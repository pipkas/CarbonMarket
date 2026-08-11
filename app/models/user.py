"""
Пользователь рынка. Может быть физическим или юридическим лицом —
обе категории могут выступать и покупателем, и продавцом (п. ТЗ:
"купить и продать может как физ лицо так и юр лицо").

registry_account_id — идентификатор счёта в ВНЕШНЕМ реестре углеродных
единиц (сейчас — просто ключ в псевдо-реестре RegistryClient, потом —
реальный ID счёта в API реестра).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum


class UserType(str, Enum):
    INDIVIDUAL = "INDIVIDUAL"       # физ. лицо
    LEGAL_ENTITY = "LEGAL_ENTITY"   # юр. лицо


@dataclass
class User:
    id: str
    email: str
    password_hash: str
    user_type: UserType
    display_name: str                  # ФИО или название компании
    registry_account_id: str           # счёт в реестре УЕ

    # Поля, актуальные только для юр. лиц (для физлиц — None)
    inn: str | None = None
    ogrn: str | None = None

    @staticmethod
    def new(
        email: str,
        password_hash: str,
        user_type: UserType,
        display_name: str,
        inn: str | None = None,
        ogrn: str | None = None,
    ) -> "User":
        return User(
            id=str(uuid.uuid4()),
            email=email,
            password_hash=password_hash,
            user_type=user_type,
            display_name=display_name,
            registry_account_id=f"registry-acc-{uuid.uuid4().hex[:10]}",
            inn=inn,
            ogrn=ogrn,
        )
