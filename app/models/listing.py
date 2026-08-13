"""
Объявление продавца (лот) — ПОСЛЕ смены модели.

Раньше Listing описывал предложение "сырых" углеродных единиц:
характеристики + количество + цена за единицу (или комиссия за сделку).

ТЕПЕРЬ Listing — это предложение продать ОДИН КОНКРЕТНЫЙ, УЖЕ
СУЩЕСТВУЮЩИЙ вексель (Voucher, см. app/models/voucher.py) целиком, за
ЕДИНУЮ фиксированную цену. Вексель неделим: либо покупают весь объём,
который он представляет, либо не покупают вовсе — поэтому у Listing
больше нет remaining_quantity, pricing_mode, min/max_deal_quantity и
цены "за штуку". Характеристики и количество УЕ не дублируются в
Listing — они принадлежат самому Voucher (listing.voucher_id).

Продавец в Listing — это ТЕКУЩИЙ держатель векселя на момент создания
объявления (может быть как тем, кто изначально выпустил вексель, так и
тем, кто перекупил его на вторичном рынке и теперь перепродаёт дальше).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class ListingStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SOLD = "SOLD"
    CANCELLED = "CANCELLED"


@dataclass
class Listing:
    id: str
    voucher_id: str          # какой вексель продаётся
    seller_id: str           # текущий держатель векселя на момент выставления
    fixed_price: float       # ₽, единая цена за вексель целиком (НЕ за единицу УЕ)
    status: ListingStatus = ListingStatus.ACTIVE
    created_at: datetime = None  # type: ignore

    @staticmethod
    def new(voucher_id: str, seller_id: str, fixed_price: float) -> "Listing":
        return Listing(
            id=str(uuid.uuid4()),
            voucher_id=voucher_id,
            seller_id=seller_id,
            fixed_price=fixed_price,
            created_at=datetime.utcnow(),
        )
