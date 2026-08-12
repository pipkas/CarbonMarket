"""
Единая лента активности участника ("История") — в отличие от
/vouchers/mine (который показывает вексели только со стороны ПОКУПАТЕЛЯ),
сюда попадают события обеих ролей одного и того же пользователя:

  LISTING_CREATED   — вы выставили объявление на продажу (продавец)
  LISTING_CANCELLED — вы сняли объявление с продажи (продавец)
  SALE              — у вас купили УЕ по вашему объявлению (продавец)
  SALE_CANCELLED    — покупатель отменил вексель по вашему объявлению (продавец)
  PURCHASE          — вы купили УЕ на рынке (покупатель)
  VOUCHER_REDEEMED  — вы обналичили вексель, УЕ зачислены на баланс (покупатель)
  VOUCHER_CANCELLED — вы отменили свой вексель (покупатель)

Одно и то же событие сделки обычно порождает две записи в этой ленте —
по одной для каждой стороны (покупатель и продавец), т.к. лента у каждого
пользователя своя (user_id).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class ActivityType(str, Enum):
    LISTING_CREATED = "LISTING_CREATED"
    LISTING_CANCELLED = "LISTING_CANCELLED"
    SALE = "SALE"
    SALE_CANCELLED = "SALE_CANCELLED"
    PURCHASE = "PURCHASE"
    VOUCHER_REDEEMED = "VOUCHER_REDEEMED"
    VOUCHER_CANCELLED = "VOUCHER_CANCELLED"


@dataclass
class ActivityEvent:
    id: str
    user_id: str
    type: ActivityType
    created_at: datetime
    quantity: float | None = None          # УЕ, если применимо
    amount: float | None = None            # ₽, если применимо
    project_name: str | None = None
    counterparty_name: str | None = None   # имя контрагента (покупатель/продавец), если применимо
    related_id: str | None = None          # id объявления или векселя, к которому относится событие

    @staticmethod
    def new(
        user_id: str,
        type_: ActivityType,
        quantity: float | None = None,
        amount: float | None = None,
        project_name: str | None = None,
        counterparty_name: str | None = None,
        related_id: str | None = None,
    ) -> "ActivityEvent":
        return ActivityEvent(
            id=str(uuid.uuid4()),
            user_id=user_id,
            type=type_,
            created_at=datetime.utcnow(),
            quantity=quantity,
            amount=amount,
            project_name=project_name,
            counterparty_name=counterparty_name,
            related_id=related_id,
        )
