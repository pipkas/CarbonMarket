"""
Жизненный цикл векселя.

issue_simple_voucher — выпуск одного "элементарного" векселя в рамках
сделки с одним объявлением:
  1) проверяет DealConstraintViolationError (min/max за сделку у Listing)
  2) списывает quantity с Listing.remaining_quantity (и переводит в
     SOLD_OUT, если дошло до нуля)
  3) замораживает quantity в реестре на счету продавца
     (registry_client.freeze_units) — получает freeze_ref
  4) создаёт SimpleVoucher(status=ISSUED) и сохраняет в voucher_repo

build_composite_voucher — оборачивает список только что выпущенных
SimpleVoucher в один CompositeVoucher для удобства покупателя (ТЗ:
"формирует один вексель, в котором могут быть несколько векселей от
разных продавцов").

redeem_composite_voucher — обналичивание: покупатель хочет получить
УЕ НА БАЛАНС в реестре, а не просто владеть правом требования. Для
каждого компонента вызывается registry_client.transfer_units, вексель
переводится в REDEEMED. Именно в этот момент, согласно ТЗ
("если в конце концов необходимо получить на балансе углеродные единицы,
а не просто вексели"), УЕ реально поступают на счёт покупателя.

До вызова redeem покупатель просто владеет пакетом векселей — это
осознанно не то же самое, что владение УЕ, и допускает в будущем
вторичный рынок перепродажи самих векселей (не реализовано в MVP).

ДЕНЬГИ: в отличие от УЕ (которые реально переходят к покупателю только
при обналичивании), деньги списываются с покупателя и зачисляются
продавцу сразу в момент выпуска SimpleVoucher — сделка в этот момент уже
считается совершённой (продавец получил оплату, покупатель получил право
требования на УЕ). Это отражается и в ленте активности (app/models/activity.py):
продавцу приходит событие SALE, покупателю — PURCHASE.
"""
from app.core.exceptions import (
    DealConstraintViolationError,
    VoucherNotFoundError,
    VoucherNotCancellableError,
    InsufficientFundsError,
)
from app.models.activity import ActivityType
from app.models.listing import Listing, ListingStatus
from app.models.voucher import SimpleVoucher, CompositeVoucher, VoucherStatus
from app.repositories import activity_repo
from app.repositories.listing_repo import listing_repo
from app.repositories.voucher_repo import simple_voucher_repo, composite_voucher_repo, get_composite_with_components
from app.services.registry_client import registry_client


def issue_simple_voucher(listing: Listing, buyer_id: str, quantity: float) -> SimpleVoucher:
    from app.repositories.user_repo import user_repo  # локальный импорт — избегаем цикла импортов

    if listing.min_deal_quantity and quantity < listing.min_deal_quantity:
        raise DealConstraintViolationError(
            f"Минимальный объём сделки по объявлению {listing.id} — {listing.min_deal_quantity}"
        )
    if listing.max_deal_quantity and quantity > listing.max_deal_quantity:
        raise DealConstraintViolationError(
            f"Максимальный объём сделки по объявлению {listing.id} — {listing.max_deal_quantity}"
        )
    if quantity > listing.remaining_quantity + 1e-9:
        raise DealConstraintViolationError("Запрошенный объём превышает остаток по объявлению")

    price_per_unit = listing.effective_price_per_unit(quantity)
    total_price = round(quantity * price_per_unit, 2)

    buyer = user_repo.get(buyer_id)
    seller = user_repo.get(listing.seller_id)
    if buyer.cash_balance < total_price - 1e-6:
        raise InsufficientFundsError(required=total_price, available=buyer.cash_balance)

    # 1. Продавец получает "заявку на продавца" в реестре
    freeze_ref = registry_client.freeze_units(seller.registry_account_id, listing.characteristics, quantity)

    # 2. Уменьшаем остаток объявления
    listing.remaining_quantity -= quantity
    if listing.remaining_quantity <= 1e-9:
        listing.status = ListingStatus.SOLD_OUT
    listing_repo.update(listing)

    # 3. Деньги: списываем с покупателя, зачисляем продавцу — сделка совершена
    buyer.cash_balance = round(buyer.cash_balance - total_price, 2)
    seller.cash_balance = round(seller.cash_balance + total_price, 2)
    user_repo.update(buyer)
    user_repo.update(seller)

    # 4. Создаём вексель
    voucher = SimpleVoucher.new(
        listing_id=listing.id,
        seller_id=listing.seller_id,
        buyer_id=buyer_id,
        characteristics=listing.characteristics,
        quantity=quantity,
        price_per_unit=price_per_unit,
        freeze_ref=freeze_ref,
    )
    voucher = simple_voucher_repo.add(voucher)

    # 5. Продавцу — запись в ленту активности: у него купили УЕ
    activity_repo.log(
        seller.id, ActivityType.SALE,
        quantity=quantity, amount=voucher.total_price,
        project_name=listing.characteristics.project_name,
        counterparty_name=buyer.display_name,
        related_id=voucher.id,
    )
    return voucher


def build_composite_voucher(buyer_id: str, simple_vouchers: list[SimpleVoucher], scenario: str) -> CompositeVoucher:
    total_quantity = sum(v.quantity for v in simple_vouchers)
    total_price = sum(v.total_price for v in simple_vouchers)
    composite = CompositeVoucher.new(
        buyer_id=buyer_id,
        component_voucher_ids=[v.id for v in simple_vouchers],
        total_quantity=total_quantity,
        total_price=total_price,
        scenario=scenario,
    )
    composite = composite_voucher_repo.add(composite)

    # Покупателю — запись в ленту активности: он купил УЕ на рынке.
    # Название проекта/продавца показываем, только если покупка была из
    # одного источника — иначе это агрегированная сделка сразу с несколькими
    # продавцами, единого контрагента для неё нет.
    project_name = None
    counterparty_name = None
    if len(simple_vouchers) == 1:
        from app.repositories.user_repo import user_repo
        only = simple_vouchers[0]
        project_name = only.characteristics.project_name
        seller = user_repo.get(only.seller_id)
        counterparty_name = seller.display_name if seller else None

    activity_repo.log(
        buyer_id, ActivityType.PURCHASE,
        quantity=total_quantity, amount=total_price,
        project_name=project_name, counterparty_name=counterparty_name,
        related_id=composite.id,
    )
    return composite


def redeem_composite_voucher(buyer_id: str, composite_id: str) -> CompositeVoucher:
    composite, components = get_composite_with_components(composite_id)
    if not composite or composite.buyer_id != buyer_id:
        raise VoucherNotFoundError(composite_id)

    buyer_registry_account = _get_buyer_registry_account(buyer_id)

    redeemed_qty = 0.0
    for v in components:
        if v.status != VoucherStatus.ISSUED:
            continue
        seller_account = _get_seller_registry_account(v.seller_id)
        registry_client.transfer_units(
            from_account=seller_account,
            to_account=buyer_registry_account,
            characteristics=v.characteristics,
            quantity=v.quantity,
            freeze_ref=v.registry_freeze_ref,
        )
        v.status = VoucherStatus.REDEEMED
        simple_voucher_repo.update(v)
        redeemed_qty += v.quantity

    if redeemed_qty > 1e-9:
        activity_repo.log(
            buyer_id, ActivityType.VOUCHER_REDEEMED,
            quantity=redeemed_qty, related_id=composite.id,
        )

    return composite


def cancel_composite_voucher(buyer_id: str, composite_id: str) -> CompositeVoucher:
    """
    Отмена векселя ДО обналичивания: покупатель передумал. Возможна только
    пока ни один из компонентов не обналичен (иначе УЕ уже реально ушли
    покупателю в реестре, и откатывать сделку небезопасно для MVP).

    Для каждого компонента:
      - снимаем заморозку в реестре (registry_client.unfreeze_units)
      - возвращаем quantity обратно в остаток объявления, и если оно было
        распродано (SOLD_OUT) — снова делаем его активным
      - откатываем деньги: продавцу списываем то, что он получил при
        покупке, покупателю возвращаем потраченное
      - переводим SimpleVoucher в статус CANCELLED
    """
    from app.repositories.user_repo import user_repo

    composite, components = get_composite_with_components(composite_id)
    if not composite or composite.buyer_id != buyer_id:
        raise VoucherNotFoundError(composite_id)

    if any(v.status != VoucherStatus.ISSUED for v in components):
        raise VoucherNotCancellableError(
            "Вексель уже частично или полностью обналичен либо отменён — отмена невозможна"
        )

    buyer = user_repo.get(buyer_id)

    for v in components:
        registry_client.unfreeze_units(v.registry_freeze_ref)

        listing = listing_repo.get(v.listing_id)
        if listing:
            listing.remaining_quantity += v.quantity
            if listing.status == ListingStatus.SOLD_OUT:
                listing.status = ListingStatus.ACTIVE
            listing_repo.update(listing)

        seller = user_repo.get(v.seller_id)
        if seller:
            seller.cash_balance = round(seller.cash_balance - v.total_price, 2)
            user_repo.update(seller)
        if buyer:
            buyer.cash_balance = round(buyer.cash_balance + v.total_price, 2)

        activity_repo.log(
            v.seller_id, ActivityType.SALE_CANCELLED,
            quantity=v.quantity, amount=v.total_price,
            project_name=v.characteristics.project_name,
            counterparty_name=buyer.display_name if buyer else None,
            related_id=v.id,
        )

        v.status = VoucherStatus.CANCELLED
        simple_voucher_repo.update(v)

    if buyer:
        user_repo.update(buyer)

    activity_repo.log(
        buyer_id, ActivityType.VOUCHER_CANCELLED,
        quantity=composite.total_quantity, amount=composite.total_price,
        related_id=composite.id,
    )

    return composite


def _get_seller_registry_account(seller_id: str) -> str:
    from app.repositories.user_repo import user_repo
    return user_repo.get(seller_id).registry_account_id


def _get_buyer_registry_account(buyer_id: str) -> str:
    from app.repositories.user_repo import user_repo
    return user_repo.get(buyer_id).registry_account_id
