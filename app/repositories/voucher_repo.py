"""
Репозиторий векселей и журнала переходов владения.

next_voucher_number() — простой последовательный счётчик человекочитаемых
номеров векселей (формат "CM-000001"). В памяти процесса, как и всё
остальное в этом MVP; при переходе на Postgres — обычный SERIAL/SEQUENCE.
"""
from itertools import count

from app.models.voucher import Voucher, VoucherTransfer
from app.repositories.memory_store import InMemoryStore

voucher_repo = InMemoryStore[Voucher](id_getter=lambda v: v.id)
voucher_transfer_repo = InMemoryStore[VoucherTransfer](id_getter=lambda t: t.id)

_number_seq = count(1)


def next_voucher_number() -> str:
    return f"CM-{next(_number_seq):06d}"


def get_by_number(number: str) -> Voucher | None:
    found = voucher_repo.filter(lambda v: v.number == number)
    return found[0] if found else None


def get_held_by(user_id: str) -> list[Voucher]:
    """Векселя, которые пользователь держит ПРЯМО СЕЙЧАС (и активные, и уже обналиченные им)."""
    vouchers = voucher_repo.filter(lambda v: v.current_holder_id == user_id)
    return sorted(vouchers, key=lambda v: v.created_at, reverse=True)


def get_transfer_chain(voucher_id: str) -> list[VoucherTransfer]:
    """Полная история переходов векселя от выпуска до текущего момента, по порядку."""
    transfers = voucher_transfer_repo.filter(lambda t: t.voucher_id == voucher_id)
    return sorted(transfers, key=lambda t: t.transferred_at)


def get_latest_sale_transfer(voucher_id: str) -> VoucherTransfer | None:
    """Последняя запись типа SALE/CANCELLATION в цепочке — нужна, чтобы понять, можно ли откатить покупку."""
    chain = get_transfer_chain(voucher_id)
    for transfer in reversed(chain):
        if transfer.type.value in ("SALE", "CANCELLATION"):
            return transfer
    return None
