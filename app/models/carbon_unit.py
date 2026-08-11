"""
Характеристики углеродных единиц (УЕ) — из ТЗ:
  Проект, Тип проекта, Год выпуска, Методология, Верификатор,
  Дата выпуска, Страна/регион, Статус.

CarbonUnitCharacteristics используется в двух местах:
  1) как "паспорт" партии УЕ на счету продавца в реестре (CarbonUnitBatch)
  2) как ФИЛЬТР в запросе покупателя ("нужны именно от проекта X") и в
     настройках объявления продавца ("что именно я готов продавать")
Для фильтра все поля Optional — None означает "любое значение подходит".
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from enum import Enum


class ProjectType(str, Enum):
    RENEWABLE_ENERGY = "RENEWABLE_ENERGY"     # ВИЭ
    FORESTRY = "FORESTRY"                     # лесоклиматические
    METHANE_CAPTURE = "METHANE_CAPTURE"
    ENERGY_EFFICIENCY = "ENERGY_EFFICIENCY"
    WASTE_MANAGEMENT = "WASTE_MANAGEMENT"
    OTHER = "OTHER"


class UnitStatus(str, Enum):
    ISSUED = "ISSUED"          # выпущена, доступна
    FROZEN = "FROZEN"          # заморожена под вексель
    RETIRED = "RETIRED"        # погашена (использована для зачёта выбросов)
    TRANSFERRED = "TRANSFERRED"


@dataclass
class CarbonUnitCharacteristics:
    project_name: str | None = None
    project_type: ProjectType | None = None
    vintage_year: int | None = None            # год выпуска
    methodology: str | None = None
    verifier: str | None = None
    issue_date: date | None = None
    country: str | None = None
    status: UnitStatus | None = None

    def matches(self, filter_: "CarbonUnitCharacteristics", strict: bool = False) -> bool:
        """
        Проверяет, удовлетворяет ли этот "паспорт" фильтру filter_.
        Не указанные (None) поля фильтра игнорируются (совпадение по
        умолчанию), если strict=False. При strict=True все непустые поля
        обеих сторон должны совпасть буквально — зарезервировано на
        будущее для более жёсткой верификации.
        """
        for field_name in self.__dataclass_fields__:
            wanted = getattr(filter_, field_name)
            if wanted is None:
                continue
            if getattr(self, field_name) != wanted:
                return False
        return True


@dataclass
class CarbonUnitBatch:
    """
    Партия УЕ на счету пользователя в (псевдо)реестре.
    quantity — общий объём партии, frozen_quantity — сколько из неё уже
    заморожено под выпущенные, но не обналиченные векселя.
    """
    id: str
    owner_registry_account_id: str
    characteristics: CarbonUnitCharacteristics
    quantity: float
    frozen_quantity: float = 0.0

    @property
    def available_quantity(self) -> float:
        return self.quantity - self.frozen_quantity

    @staticmethod
    def new(owner_registry_account_id: str, characteristics: CarbonUnitCharacteristics, quantity: float) -> "CarbonUnitBatch":
        return CarbonUnitBatch(
            id=str(uuid.uuid4()),
            owner_registry_account_id=owner_registry_account_id,
            characteristics=characteristics,
            quantity=quantity,
        )
