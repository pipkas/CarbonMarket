"""
Покупка углеродных единиц: подбор по объёму, подбор по бюджету, прямая
покупка по конкретному объявлению — плюс превью ("quote") для первых двух,
которое можно смотреть без авторизации, чтобы покупатель видел топ
предложений ДО оформления сделки.
"""
from fastapi import APIRouter, Depends

from app.core.dependencies import get_current_user
from app.core.exceptions import ListingNotFoundError
from app.models.carbon_unit import CarbonUnitCharacteristics
from app.models.user import User
from app.repositories.listing_repo import listing_repo
from app.repositories.user_repo import user_repo
from app.schemas.carbon_unit import CharacteristicsFilterDTO
from app.schemas.market import (
    BuyExactQuantityRequest,
    InvestAmountRequest,
    ReserveFromListingRequest,
    CompositeVoucherResponse,
    QuoteOfferDTO,
    QuoteResponse,
)
from app.services import matching_service
from app.services.matching_service import AllocationResult

router = APIRouter(prefix="/market", tags=["market"])

TOP_OFFERS_SHOWN = 5


def _filter_or_none(dto) -> CarbonUnitCharacteristics | None:
    if dto is None:
        return None
    data = dto.model_dump()
    if not any(v is not None for v in data.values()):
        return None
    return CarbonUnitCharacteristics(**data)


def _allocation_to_quote(allocation: AllocationResult, *, quantity_mode: bool) -> QuoteResponse:
    shown = allocation.items[:TOP_OFFERS_SHOWN]
    offers = []
    for item in shown:
        seller = user_repo.get(item.listing.seller_id)
        offers.append(QuoteOfferDTO(
            listing_id=item.listing.id,
            seller_id=item.listing.seller_id,
            seller_display_name=seller.display_name if seller else "—",
            characteristics=CharacteristicsFilterDTO(**item.listing.characteristics.__dict__),
            price_per_unit=item.price_per_unit,
            quantity=item.quantity,
            subtotal=item.subtotal,
            min_deal_quantity=item.listing.min_deal_quantity,
            max_deal_quantity=item.listing.max_deal_quantity,
        ))
    return QuoteResponse(
        offers=offers,
        offers_beyond_shown=max(0, len(allocation.items) - TOP_OFFERS_SHOWN),
        total_quantity=allocation.total_quantity,
        total_price=allocation.total_price,
        unmet_quantity=allocation.unmet_quantity if quantity_mode else None,
        leftover_budget=None if quantity_mode else allocation.leftover_budget,
    )


@router.post("/quote/buy-exact-quantity", response_model=QuoteResponse)
def quote_buy_exact_quantity(payload: BuyExactQuantityRequest):
    """
    Публичное превью: из каких предложений сложится покупка нужного
    количества УЕ, без резервирования и без авторизации.
    """
    allocation = matching_service.preview_buy_exact_quantity(
        quantity_needed=payload.quantity_needed,
        characteristics_filter=_filter_or_none(payload.characteristics),
    )
    return _allocation_to_quote(allocation, quantity_mode=True)


@router.post("/quote/invest-amount", response_model=QuoteResponse)
def quote_invest_amount(payload: InvestAmountRequest):
    """Публичное превью для подбора по бюджету."""
    allocation = matching_service.preview_invest_amount(
        budget_amount=payload.budget_amount,
        characteristics_filter=_filter_or_none(payload.characteristics),
    )
    return _allocation_to_quote(allocation, quantity_mode=False)


@router.post("/buy-exact-quantity", response_model=CompositeVoucherResponse)
def buy_exact_quantity(payload: BuyExactQuantityRequest, user: User = Depends(get_current_user)):
    """Оформление покупки нужного объёма — требует авторизации."""
    return matching_service.buy_exact_quantity(
        buyer_id=user.id,
        quantity_needed=payload.quantity_needed,
        characteristics_filter=_filter_or_none(payload.characteristics),
    )


@router.post("/invest-amount", response_model=CompositeVoucherResponse)
def invest_amount(payload: InvestAmountRequest, user: User = Depends(get_current_user)):
    """Оформление покупки на заданный бюджет — требует авторизации."""
    return matching_service.invest_amount(
        buyer_id=user.id,
        budget_amount=payload.budget_amount,
        characteristics_filter=_filter_or_none(payload.characteristics),
    )


@router.post("/reserve-from-listing", response_model=CompositeVoucherResponse)
def reserve_from_listing(payload: ReserveFromListingRequest, user: User = Depends(get_current_user)):
    """Прямая покупка по конкретному, самостоятельно выбранному объявлению — требует авторизации."""
    listing = listing_repo.get(payload.listing_id)
    if not listing:
        raise ListingNotFoundError(payload.listing_id)
    return matching_service.reserve_from_listing(user.id, listing, payload.quantity)
