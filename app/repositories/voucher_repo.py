"""Репозитории простых и сборных векселей."""
from app.models.voucher import SimpleVoucher, CompositeVoucher
from app.repositories.memory_store import InMemoryStore

simple_voucher_repo = InMemoryStore[SimpleVoucher](id_getter=lambda v: v.id)
composite_voucher_repo = InMemoryStore[CompositeVoucher](id_getter=lambda v: v.id)


def get_composite_with_components(composite_id: str):
    composite = composite_voucher_repo.get(composite_id)
    if not composite:
        return None, []
    components = [simple_voucher_repo.get(vid) for vid in composite.component_voucher_ids]
    return composite, [c for c in components if c is not None]


def get_composites_for_buyer(buyer_id: str) -> list[CompositeVoucher]:
    return composite_voucher_repo.filter(lambda c: c.buyer_id == buyer_id)
