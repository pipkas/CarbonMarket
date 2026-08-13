"""
Вексель — центральная сущность рынка.

ВАЖНО (смена модели): вексель больше не выпускается автоматически "внутри"
сделки покупки. Теперь это самостоятельный пронумерованный инструмент:

  1) Продавец, у которого есть УЕ на счету в реестре, ВЫПУСКАЕТ
     (минтит) вексель на конкретный объём и характеристики —
     voucher_service.mint_voucher. В этот момент:
       - в реестре замораживается quantity УЕ (registry_client.freeze_units)
       - создаётся Voucher(status=ACTIVE) с уникальным номером (number)
       - продавец становится и original_seller_id, и current_holder_id
       - в журнал переходов (VoucherTransfer) добавляется запись типа MINT

  2) Только СУЩЕСТВУЮЩИЙ вексель можно выставить на продажу — Listing
     теперь ссылается на voucher_id и содержит единственную ФИКСИРОВАННУЮ
     цену за вексель целиком (fixed_price). Продавать "углеродные единицы
     по цене за единицу" больше нельзя — see app/models/listing.py.

  3) Когда вексель покупают, current_holder_id меняется на покупателя,
     в VoucherTransfer добавляется запись типа SALE (с ценой и ссылкой на
     Listing). Новый держатель может: обналичить (redeem) ИЛИ выставить
     тот же вексель на перепродажу за свою цену — вексель продолжает жить
     как один и тот же пронумерованный инструмент, просто со сменившимся
     держателем. Так образуется цепочка перепродаж.

  4) По номеру векселя (Voucher.number) можно поднять всю цепочку
     VoucherTransfer и увидеть: кто выпустил вексель изначально
     (original_seller_id), кто были промежуточные держатели, кто владеет
     им сейчас (current_holder_id) — см. voucher_repo.get_transfer_chain
     и GET /vouchers/number/{number}.

Обналичивание (redeem): когда ТЕКУЩЕМУ держателю нужны именно УЕ на
балансе в реестре (а не просто владение векселем), вызывается
registry_client.transfer_units(original_seller_account -> holder_account)
по сохранённому registry_freeze_ref — вексель переходит в REDEEMED и
больше не может ни перепродаваться, ни обналичиваться повторно.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from app.models.carbon_unit import CarbonUnitCharacteristics


class VoucherStatus(str, Enum):
    ACTIVE = "ACTIVE"        # существует, можно держать/перепродавать/обналичить
    REDEEMED = "REDEEMED"    # обналичен, УЕ реально зачислены текущему держателю


class TransferType(str, Enum):
    MINT = "MINT"                  # первичный выпуск продавцом из реестра — не покупка
    SALE = "SALE"                  # переход по купленному объявлению (fixed_price)
    CANCELLATION = "CANCELLATION"  # откат последней покупки — возврат предыдущему держателю


@dataclass
class Voucher:
    id: str
    number: str                        # человекочитаемый уникальный номер, напр. "CM-000042"
    original_seller_id: str            # кто выпустил вексель из реестра изначально
    current_holder_id: str             # кто владеет векселем сейчас
    characteristics: CarbonUnitCharacteristics
    quantity: float                    # объём УЕ — фиксирован на весь срок жизни векселя (неделим)
    status: VoucherStatus = VoucherStatus.ACTIVE
    registry_freeze_ref: str | None = None   # ссылка на заморозку в реестре (со времён минта)
    created_at: datetime = None        # type: ignore   # момент выпуска (минта)
    redeemed_at: datetime | None = None

    @staticmethod
    def new(original_seller_id: str, characteristics: CarbonUnitCharacteristics, quantity: float,
            number: str, freeze_ref: str | None) -> "Voucher":
        return Voucher(
            id=str(uuid.uuid4()),
            number=number,
            original_seller_id=original_seller_id,
            current_holder_id=original_seller_id,
            characteristics=characteristics,
            quantity=quantity,
            registry_freeze_ref=freeze_ref,
            created_at=datetime.utcnow(),
        )


@dataclass
class VoucherTransfer:
    """
    Одна запись неизменяемого журнала владения векселем. Записи никогда не
    удаляются и не редактируются (даже при отмене покупки — см.
    TransferType.CANCELLATION) — так по номеру векселя всегда можно
    восстановить полную историю: кто выпустил, у кого он был, кто владеет
    сейчас.
    """
    id: str
    voucher_id: str
    type: TransferType
    from_user_id: str | None    # None только для MINT (у векселя ещё не было предыдущего держателя)
    to_user_id: str
    price: float | None         # уплаченная сумма за ВЕСЬ вексель; None для MINT/CANCELLATION
    listing_id: str | None      # объявление, по которому прошла сделка; None для MINT/CANCELLATION
    transferred_at: datetime = None  # type: ignore

    @staticmethod
    def new(voucher_id: str, type_: TransferType, to_user_id: str,
            from_user_id: str | None = None, price: float | None = None,
            listing_id: str | None = None) -> "VoucherTransfer":
        return VoucherTransfer(
            id=str(uuid.uuid4()),
            voucher_id=voucher_id,
            type=type_,
            from_user_id=from_user_id,
            to_user_id=to_user_id,
            price=price,
            listing_id=listing_id,
            transferred_at=datetime.utcnow(),
        )
