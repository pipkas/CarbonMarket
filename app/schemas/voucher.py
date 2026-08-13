"""DTO для векселей: выпуск, просмотр, история владения по номеру."""
from datetime import datetime

from pydantic import BaseModel

from app.schemas.carbon_unit import CharacteristicsFilterDTO


class MintVoucherRequest(BaseModel):
    characteristics: CharacteristicsFilterDTO
    quantity: float


class VoucherListingInfo(BaseModel):
    """Краткая информация об активном объявлении на этот вексель, если оно есть."""
    listing_id: str
    fixed_price: float


class VoucherResponse(BaseModel):
    id: str
    number: str
    characteristics: CharacteristicsFilterDTO
    quantity: float
    status: str                              # "ACTIVE" | "REDEEMED"
    original_seller_id: str
    original_seller_display_name: str
    current_holder_id: str
    current_holder_display_name: str
    is_original_seller: bool                 # держатель = тот же, кто выпустил (никогда не перепродавался)
    price_paid: float | None                 # сколько текущий держатель заплатил за него (None, если сам выпустил)
    owners_count: int                        # сколько раз вексель переходил из рук в руки (без учёта минта)
    active_listing: VoucherListingInfo | None
    created_at: datetime
    redeemed_at: datetime | None = None

    class Config:
        from_attributes = True


class VoucherTransferDTO(BaseModel):
    type: str                                # "MINT" | "SALE" | "CANCELLATION"
    from_user_id: str | None
    from_display_name: str | None
    to_user_id: str
    to_display_name: str
    price: float | None
    transferred_at: datetime

    class Config:
        from_attributes = True


class VoucherHistoryResponse(BaseModel):
    """Полная карточка векселя по номеру: паспорт + вся цепочка держателей."""
    voucher: VoucherResponse
    chain: list[VoucherTransferDTO]
