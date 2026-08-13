"""
Покупка векселей: подбор по объёму, подбор по бюджету, прямая покупка
конкретного объявления — плюс превью ("quote") для первых двух, которое
можно смотреть без авторизации.
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
    BuyListingRequest,
    InvestAmountRequest,
    PurchaseResultResponse,
    QuoteOfferDTO,
    QuoteResponse,
)
from app.schemas.voucher import VoucherResponse
from app.services import matching_service
from app.services.matching_service import AllocationResult

router = APIRouter(prefix="/market", tags=["market"])


def _filter_or_none(dto) -> CarbonUnitCharacteristics | None:
    if dto is None:
        return None
    data = dto.model_dump()
    if not any(v is not None for v in data.values()):
        return None
    return CarbonUnitCharacteristics(**data)


def _allocation_to_quote(allocation: AllocationResult, *, quantity_mode: bool) -> QuoteResponse:
    offers = []
    for item in allocation.items:
        seller = user_repo.get(item.listing.seller_id)
        offers.append(QuoteOfferDTO(
            listing_id=item.listing.id,
            voucher_id=item.voucher.id,
            voucher_number=item.voucher.number,
            seller_id=item.listing.seller_id,
            seller_display_name=seller.display_name if seller else "—",
            characteristics=CharacteristicsFilterDTO(**item.voucher.characteristics.__dict__),
            quantity=item.voucher.quantity,
            price_per_unit=item.price_per_unit,
            fixed_price=item.price,
        ))
    return QuoteResponse(
        offers=offers,
        offers_beyond_shown=0,
        total_quantity=allocation.total_quantity,
        total_price=allocation.total_price,
        unmet_quantity=allocation.unmet_quantity if quantity_mode else None,
        leftover_budget=None if quantity_mode else allocation.leftover_budget,
    )


def _purchase_to_response(result) -> PurchaseResultResponse:
    from app.api.routes_vouchers import _to_response as voucher_to_response
    return PurchaseResultResponse(
        vouchers=[voucher_to_response(v) for v in result.vouchers],
        total_quantity=result.total_quantity,
        total_price=result.total_price,
        scenario=result.scenario,
    )


@router.post("/quote/buy-exact-quantity", response_model=QuoteResponse)
def quote_buy_exact_quantity(payload: BuyExactQuantityRequest):
    """Публичное превью: какие именно векселя вошли бы в покупку нужного объёма, без резервирования и без авторизации."""
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


@router.post("/buy-exact-quantity", response_model=PurchaseResultResponse)
def buy_exact_quantity(payload: BuyExactQuantityRequest, user: User = Depends(get_current_user)):
    """Оформление покупки нужного объёма — требует авторизации."""
    result = matching_service.buy_exact_quantity(
        buyer_id=user.id,
        quantity_needed=payload.quantity_needed,
        characteristics_filter=_filter_or_none(payload.characteristics),
    )
    return _purchase_to_response(result)


@router.post("/invest-amount", response_model=PurchaseResultResponse)
def invest_amount(payload: InvestAmountRequest, user: User = Depends(get_current_user)):
    """Оформление покупки на заданный бюджет — требует авторизации."""
    result = matching_service.invest_amount(
        buyer_id=user.id,
        budget_amount=payload.budget_amount,
        characteristics_filter=_filter_or_none(payload.characteristics),
    )
    return _purchase_to_response(result)


@router.post("/buy-listing", response_model=VoucherResponse)
def buy_listing(payload: BuyListingRequest, user: User = Depends(get_current_user)):
    """Прямая покупка конкретного, самостоятельно выбранного объявления — требует авторизации. Вексель покупается целиком."""
    from app.api.routes_vouchers import _to_response as voucher_to_response

    listing = listing_repo.get(payload.listing_id)
    if not listing:
        raise ListingNotFoundError(payload.listing_id)
    voucher = matching_service.buy_listing_direct(user.id, listing)
    return voucher_to_response(voucher)
