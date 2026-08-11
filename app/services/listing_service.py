"""
Управление объявлениями продавца (создание / просмотр / отмена) и ручной
просмотр рынка покупателем ("режим 2: выбрать продавца" из ТЗ — покупатель
сам видит все предложения и сортирует их, в отличие от "купить сейчас",
где всё собирает алгоритм — см. matching_service.py).
"""
from datetime import datetime

from app.core.exceptions import InsufficientSellerCapacityError, ListingNotFoundError
from app.models.carbon_unit import CarbonUnitCharacteristics
from app.models.listing import Listing, ListingStatus, PricingMode
from app.models.user import User
from app.repositories.listing_repo import listing_repo, get_active
from app.services.seller_capacity_service import get_available_for_sale


def create_listing(
    seller: User,
    characteristics: CarbonUnitCharacteristics,
    total_quantity: float,
    pricing_mode: PricingMode,
    base_reference_price: float,
    price_per_unit: float | None,
    flat_fee_per_deal: float | None,
    min_deal_quantity: float | None,
    max_deal_quantity: float | None,
) -> Listing:
    # 1. Проверяем, что продавцу физически есть что продавать в таком объёме
    #    (баланс в реестре минус уже выставленное в других объявлениях —
    #    см. seller_capacity_service.get_available_for_sale)
    available = get_available_for_sale(seller.registry_account_id, seller.id, characteristics)
    if total_quantity > available:
        raise InsufficientSellerCapacityError(
            f"Доступно для продажи {available}, запрошено {total_quantity}"
        )

    # 2. Валидация гибких правил объёма сделки: min не может быть больше max,
    #    min/max не может превышать total_quantity.
    if min_deal_quantity and max_deal_quantity and min_deal_quantity > max_deal_quantity:
        raise ValueError("min_deal_quantity не может быть больше max_deal_quantity")
    if (min_deal_quantity or 0) > total_quantity:
        raise ValueError("min_deal_quantity не может превышать total_quantity")

    # 3. Валидация ценообразования: ровно один из двух режимов должен быть задан
    if pricing_mode == PricingMode.PER_UNIT_MARKUP and price_per_unit is None:
        raise ValueError("Для PER_UNIT_MARKUP нужно указать price_per_unit")
    if pricing_mode == PricingMode.FLAT_FEE_PER_DEAL and flat_fee_per_deal is None:
        raise ValueError("Для FLAT_FEE_PER_DEAL нужно указать flat_fee_per_deal")

    listing = Listing.new(
        seller_id=seller.id,
        characteristics=characteristics,
        total_quantity=total_quantity,
        pricing_mode=pricing_mode,
        base_reference_price=base_reference_price,
        price_per_unit=price_per_unit,
        flat_fee_per_deal=flat_fee_per_deal,
        min_deal_quantity=min_deal_quantity,
        max_deal_quantity=max_deal_quantity,
    )
    return listing_repo.add(listing)


def cancel_listing(seller: User, listing_id: str) -> Listing:
    listing = listing_repo.get(listing_id)
    if not listing or listing.seller_id != seller.id:
        raise ListingNotFoundError(listing_id)
    listing.status = ListingStatus.CANCELLED
    return listing_repo.update(listing)


def browse_listings(
    characteristics_filter: CarbonUnitCharacteristics | None = None,
    sort_by: str = "price",  # "price" | "quantity" | "created_at"
) -> list[Listing]:
    """
    "Режим 2: выбрать продавца". Возвращает все активные объявления,
    подходящие под фильтр характеристик, отсортированные по выбору
    покупателя. deal_quantity для сортировки по цене берём как
    remaining_quantity объявления (цена "если брать всё сразу") —
    фронт может пересчитать effective_price_per_unit под конкретный
    объём, который введёт пользователь на карточке объявления.
    """
    listings = get_active()
    if characteristics_filter:
        listings = [l for l in listings if l.characteristics.matches(characteristics_filter)]

    if sort_by == "price":
        listings.sort(key=lambda l: l.effective_price_per_unit(l.remaining_quantity))
    elif sort_by == "quantity":
        listings.sort(key=lambda l: -l.remaining_quantity)
    elif sort_by == "created_at":
        listings.sort(key=lambda l: l.created_at, reverse=True)

    return listings
