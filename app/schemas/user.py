"""DTO для приватного профиля пользователя и его ленты активности."""
from datetime import datetime

from pydantic import BaseModel


class ProfileResponse(BaseModel):
    id: str
    email: str
    display_name: str
    user_type: str
    inn: str | None = None
    ogrn: str | None = None

    cash_balance: float                    # денежный баланс, ₽

    carbon_units_available: float          # УЕ на балансе в реестре, доступные (не заморожены)
    carbon_units_frozen: float             # УЕ, замороженные под выпущенные, но не обналиченные векселя
    carbon_units_total: float              # available + frozen


class ActivityEventResponse(BaseModel):
    id: str
    type: str
    created_at: datetime
    quantity: float | None = None
    amount: float | None = None
    project_name: str | None = None
    counterparty_name: str | None = None
    related_id: str | None = None

    class Config:
        from_attributes = True
