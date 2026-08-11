"""
Заглушка клиента ВНЕШНЕГО реестра углеродных единиц.

Это единственное место в проекте, которое нужно будет заменить при
подключении настоящего API реестра (сейчас — httpx-клиент к их REST/SOAP,
позже). Интерфейс спроектирован так, как должен выглядеть и с реальным API:

    get_balance(account_id, characteristics_filter=None) -> list[CarbonUnitBatch]
    freeze_units(account_id, characteristics, quantity) -> freeze_ref: str
    unfreeze_units(freeze_ref) -> None
    transfer_units(from_account, to_account, characteristics, quantity, freeze_ref=None) -> transfer_ref: str

Реализация ниже держит партии УЕ (CarbonUnitBatch) в памяти процесса и
имитирует поведение реестра:
  - freeze_units переводит quantity из batch.available_quantity в
    batch.frozen_quantity (партия остаётся у продавца, но эта часть
    "заблокирована" под конкретный вексель и не может быть продана повторно)
  - transfer_units физически переносит quantity из партии продавца в новую
    (или существующую подходящую) партию покупателя и уменьшает
    frozen_quantity — это и есть момент "обналичивания" векселя
  - unfreeze_units откатывает заморозку (для отмены/просрочки сделки)

seed_demo_balance(...) используется в main.py, чтобы наполнить псевдо-реестр
демо-остатками при старте приложения.
"""
from __future__ import annotations

import uuid

from app.models.carbon_unit import CarbonUnitBatch, CarbonUnitCharacteristics


class RegistryClient:
    def __init__(self):
        self._batches: dict[str, CarbonUnitBatch] = {}
        # freeze_ref -> (batch_id, quantity)
        self._freezes: dict[str, tuple[str, float]] = {}

    # ---- запись остатков (используется при сидировании демо-данных) ----
    def seed_demo_balance(self, account_id: str, characteristics: CarbonUnitCharacteristics, quantity: float) -> CarbonUnitBatch:
        batch = CarbonUnitBatch.new(account_id, characteristics, quantity)
        self._batches[batch.id] = batch
        return batch

    # ---- чтение баланса ----
    def get_balance(self, account_id: str, characteristics_filter: CarbonUnitCharacteristics | None = None) -> list[CarbonUnitBatch]:
        result = [b for b in self._batches.values() if b.owner_registry_account_id == account_id]
        if characteristics_filter:
            result = [b for b in result if b.characteristics.matches(characteristics_filter)]
        return result

    # ---- заморозка под вексель (в момент выпуска SimpleVoucher) ----
    def freeze_units(self, account_id: str, characteristics: CarbonUnitCharacteristics, quantity: float) -> str:
        candidates = self.get_balance(account_id, characteristics)
        candidates = [b for b in candidates if b.available_quantity >= 1e-9]
        remaining = quantity
        touched: list[tuple[str, float]] = []
        for batch in sorted(candidates, key=lambda b: -b.available_quantity):
            if remaining <= 1e-9:
                break
            take = min(batch.available_quantity, remaining)
            batch.frozen_quantity += take
            remaining -= take
            touched.append((batch.id, take))
        if remaining > 1e-6:
            raise ValueError("Недостаточно доступных УЕ в реестре для заморозки")

        freeze_ref = str(uuid.uuid4())
        # Для простоты MVP считаем, что один freeze_ref = одна партия (после
        # merge партий на этапе seller_capacity_service обычно так и есть).
        # Если тронуто несколько партий — храним первую как "основную",
        # остальные списываем аналогично при unfreeze/transfer.
        self._freezes[freeze_ref] = (touched[0][0], quantity) if touched else ("", 0)
        return freeze_ref

    def unfreeze_units(self, freeze_ref: str) -> None:
        entry = self._freezes.pop(freeze_ref, None)
        if not entry:
            return
        batch_id, quantity = entry
        batch = self._batches.get(batch_id)
        if batch:
            batch.frozen_quantity = max(0.0, batch.frozen_quantity - quantity)

    # ---- обналичивание векселя: реальный перенос УЕ продавец -> покупатель ----
    def transfer_units(
        self,
        from_account: str,
        to_account: str,
        characteristics: CarbonUnitCharacteristics,
        quantity: float,
        freeze_ref: str | None = None,
    ) -> str:
        if freeze_ref:
            batch_id, frozen_qty = self._freezes.get(freeze_ref, (None, 0))
            batch = self._batches.get(batch_id) if batch_id else None
            if batch:
                batch.quantity -= quantity
                batch.frozen_quantity = max(0.0, batch.frozen_quantity - quantity)
            self._freezes.pop(freeze_ref, None)

        # Зачисляем покупателю новую партию с теми же характеристиками
        new_batch = CarbonUnitBatch.new(to_account, characteristics, quantity)
        self._batches[new_batch.id] = new_batch
        return new_batch.id


registry_client = RegistryClient()
