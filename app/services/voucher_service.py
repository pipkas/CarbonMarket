"""
Жизненный цикл векселя — ПОСЛЕ смены модели (см. app/models/voucher.py).

mint_voucher — ВЫПУСК нового векселя продавцом из его остатка в реестре:
  1) проверяет доступный остаток (seller_capacity_service)
  2) замораживает quantity УЕ в реестре (registry_client.freeze_units)
  3) создаёт Voucher(status=ACTIVE) с уникальным номером,
     original_seller_id == current_holder_id == продавец
  4) пишет в журнал переходов запись типа MINT
Вексель после этого существует как конкретный пронумерованный инструмент,
даже если продавец ещё не выставил его на продажу.

buy_listing — ПОКУПКА уже существующего векселя по чужому объявлению:
  1) проверяет, что объявление активно, а вексель у него всё ещё во владении
     продавца из объявления (не был перепродан/обналичен мимо этого Listing)
  2) списывает/зачисляет деньги (fixed_price — единая цена за вексель целиком)
  3) переводит Voucher.current_holder_id на покупателя
  4) закрывает Listing (SOLD)
  5) пишет в журнал переходов запись типа SALE — так в истории видно,
     через кого именно прошёл вексель и по какой цене на каждом шаге

redeem_voucher — обналичивание: ТЕКУЩИЙ держатель хочет получить реальные
УЕ на баланс в реестре. Регистровый перевод всегда идёт со счёта
ПЕРВОНАЧАЛЬНОГО продавца (там физически заморожены единицы с самого
минта) на счёт текущего держателя — независимо от того, сколько раз
вексель успел перепродаваться.

cancel_purchase — откат САМОЙ ПОСЛЕДНЕЙ покупки: покупатель возвращает
вексель предыдущему держателю, деньги идут обратно. Возможно только пока
вексель не перепродали дальше и не обналичили — история переходов при
этом не переписывается, а дополняется записью типа CANCELLATION (запись
о самой покупке остаётся в журнале как есть).
"""
from datetime import datetime

from app.core.exceptions import (
    InsufficientFundsError,
    InsufficientSellerCapacityError,
    TransferNotCancellableError,
    VoucherAlreadyRedeemedError,
    VoucherNotFoundError,
    VoucherNotOwnedError,
)
from app.models.activity import ActivityType
from app.models.carbon_unit import CarbonUnitCharacteristics
from app.models.listing import Listing, ListingStatus
from app.models.voucher import TransferType, Voucher, VoucherStatus, VoucherTransfer
from app.repositories import activity_repo
from app.repositories.listing_repo import listing_repo
from app.repositories.voucher_repo import (
    get_latest_sale_transfer,
    get_transfer_chain,
    next_voucher_number,
    voucher_repo,
    voucher_transfer_repo,
)
from app.services import seller_capacity_service
from app.services.registry_client import registry_client


def mint_voucher(seller, characteristics: CarbonUnitCharacteristics, quantity: float) -> Voucher:
    if quantity <= 0:
        raise ValueError("Объём векселя должен быть положительным")

    available = seller_capacity_service.get_available_to_mint(seller.registry_account_id, characteristics)
    if quantity > available:
        raise InsufficientSellerCapacityError(
            f"Доступно для выпуска векселя {available}, запрошено {quantity}"
        )

    freeze_ref = registry_client.freeze_units(seller.registry_account_id, characteristics, quantity)

    voucher = Voucher.new(
        original_seller_id=seller.id,
        characteristics=characteristics,
        quantity=quantity,
        number=next_voucher_number(),
        freeze_ref=freeze_ref,
    )
    voucher = voucher_repo.add(voucher)

    voucher_transfer_repo.add(VoucherTransfer.new(
        voucher_id=voucher.id, type_=TransferType.MINT, to_user_id=seller.id,
    ))

    activity_repo.log(
        seller.id, ActivityType.VOUCHER_MINTED,
        quantity=quantity, project_name=characteristics.project_name,
        related_id=voucher.id,
    )
    return voucher


def buy_listing(buyer_id: str, listing: Listing) -> Voucher:
    from app.repositories.user_repo import user_repo  # локальный импорт — избегаем цикла импортов

    if listing.status != ListingStatus.ACTIVE:
        raise VoucherNotFoundError("Объявление больше не активно")

    voucher = voucher_repo.get(listing.voucher_id)
    if not voucher or voucher.status != VoucherStatus.ACTIVE or voucher.current_holder_id != listing.seller_id:
        # Вексель успел уйти другим путём (обналичен/перепродан вне этого объявления) — рассинхрон.
        listing.status = ListingStatus.CANCELLED
        listing_repo.update(listing)
        raise VoucherNotFoundError("Этот вексель больше недоступен для покупки")

    if buyer_id == listing.seller_id:
        raise VoucherNotOwnedError("Нельзя купить собственный вексель")

    buyer = user_repo.get(buyer_id)
    seller = user_repo.get(listing.seller_id)
    if buyer.cash_balance < listing.fixed_price - 1e-6:
        raise InsufficientFundsError(required=listing.fixed_price, available=buyer.cash_balance)

    buyer.cash_balance = round(buyer.cash_balance - listing.fixed_price, 2)
    seller.cash_balance = round(seller.cash_balance + listing.fixed_price, 2)
    user_repo.update(buyer)
    user_repo.update(seller)

    voucher.current_holder_id = buyer_id
    voucher_repo.update(voucher)

    listing.status = ListingStatus.SOLD
    listing_repo.update(listing)

    voucher_transfer_repo.add(VoucherTransfer.new(
        voucher_id=voucher.id, type_=TransferType.SALE,
        from_user_id=seller.id, to_user_id=buyer_id,
        price=listing.fixed_price, listing_id=listing.id,
    ))

    activity_repo.log(
        seller.id, ActivityType.SALE,
        quantity=voucher.quantity, amount=listing.fixed_price,
        project_name=voucher.characteristics.project_name,
        counterparty_name=buyer.display_name,
        related_id=voucher.id,
    )
    return voucher


def redeem_voucher(user_id: str, voucher_id: str) -> Voucher:
    from app.repositories.user_repo import user_repo

    voucher = voucher_repo.get(voucher_id)
    if not voucher or voucher.current_holder_id != user_id:
        raise VoucherNotFoundError(voucher_id)
    if voucher.status == VoucherStatus.REDEEMED:
        raise VoucherAlreadyRedeemedError("Вексель уже обналичен")

    holder = user_repo.get(user_id)
    original_seller = user_repo.get(voucher.original_seller_id)

    registry_client.transfer_units(
        from_account=original_seller.registry_account_id,
        to_account=holder.registry_account_id,
        characteristics=voucher.characteristics,
        quantity=voucher.quantity,
        freeze_ref=voucher.registry_freeze_ref,
    )

    voucher.status = VoucherStatus.REDEEMED
    voucher.redeemed_at = datetime.utcnow()
    voucher_repo.update(voucher)

    activity_repo.log(
        user_id, ActivityType.VOUCHER_REDEEMED,
        quantity=voucher.quantity, project_name=voucher.characteristics.project_name,
        related_id=voucher.id,
    )
    return voucher


def cancel_purchase(user_id: str, voucher_id: str) -> Voucher:
    from app.repositories.user_repo import user_repo

    voucher = voucher_repo.get(voucher_id)
    if not voucher or voucher.current_holder_id != user_id:
        raise VoucherNotFoundError(voucher_id)
    if voucher.status == VoucherStatus.REDEEMED:
        raise TransferNotCancellableError("Вексель уже обналичен — отменить покупку нельзя")

    latest_sale = get_latest_sale_transfer(voucher.id)
    if not latest_sale or latest_sale.type != TransferType.SALE or latest_sale.to_user_id != user_id:
        raise TransferNotCancellableError(
            "Отменить можно только последнюю покупку — либо вексель был получен не покупкой (выпущен вами), "
            "либо его уже перепродали дальше"
        )

    previous_holder_id = latest_sale.from_user_id
    price = latest_sale.price or 0.0

    buyer = user_repo.get(user_id)
    seller = user_repo.get(previous_holder_id)

    if seller:
        seller.cash_balance = round(seller.cash_balance - price, 2)
        user_repo.update(seller)
    buyer.cash_balance = round(buyer.cash_balance + price, 2)
    user_repo.update(buyer)

    voucher.current_holder_id = previous_holder_id
    voucher_repo.update(voucher)

    voucher_transfer_repo.add(VoucherTransfer.new(
        voucher_id=voucher.id, type_=TransferType.CANCELLATION,
        from_user_id=user_id, to_user_id=previous_holder_id,
        listing_id=latest_sale.listing_id,
    ))

    # Объявление, по которому шла эта покупка, снова открываем — прежний
    # держатель, скорее всего, хочет предложить вексель дальше по той же цене.
    if latest_sale.listing_id:
        listing = listing_repo.get(latest_sale.listing_id)
        if listing:
            listing.status = ListingStatus.ACTIVE
            listing_repo.update(listing)

    activity_repo.log(
        previous_holder_id, ActivityType.SALE_CANCELLED,
        quantity=voucher.quantity, amount=price,
        project_name=voucher.characteristics.project_name,
        counterparty_name=buyer.display_name,
        related_id=voucher.id,
    )
    activity_repo.log(
        user_id, ActivityType.VOUCHER_CANCELLED,
        quantity=voucher.quantity, amount=price,
        project_name=voucher.characteristics.project_name,
        related_id=voucher.id,
    )
    return voucher


def get_ownership_chain(voucher_id: str) -> list[VoucherTransfer]:
    return get_transfer_chain(voucher_id)
