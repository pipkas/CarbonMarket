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
"""
from app.core.exceptions import DealConstraintViolationError, VoucherNotFoundError
from app.models.listing import Listing, ListingStatus
from app.models.voucher import SimpleVoucher, CompositeVoucher, VoucherStatus
from app.repositories.listing_repo import listing_repo
from app.repositories.voucher_repo import simple_voucher_repo, composite_voucher_repo, get_composite_with_components
from app.services.registry_client import registry_client


def issue_simple_voucher(listing: Listing, buyer_id: str, quantity: float) -> SimpleVoucher:
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

    # 1. Продавец получает "заявку на продавца" в реестре
    seller = _get_seller_registry_account(listing.seller_id)
    freeze_ref = registry_client.freeze_units(seller, listing.characteristics, quantity)

    # 2. Уменьшаем остаток объявления
    listing.remaining_quantity -= quantity
    if listing.remaining_quantity <= 1e-9:
        listing.status = ListingStatus.SOLD_OUT
    listing_repo.update(listing)

    # 3. Создаём вексель
    voucher = SimpleVoucher.new(
        listing_id=listing.id,
        seller_id=listing.seller_id,
        buyer_id=buyer_id,
        characteristics=listing.characteristics,
        quantity=quantity,
        price_per_unit=price_per_unit,
        freeze_ref=freeze_ref,
    )
    return simple_voucher_repo.add(voucher)


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
    return composite_voucher_repo.add(composite)


def redeem_composite_voucher(buyer_id: str, composite_id: str) -> CompositeVoucher:
    composite, components = get_composite_with_components(composite_id)
    if not composite or composite.buyer_id != buyer_id:
        raise VoucherNotFoundError(composite_id)

    buyer_registry_account = _get_buyer_registry_account(buyer_id)

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

    return composite


def _get_seller_registry_account(seller_id: str) -> str:
    from app.repositories.user_repo import user_repo
    return user_repo.get(seller_id).registry_account_id


def _get_buyer_registry_account(buyer_id: str) -> str:
    from app.repositories.user_repo import user_repo
    return user_repo.get(buyer_id).registry_account_id
