"""
Управление объявлениями продавца + публичная витрина рынка (доступна без
авторизации — покупать/продавать нельзя, но смотреть и сортировать можно).

Объявление теперь ссылается на конкретный вексель (voucher_id) и содержит
только fixed_price — см. app/models/listing.py.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.dependencies import get_current_user
from app.models.carbon_unit import CarbonUnitCharacteristics
from app.models.listing import Listing
from app.models.user import User
from app.repositories.listing_repo import get_active, listing_repo
from app.repositories.user_repo import user_repo
from app.repositories.voucher_repo import voucher_repo
from app.schemas.carbon_unit import CharacteristicsFilterDTO
from app.schemas.listing import CreateListingRequest, ListingResponse
from app.services import listing_service

router = APIRouter(prefix="/listings", tags=["listings"])


def _to_domain_characteristics(dto: CharacteristicsFilterDTO) -> CarbonUnitCharacteristics:
    return CarbonUnitCharacteristics(**dto.model_dump())


def _to_response(listing: Listing) -> ListingResponse:
    seller = user_repo.get(listing.seller_id)
    voucher = voucher_repo.get(listing.voucher_id)
    return ListingResponse(
        id=listing.id,
        voucher_id=listing.voucher_id,
        voucher_number=voucher.number if voucher else "—",
        seller_id=listing.seller_id,
        seller_display_name=seller.display_name if seller else "—",
        characteristics=CharacteristicsFilterDTO(**voucher.characteristics.__dict__) if voucher else CharacteristicsFilterDTO(),
        quantity=voucher.quantity if voucher else 0.0,
        fixed_price=listing.fixed_price,
        price_per_unit=(listing.fixed_price / voucher.quantity) if voucher and voucher.quantity else 0.0,
        status=listing.status,
        created_at=listing.created_at,
    )


@router.post("", response_model=ListingResponse)
def create_listing(payload: CreateListingRequest, user: User = Depends(get_current_user)):
    listing = listing_service.create_listing(
        seller=user,
        voucher_id=payload.voucher_id,
        fixed_price=payload.fixed_price,
    )
    return _to_response(listing)


@router.get("/mine", response_model=list[ListingResponse])
def my_listings(user: User = Depends(get_current_user)):
    listings = listing_repo.filter(lambda l: l.seller_id == user.id)
    return [_to_response(l) for l in listings]


@router.delete("/{listing_id}", response_model=ListingResponse)
def cancel_listing(listing_id: str, user: User = Depends(get_current_user)):
    return _to_response(listing_service.cancel_listing(user, listing_id))


class SellerPublicProfile(BaseModel):
    id: str
    display_name: str
    user_type: str
    active_listings: list[ListingResponse]


@router.get("/seller/{seller_id}", response_model=SellerPublicProfile)
def seller_profile(seller_id: str):
    """Публичный профиль продавца: имя, тип участника, активные объявления."""
    seller = user_repo.get(seller_id)
    if not seller:
        raise HTTPException(status_code=404, detail="Продавец не найден")
    active = [_to_response(l) for l in listing_repo.filter(lambda l: l.seller_id == seller_id) if l.status == "ACTIVE"]
    return SellerPublicProfile(
        id=seller.id,
        display_name=seller.display_name,
        user_type=seller.user_type.value,
        active_listings=active,
    )


@router.get("", response_model=list[ListingResponse])
def browse(characteristics: CharacteristicsFilterDTO = Depends(), sort_by: str = "price"):
    """Публичная витрина — доступна БЕЗ авторизации, покупать нельзя, но смотреть и сортировать может кто угодно."""
    filt = _to_domain_characteristics(characteristics)
    has_filter = any(v is not None for v in filt.__dict__.values())
    listings = listing_service.browse_listings(filt if has_filter else None, sort_by=sort_by)
    return [_to_response(l) for l in listings]
