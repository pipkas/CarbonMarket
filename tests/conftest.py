"""
Pytest fixtures — сбрасывают in-memory репозитории и реестр между тестами.
Все хранилища — синглтоны на уровне модуля, поэтому между тестами
накапливается «мусор». Фикстура autouse=True очищает их автоматически.
"""
import pytest

from app.repositories.listing_repo import listing_repo
from app.repositories.user_repo import user_repo
from app.repositories.voucher_repo import voucher_repo, voucher_transfer_repo
from app.services.registry_client import registry_client


def _clear_all():
    listing_repo._data.clear()
    voucher_repo._data.clear()
    voucher_transfer_repo._data.clear()
    user_repo._data.clear()
    registry_client._batches.clear()
    registry_client._freezes.clear()


@pytest.fixture(autouse=True)
def reset_stores():
    """Очищает все хранилища до теста и после него."""
    _clear_all()
    yield
    _clear_all()
