"""
Управление объявлениями — ПОСЛЕ смены модели.

create_listing теперь не принимает характеристики/количество/цену за
единицу — вместо этого продавец выбирает КОНКРЕТНЫЙ, уже выпущенный
вексель (voucher_id, см. voucher_service.mint_voucher) и назначает ему
ЕДИНУЮ фиксированную цену (fixed_price). Продавцом объявления может быть
и тот, кто изначально выпустил вексель, и тот, кто перекупил его на
вторичном рынке — в обоих случаях проверяем, что seller — это ТЕКУЩИЙ
держатель векселя на момент выставления.

browse_listings — публичная витрина (доступна без авторизации): все
активные объявления, с возможностью фильтровать по характеристикам
векселя и сортировать. Поскольку у Listing больше нет своих
характеристик/количества — они читаются из связанного Voucher.
"""
from app.core.exceptions import (
    ListingNotFoundError,
    VoucherAlreadyListedError,
    VoucherAlreadyRedeemedError,
    VoucherNotFoundError,
    VoucherNotOwnedError,
)
from app.models.activity import ActivityType
from app.models.carbon_unit import CarbonUnitCharacteristics
from app.models.listing import Listing, ListingStatus
from app.models.voucher import VoucherStatus
from app.repositories import activity_repo
from app.repositories.listing_repo import get_active, get_active_listing_for_voucher, listing_repo
from app.repositories.voucher_repo import voucher_repo


def create_listing(seller, voucher_id: str, fixed_price: float) -> Listing:
    if fixed_price <= 0:
        raise ValueError("Цена должна быть положительной")

    voucher = voucher_repo.get(voucher_id)
    if not voucher:
        raise VoucherNotFoundError(voucher_id)
    if voucher.current_holder_id != seller.id:
        raise VoucherNotOwnedError("Вы можете выставить на продажу только тот вексель, которым владеете")
    if voucher.status == VoucherStatus.REDEEMED:
        raise VoucherAlreadyRedeemedError("Вексель уже обналичен — выставить его на продажу нельзя")
    if get_active_listing_for_voucher(voucher_id):
        raise VoucherAlreadyListedError("У этого векселя уже есть активное объявление")

    listing = Listing.new(voucher_id=voucher_id, seller_id=seller.id, fixed_price=fixed_price)
    listing = listing_repo.add(listing)

    activity_repo.log(
        seller.id, ActivityType.LISTING_CREATED,
        quantity=voucher.quantity, amount=fixed_price,
        project_name=voucher.characteristics.project_name,
        related_id=listing.id,
    )
    return listing


def cancel_listing(seller, listing_id: str) -> Listing:
    listing = listing_repo.get(listing_id)
    if not listing or listing.seller_id != seller.id:
        raise ListingNotFoundError(listing_id)
    if listing.status != ListingStatus.ACTIVE:
        raise ListingNotFoundError(listing_id)

    listing.status = ListingStatus.CANCELLED
    listing = listing_repo.update(listing)

    voucher = voucher_repo.get(listing.voucher_id)
    activity_repo.log(
        seller.id, ActivityType.LISTING_CANCELLED,
        quantity=voucher.quantity if voucher else None,
        project_name=voucher.characteristics.project_name if voucher else None,
        related_id=listing.id,
    )
    return listing


def browse_listings(
    characteristics_filter: CarbonUnitCharacteristics | None = None,
    sort_by: str = "price",  # "price" | "quantity" | "created_at"
) -> list[Listing]:
    listings = get_active()
    enriched = [(l, voucher_repo.get(l.voucher_id)) for l in listings]
    enriched = [(l, v) for l, v in enriched if v is not None]

    if characteristics_filter:
        enriched = [(l, v) for l, v in enriched if v.characteristics.matches(characteristics_filter)]

    if sort_by == "price":
        enriched.sort(key=lambda pair: pair[0].fixed_price / pair[1].quantity)
    elif sort_by == "quantity":
        enriched.sort(key=lambda pair: -pair[1].quantity)
    elif sort_by == "created_at":
        enriched.sort(key=lambda pair: pair[0].created_at, reverse=True)

    return [l for l, _ in enriched]
