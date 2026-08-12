"""Просмотр и обналичивание векселей покупателя."""
from fastapi import APIRouter, Depends

from app.core.dependencies import get_current_user
from app.models.user import User
from app.repositories.user_repo import user_repo
from app.repositories.voucher_repo import get_composites_for_buyer, get_composite_with_components
from app.schemas.market import CompositeVoucherResponse, CompositeVoucherDetailResponse, SimpleVoucherDTO
from app.services import voucher_service

router = APIRouter(prefix="/vouchers", tags=["vouchers"])


def _build_detail(composite, components) -> CompositeVoucherDetailResponse:
    """Собирает детальный ответ: добавляет имена продавцов и статусы."""
    dtos = []
    for v in components:
        seller = user_repo.get(v.seller_id)
        dtos.append(SimpleVoucherDTO(
            id=v.id,
            seller_id=v.seller_id,
            seller_display_name=seller.display_name if seller else "—",
            listing_id=v.listing_id,
            project_name=v.characteristics.project_name if v.characteristics else None,
            quantity=v.quantity,
            price_per_unit=v.price_per_unit,
            total_price=v.total_price,
            status=v.status.value,
            created_at=v.created_at,
            redeemed_at=v.redeemed_at,
        ))

    statuses = {d.status for d in dtos}
    if statuses == {"REDEEMED"}:
        overall = "REDEEMED"
    elif statuses == {"CANCELLED"}:
        overall = "CANCELLED"
    elif "REDEEMED" in statuses:
        overall = "PARTIAL"
    else:
        overall = "ISSUED"

    return CompositeVoucherDetailResponse(
        id=composite.id,
        buyer_id=composite.buyer_id,
        total_quantity=composite.total_quantity,
        total_price=composite.total_price,
        scenario=composite.scenario,
        created_at=composite.created_at,
        components=dtos,
        status=overall,
    )


@router.get("/mine", response_model=list[CompositeVoucherDetailResponse])
def my_vouchers(user: User = Depends(get_current_user)):
    """Все векселя покупателя с детализацией по компонентам."""
    composites = get_composites_for_buyer(user.id)
    result = []
    for composite in composites:
        _, components = get_composite_with_components(composite.id)
        result.append(_build_detail(composite, components))
    return result


@router.post("/{composite_id}/redeem", response_model=CompositeVoucherResponse)
def redeem(composite_id: str, user: User = Depends(get_current_user)):
    """
    Обналичивание: покупателю нужны реальные УЕ на балансе в реестре,
    а не просто владение векселем (см. voucher_service.redeem_composite_voucher).
    """
    return voucher_service.redeem_composite_voucher(user.id, composite_id)


@router.post("/{composite_id}/cancel", response_model=CompositeVoucherResponse)
def cancel(composite_id: str, user: User = Depends(get_current_user)):
    """
    Отмена векселя ДО обналичивания — снимает заморозку УЕ у продавца в
    реестре и возвращает объём обратно в остаток объявления (см.
    voucher_service.cancel_composite_voucher).
    """
    return voucher_service.cancel_composite_voucher(user.id, composite_id)
