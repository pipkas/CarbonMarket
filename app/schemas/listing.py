"""DTO для создания/просмотра объявлений."""
from datetime import datetime

from pydantic import BaseModel, model_validator

from app.models.listing import PricingMode
from app.schemas.carbon_unit import CharacteristicsFilterDTO


class CreateListingRequest(BaseModel):
    characteristics: CharacteristicsFilterDTO
    total_quantity: float
    pricing_mode: PricingMode
    base_reference_price: float
    price_per_unit: float | None = None
    flat_fee_per_deal: float | None = None
    min_deal_quantity: float | None = None
    max_deal_quantity: float | None = None

    @model_validator(mode="after")
    def check_pricing(self):
        if self.pricing_mode == PricingMode.PER_UNIT_MARKUP and self.price_per_unit is None:
            raise ValueError("price_per_unit обязателен для режима PER_UNIT_MARKUP")
        if self.pricing_mode == PricingMode.FLAT_FEE_PER_DEAL and self.flat_fee_per_deal is None:
            raise ValueError("flat_fee_per_deal обязателен для режима FLAT_FEE_PER_DEAL")
        return self


class ListingResponse(BaseModel):
    id: str
    seller_id: str
    seller_display_name: str
    characteristics: CharacteristicsFilterDTO
    total_quantity: float
    remaining_quantity: float
    pricing_mode: PricingMode
    price_per_unit: float | None
    flat_fee_per_deal: float | None
    base_reference_price: float
    min_deal_quantity: float | None
    max_deal_quantity: float | None
    status: str
    created_at: datetime

    class Config:
        from_attributes = True
