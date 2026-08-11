"""
Вексель — центральная сущность рынка (см. ТЗ).

SimpleVoucher — "элементарный" вексель, результат одной сделки покупателя
с ОДНИМ продавцом по ОДНОМУ объявлению. При выпуске:
  - у продавца в реестре замораживается quantity УЕ данных характеристик
    (registry_client.freeze_units)
  - Listing.remaining_quantity уменьшается на quantity
  - вексель получает статус ISSUED (покупатель владеет правом требования,
    но реальные УЕ на его баланс в реестре ещё не зачислены)

CompositeVoucher — "сборный" вексель для удобства восприятия покупателя
(ТЗ: "формирует один вексель, в котором могут быть несколько векселей от
разных продавцов"). Это агрегатор над несколькими SimpleVoucher,
выпущенными в рамках одной покупки (сценарий 1 или 2).

Обналичивание (redeem): когда покупателю нужно ИМЕННО зачисление УЕ на
баланс (а не просто владение векселем), по каждому SimpleVoucher вызывается
registry_client.transfer_units(seller_account -> buyer_account), вексель
переходит в статус REDEEMED. До этого момента вексель можно (в будущем
расширении) перепродать другому покупателю — модель это допускает, т.к.
buyer_id — обычное изменяемое поле, но сама торговля векселями на вторичном
рынке в этом MVP не реализована (см. docs/architecture.md, "Точки расширения").
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from app.models.carbon_unit import CarbonUnitCharacteristics


class VoucherStatus(str, Enum):
    ISSUED = "ISSUED"        # выпущен, УЕ заморожены у продавца
    REDEEMED = "REDEEMED"    # обналичен, УЕ реально зачислены покупателю
    CANCELLED = "CANCELLED"


@dataclass
class SimpleVoucher:
    id: str
    listing_id: str
    seller_id: str
    buyer_id: str
    characteristics: CarbonUnitCharacteristics
    quantity: float
    price_per_unit: float          # зафиксированная цена сделки (эффективная)
    total_price: float
    status: VoucherStatus = VoucherStatus.ISSUED
    registry_freeze_ref: str | None = None   # ссылка на операцию заморозки в реестре
    created_at: datetime = None    # type: ignore
    redeemed_at: datetime | None = None

    @staticmethod
    def new(listing_id, seller_id, buyer_id, characteristics, quantity, price_per_unit, freeze_ref) -> "SimpleVoucher":
        return SimpleVoucher(
            id=str(uuid.uuid4()),
            listing_id=listing_id,
            seller_id=seller_id,
            buyer_id=buyer_id,
            characteristics=characteristics,
            quantity=quantity,
            price_per_unit=price_per_unit,
            total_price=round(quantity * price_per_unit, 2),
            registry_freeze_ref=freeze_ref,
            created_at=datetime.utcnow(),
        )


@dataclass
class CompositeVoucher:
    id: str
    buyer_id: str
    component_voucher_ids: list[str] = field(default_factory=list)
    total_quantity: float = 0.0
    total_price: float = 0.0
    scenario: str = ""   # "BUY_EXACT_QUANTITY" | "INVEST_AMOUNT" | "CHOOSE_SELLER"
    created_at: datetime = None  # type: ignore

    @staticmethod
    def new(buyer_id: str, component_voucher_ids: list[str], total_quantity: float, total_price: float, scenario: str) -> "CompositeVoucher":
        return CompositeVoucher(
            id=str(uuid.uuid4()),
            buyer_id=buyer_id,
            component_voucher_ids=component_voucher_ids,
            total_quantity=total_quantity,
            total_price=total_price,
            scenario=scenario,
            created_at=datetime.utcnow(),
        )
