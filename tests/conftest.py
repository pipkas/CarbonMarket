"""
Pytest fixtures — сбрасывают in-memory репозитории и реестр между тестами.
Все хранилища — синглтоны на уровне модуля, поэтому между тестами
накапливается «мусор». Фикстура autouse=True очищает их автоматически.
"""
import pytest

from app.repositories.listing_repo import listing_repo
from app.repositories.user_repo import user_repo
from app.repositories.voucher_repo import simple_voucher_repo, composite_voucher_repo
from app.services.registry_client import registry_client


@pytest.fixture(autouse=True)
def reset_stores():
    """Очищает все хранилища до теста и после него."""
    listing_repo._data.clear()
    simple_voucher_repo._data.clear()
    composite_voucher_repo._data.clear()
    user_repo._data.clear()
    registry_client._batches.clear()
    registry_client._freezes.clear()
    yield
    # После теста тоже чистим — на случай если тест упал
    listing_repo._data.clear()
    simple_voucher_repo._data.clear()
    composite_voucher_repo._data.clear()
    user_repo._data.clear()
    registry_client._batches.clear()
    registry_client._freezes.clear()
