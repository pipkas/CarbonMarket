"""
Управление объявлениями продавца + публичная витрина рынка (доступна без
авторизации — покупать/продавать нельзя, но смотреть и сортировать можно).
"""
from fastapi import APIRouter, Depends

from app.core.dependencies import get_current_user
from app.models.carbon_unit import CarbonUnitCharacteristics
from app.models.listing import Listing
from app.models.user import User
from app.repositories.listing_repo import get_by_seller
from app.repositories.user_repo import user_repo
from app.schemas.carbon_unit import CharacteristicsFilterDTO
from app.schemas.listing import CreateListingRequest, ListingResponse
from app.services import listing_service
from app.services.seller_capacity_service import get_available_for_sale

router = APIRouter(prefix="/listings", tags=["listings"])


def _to_domain_characteristics(dto: CharacteristicsFilterDTO) -> CarbonUnitCharacteristics:
    return CarbonUnitCharacteristics(**dto.model_dump())


def _to_response(listing: Listing) -> ListingResponse:
    seller = user_repo.get(listing.seller_id)
    return ListingResponse(
        id=listing.id,
        seller_id=listing.seller_id,
        seller_display_name=seller.display_name if seller else "—",
        characteristics=CharacteristicsFilterDTO(**listing.characteristics.__dict__),
        total_quantity=listing.total_quantity,
        remaining_quantity=listing.remaining_quantity,
        pricing_mode=listing.pricing_mode,
        price_per_unit=listing.price_per_unit,
        flat_fee_per_deal=listing.flat_fee_per_deal,
        base_reference_price=listing.base_reference_price,
        min_deal_quantity=listing.min_deal_quantity,
        max_deal_quantity=listing.max_deal_quantity,
        status=listing.status,
        created_at=listing.created_at,
    )


@router.get("/available-capacity")
def available_capacity(characteristics: CharacteristicsFilterDTO = Depends(), user: User = Depends(get_current_user)):
    """Сколько УЕ данных характеристик продавец реально может выставить прямо сейчас."""
    qty = get_available_for_sale(user.registry_account_id, user.id, _to_domain_characteristics(characteristics))
    return {"available_quantity": qty}


@router.post("", response_model=ListingResponse)
def create_listing(payload: CreateListingRequest, user: User = Depends(get_current_user)):
    listing = listing_service.create_listing(
        seller=user,
        characteristics=_to_domain_characteristics(payload.characteristics),
        total_quantity=payload.total_quantity,
        pricing_mode=payload.pricing_mode,
        base_reference_price=payload.base_reference_price,
        price_per_unit=payload.price_per_unit,
        flat_fee_per_deal=payload.flat_fee_per_deal,
        min_deal_quantity=payload.min_deal_quantity,
        max_deal_quantity=payload.max_deal_quantity,
    )
    return _to_response(listing)


@router.get("/mine", response_model=list[ListingResponse])
def my_listings(user: User = Depends(get_current_user)):
    return [_to_response(l) for l in get_by_seller(user.id)]


@router.delete("/{listing_id}", response_model=ListingResponse)
def cancel_listing(listing_id: str, user: User = Depends(get_current_user)):
    return _to_response(listing_service.cancel_listing(user, listing_id))


@router.get("", response_model=list[ListingResponse])
def browse(characteristics: CharacteristicsFilterDTO = Depends(), sort_by: str = "price"):
    """
    Публичная витрина — доступна БЕЗ авторизации, покупать нельзя, но
    смотреть и сортировать может кто угодно.
    """
    filt = _to_domain_characteristics(characteristics)
    has_filter = any(v is not None for v in filt.__dict__.values())
    listings = listing_service.browse_listings(filt if has_filter else None, sort_by=sort_by)
    return [_to_response(l) for l in listings]
