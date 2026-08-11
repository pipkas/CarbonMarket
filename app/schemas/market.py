"""DTO для операций покупки (сценарии 1, 2, 3)."""
from datetime import datetime

from pydantic import BaseModel

from app.schemas.carbon_unit import CharacteristicsFilterDTO


class BuyExactQuantityRequest(BaseModel):
    quantity_needed: int       # УЕ — только целое число
    characteristics: CharacteristicsFilterDTO | None = None


class InvestAmountRequest(BaseModel):
    budget_amount: float
    characteristics: CharacteristicsFilterDTO | None = None


class ReserveFromListingRequest(BaseModel):
    listing_id: str
    quantity: int              # УЕ — только целое число


class QuoteOfferDTO(BaseModel):
    """
    Один пункт превью — конкретное предложение, которое вошло бы в
    покупку. Возвращается topN (см. QuoteResponse) отсортированными от
    самых дешёвых, вместе с продавцом и характеристиками, чтобы
    покупатель мог детально ознакомиться ДО оформления сделки.
    """
    listing_id: str
    seller_id: str
    seller_display_name: str
    characteristics: CharacteristicsFilterDTO
    price_per_unit: float
    quantity: float
    subtotal: float
    min_deal_quantity: float | None
    max_deal_quantity: float | None


class QuoteResponse(BaseModel):
    """
    Превью раскладки покупки — считается тем же алгоритмом, что и реальная
    покупка, но ничего не резервирует и не требует авторизации.
    """
    offers: list[QuoteOfferDTO]        # топ (до 5) самых дешёвых предложений, вошедших в раскладку
    offers_beyond_shown: int           # сколько ещё предложений использовалось бы сверх показанных
    total_quantity: float
    total_price: float
    unmet_quantity: float | None = None   # только для подбора по количеству: сколько не удалось набрать
    leftover_budget: float | None = None  # только для подбора по бюджету: сколько денег осталось неизрасходовано


class CompositeVoucherResponse(BaseModel):
    id: str
    buyer_id: str
    component_voucher_ids: list[str]
    total_quantity: float
    total_price: float
    scenario: str
    created_at: datetime

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# Детальный ответ для истории — включает компоненты с их статусами
# ---------------------------------------------------------------------------

class SimpleVoucherDTO(BaseModel):
    id: str
    seller_id: str
    seller_display_name: str
    listing_id: str
    project_name: str | None
    quantity: float
    price_per_unit: float
    total_price: float
    status: str          # "ISSUED" | "REDEEMED" | "CANCELLED"
    created_at: datetime
    redeemed_at: datetime | None = None

    class Config:
        from_attributes = True


class CompositeVoucherDetailResponse(BaseModel):
    id: str
    buyer_id: str
    total_quantity: float
    total_price: float
    scenario: str
    created_at: datetime
    components: list[SimpleVoucherDTO]
    status: str          # "ISSUED" | "REDEEMED" | "PARTIAL"

    class Config:
        from_attributes = True

