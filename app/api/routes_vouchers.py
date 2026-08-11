"""Просмотр и обналичивание векселей покупателя."""
from fastapi import APIRouter, Depends

from app.core.dependencies import get_current_user
from app.models.user import User
from app.repositories.voucher_repo import get_composites_for_buyer, get_composite_with_components
from app.schemas.market import CompositeVoucherResponse
from app.services import voucher_service

router = APIRouter(prefix="/vouchers", tags=["vouchers"])


@router.get("/mine", response_model=list[CompositeVoucherResponse])
def my_vouchers(user: User = Depends(get_current_user)):
    return get_composites_for_buyer(user.id)


@router.get("/{composite_id}")
def voucher_detail(composite_id: str, user: User = Depends(get_current_user)):
    composite, components = get_composite_with_components(composite_id)
    return {"composite": composite, "components": components}


@router.post("/{composite_id}/redeem", response_model=CompositeVoucherResponse)
def redeem(composite_id: str, user: User = Depends(get_current_user)):
    """
    Обналичивание: покупателю нужны реальные УЕ на балансе в реестре,
    а не просто владение векселем (см. voucher_service.redeem_composite_voucher).
    """
    return voucher_service.redeem_composite_voucher(user.id, composite_id)
