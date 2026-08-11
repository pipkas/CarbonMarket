"""
Generic in-memory "репозиторий" — простая обёртка над dict, чтобы не
дублировать get/add/update/delete/list в каждом repo. При переходе на
Postgres каждый *_repo.py меняет реализацию этих же методов на SQL-запросы,
а сервисы (services/*) не замечают разницы — они работают только через
методы репозиториев, а не напрямую со словарями.

Потокобезопасность и персистентность сознательно не решаются — это MVP
"на заглушках", как и указано в задаче.
"""
from __future__ import annotations  # нужно, т.к. метод "list" ниже иначе затеняет builtin list[] в аннотациях

from typing import Generic, TypeVar, Callable, Optional

T = TypeVar("T")


class InMemoryStore(Generic[T]):
    def __init__(self, id_getter: Callable[[T], str]):
        self._data: dict[str, T] = {}
        self._id_getter = id_getter

    def add(self, item: T) -> T:
        self._data[self._id_getter(item)] = item
        return item

    def get(self, item_id: str) -> Optional[T]:
        return self._data.get(item_id)

    def update(self, item: T) -> T:
        self._data[self._id_getter(item)] = item
        return item

    def delete(self, item_id: str) -> None:
        self._data.pop(item_id, None)

    def list(self) -> list[T]:
        return list(self._data.values())

    def filter(self, predicate: Callable[[T], bool]) -> list[T]:
        return [item for item in self._data.values() if predicate(item)]
