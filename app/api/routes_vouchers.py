"""
Выпуск, просмотр и жизненный цикл векселей.

GET /vouchers/number/{number} — ПУБЛИЧНЫЙ (без авторизации) поиск по
номеру векселя: кто продавец (original_seller), кто текущий держатель,
и вся цепочка промежуточных владельцев — см. voucher_service.get_ownership_chain.
Это соответствует идее "реестра": номер векселя можно проверить как
любой другой публичный регистрационный номер.
"""
from fastapi import APIRouter, Depends, HTTPException

from app.core.dependencies import get_current_user
from app.models.carbon_unit import CarbonUnitCharacteristics
from app.models.user import User
from app.models.voucher import Voucher, VoucherTransfer
from app.repositories.listing_repo import get_active_listing_for_voucher
from app.repositories.user_repo import user_repo
from app.repositories.voucher_repo import get_by_number, get_held_by, voucher_repo
from app.schemas.carbon_unit import CharacteristicsFilterDTO
from app.schemas.voucher import (
    MintVoucherRequest,
    VoucherHistoryResponse,
    VoucherListingInfo,
    VoucherResponse,
    VoucherTransferDTO,
)
from app.services import seller_capacity_service, voucher_service

router = APIRouter(prefix="/vouchers", tags=["vouchers"])


def _display_name(user_id: str | None) -> str | None:
    if not user_id:
        return None
    user = user_repo.get(user_id)
    return user.display_name if user else "—"


def _to_response(voucher: Voucher) -> VoucherResponse:
    chain = voucher_service.get_ownership_chain(voucher.id)
    sale_transfers = [t for t in chain if t.type.value in ("SALE",)]
    latest_sale = sale_transfers[-1] if sale_transfers else None
    # "Сколько раз перепродавался" — считаем чистые смены держателя, без
    # учёта отменённых покупок (у каждой SALE есть максимум одна
    # компенсирующая её CANCELLATION где-то позже в цепочке).
    cancellations = len([t for t in chain if t.type.value == "CANCELLATION"])
    owners_count = max(0, len(sale_transfers) - cancellations)

    active_listing = get_active_listing_for_voucher(voucher.id)

    return VoucherResponse(
        id=voucher.id,
        number=voucher.number,
        characteristics=CharacteristicsFilterDTO(**voucher.characteristics.__dict__),
        quantity=voucher.quantity,
        status=voucher.status.value,
        original_seller_id=voucher.original_seller_id,
        original_seller_display_name=_display_name(voucher.original_seller_id) or "—",
        current_holder_id=voucher.current_holder_id,
        current_holder_display_name=_display_name(voucher.current_holder_id) or "—",
        is_original_seller=voucher.current_holder_id == voucher.original_seller_id,
        price_paid=latest_sale.price if (latest_sale and owners_count > 0) else None,
        owners_count=owners_count,
        active_listing=VoucherListingInfo(listing_id=active_listing.id, fixed_price=active_listing.fixed_price) if active_listing else None,
        created_at=voucher.created_at,
        redeemed_at=voucher.redeemed_at,
    )


def _transfer_to_dto(transfer: VoucherTransfer) -> VoucherTransferDTO:
    return VoucherTransferDTO(
        type=transfer.type.value,
        from_user_id=transfer.from_user_id,
        from_display_name=_display_name(transfer.from_user_id),
        to_user_id=transfer.to_user_id,
        to_display_name=_display_name(transfer.to_user_id) or "—",
        price=transfer.price,
        transferred_at=transfer.transferred_at,
    )


@router.get("/mint/available-capacity")
def available_to_mint(characteristics: CharacteristicsFilterDTO = Depends(), user: User = Depends(get_current_user)):
    """Сколько УЕ данных характеристик пользователь реально может заминтить в новый вексель прямо сейчас."""
    chars = CarbonUnitCharacteristics(**characteristics.model_dump())
    qty = seller_capacity_service.get_available_to_mint(user.registry_account_id, chars)
    return {"available_quantity": qty}


@router.post("/mint", response_model=VoucherResponse)
def mint(payload: MintVoucherRequest, user: User = Depends(get_current_user)):
    """Выпустить новый вексель из своих УЕ в реестре — до этого его нельзя выставить на продажу."""
    chars = CarbonUnitCharacteristics(**payload.characteristics.model_dump())
    voucher = voucher_service.mint_voucher(user, chars, payload.quantity)
    return _to_response(voucher)


@router.get("/mine", response_model=list[VoucherResponse])
def my_vouchers(user: User = Depends(get_current_user)):
    """Все векселя, которые пользователь держит прямо сейчас — выпущенные им самим и купленные."""
    return [_to_response(v) for v in get_held_by(user.id)]


@router.get("/number/{number}", response_model=VoucherHistoryResponse)
def lookup_by_number(number: str):
    """
    Публичный поиск по номеру векселя — доступен без авторизации, как
    проверка любого регистрационного номера. Показывает продавца-эмитента,
    всех промежуточных держателей и текущего владельца.
    """
    voucher = get_by_number(number)
    if not voucher:
        raise HTTPException(status_code=404, detail=f"Вексель с номером {number} не найден")
    chain = voucher_service.get_ownership_chain(voucher.id)
    return VoucherHistoryResponse(
        voucher=_to_response(voucher),
        chain=[_transfer_to_dto(t) for t in chain],
    )


@router.post("/{voucher_id}/redeem", response_model=VoucherResponse)
def redeem(voucher_id: str, user: User = Depends(get_current_user)):
    """Обналичивание: текущему держателю нужны реальные УЕ на балансе в реестре."""
    voucher = voucher_service.redeem_voucher(user.id, voucher_id)
    return _to_response(voucher)


@router.post("/{voucher_id}/cancel-purchase", response_model=VoucherResponse)
def cancel_purchase(voucher_id: str, user: User = Depends(get_current_user)):
    """Отменить свою последнюю покупку этого векселя — вернуть его прежнему держателю и получить деньги обратно."""
    voucher = voucher_service.cancel_purchase(user.id, voucher_id)
    return _to_response(voucher)
