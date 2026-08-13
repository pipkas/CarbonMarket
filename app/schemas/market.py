"""DTO для операций покупки (подбор по количеству, по бюджету, прямая покупка объявления)."""
from pydantic import BaseModel

from app.schemas.carbon_unit import CharacteristicsFilterDTO
from app.schemas.voucher import VoucherResponse


class BuyExactQuantityRequest(BaseModel):
    quantity_needed: float
    characteristics: CharacteristicsFilterDTO | None = None


class InvestAmountRequest(BaseModel):
    budget_amount: float
    characteristics: CharacteristicsFilterDTO | None = None


class BuyListingRequest(BaseModel):
    listing_id: str


class QuoteOfferDTO(BaseModel):
    """
    Один пункт превью — конкретный вексель (через чьё объявление), который
    вошёл бы в покупку. Возвращается отсортированным от самых дешёвых, до
    оформления сделки.
    """
    listing_id: str
    voucher_id: str
    voucher_number: str
    seller_id: str
    seller_display_name: str
    characteristics: CharacteristicsFilterDTO
    quantity: float
    price_per_unit: float
    fixed_price: float       # = цена, которую покупатель заплатит за этот вексель целиком


class QuoteResponse(BaseModel):
    offers: list[QuoteOfferDTO]
    offers_beyond_shown: int
    total_quantity: float
    total_price: float
    unmet_quantity: float | None = None
    leftover_budget: float | None = None


class PurchaseResultResponse(BaseModel):
    """Итог операции покупки — список уже пронумерованных приобретённых векселей."""
    vouchers: list[VoucherResponse]
    total_quantity: float
    total_price: float
    scenario: str
