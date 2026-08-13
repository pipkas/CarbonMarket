"""DTO для создания/просмотра объявлений — теперь это предложение продать конкретный вексель."""
from datetime import datetime

from pydantic import BaseModel

from app.schemas.carbon_unit import CharacteristicsFilterDTO


class CreateListingRequest(BaseModel):
    voucher_id: str
    fixed_price: float       # ₽, единая цена за весь вексель


class ListingResponse(BaseModel):
    id: str
    voucher_id: str
    voucher_number: str
    seller_id: str
    seller_display_name: str
    characteristics: CharacteristicsFilterDTO   # унаследованы от векселя, только для отображения/фильтра
    quantity: float                             # объём УЕ, который представляет вексель
    fixed_price: float                          # ₽, единая цена за вексель целиком
    price_per_unit: float                       # = fixed_price / quantity, только для справки/сортировки
    status: str
    created_at: datetime

    class Config:
        from_attributes = True
