"""
Объявление продавца (лот). Один продавец может создать несколько
объявлений с разной ценой/количеством/ограничениями — из ТЗ:
  "может один продавец несколько объявлений выставить с разными ценами
  и разным количеством".

Гибкие правила из ТЗ реализованы полями min_deal_quantity / max_deal_quantity:
  - "У меня есть 1000, но меньше 500 за одну сделку не продаю"
      -> total_quantity=1000, min_deal_quantity=500, max_deal_quantity=None
  - "Всего продаю 10000, но одной сделкой больше 2000 не отдаю"
      -> total_quantity=10000, max_deal_quantity=2000, min_deal_quantity=None

Ценообразование — два взаимоисключающих режима (см. config.settings):
  PER_UNIT_MARKUP     — продавец задаёт цену за единицу напрямую
                         (например 7 руб. вместо базовых 6)
  FLAT_FEE_PER_DEAL    — продавец задаёт фиксированную комиссию за сделку,
                         а не наценку на единицу
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from app.models.carbon_unit import CarbonUnitCharacteristics


class ListingStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    SOLD_OUT = "SOLD_OUT"
    CANCELLED = "CANCELLED"


class PricingMode(str, Enum):
    PER_UNIT_MARKUP = "PER_UNIT_MARKUP"
    FLAT_FEE_PER_DEAL = "FLAT_FEE_PER_DEAL"


@dataclass
class Listing:
    id: str
    seller_id: str
    characteristics: CarbonUnitCharacteristics  # что именно продаём

    total_quantity: float          # сколько всего выставлено на продажу
    remaining_quantity: float      # сколько ещё не продано (уменьшается по мере сделок)

    pricing_mode: PricingMode
    price_per_unit: float | None      # используется при PER_UNIT_MARKUP
    flat_fee_per_deal: float | None   # используется при FLAT_FEE_PER_DEAL
    base_reference_price: float       # справочная "рыночная" цена без наценки,
                                       # нужна чтобы считать flat_fee в пересчёте на ед.

    min_deal_quantity: float | None = None   # минимум за одну сделку
    max_deal_quantity: float | None = None   # максимум за одну сделку

    status: ListingStatus = ListingStatus.ACTIVE
    created_at: datetime = None  # type: ignore

    def effective_price_per_unit(self, deal_quantity: float) -> float:
        """
        Приводит любой режим ценообразования к цене за единицу для
        конкретного объёма сделки — используется matching_service для
        сортировки предложений "от дешёвых к дорогим".
        """
        if self.pricing_mode == PricingMode.PER_UNIT_MARKUP:
            return self.price_per_unit or self.base_reference_price
        # FLAT_FEE_PER_DEAL: комиссия размазывается по объёму сделки
        fee_per_unit = (self.flat_fee_per_deal or 0.0) / max(deal_quantity, 1e-9)
        return self.base_reference_price + fee_per_unit

    @staticmethod
    def new(
        seller_id: str,
        characteristics: CarbonUnitCharacteristics,
        total_quantity: float,
        pricing_mode: PricingMode,
        base_reference_price: float,
        price_per_unit: float | None = None,
        flat_fee_per_deal: float | None = None,
        min_deal_quantity: float | None = None,
        max_deal_quantity: float | None = None,
    ) -> "Listing":
        return Listing(
            id=str(uuid.uuid4()),
            seller_id=seller_id,
            characteristics=characteristics,
            total_quantity=total_quantity,
            remaining_quantity=total_quantity,
            pricing_mode=pricing_mode,
            price_per_unit=price_per_unit,
            flat_fee_per_deal=flat_fee_per_deal,
            base_reference_price=base_reference_price,
            min_deal_quantity=min_deal_quantity,
            max_deal_quantity=max_deal_quantity,
            created_at=datetime.utcnow(),
        )
