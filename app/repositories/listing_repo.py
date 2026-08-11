"""Репозиторий объявлений + удобные выборки."""
from app.models.listing import Listing, ListingStatus
from app.repositories.memory_store import InMemoryStore

listing_repo = InMemoryStore[Listing](id_getter=lambda l: l.id)


def get_active() -> list[Listing]:
    return listing_repo.filter(lambda l: l.status == ListingStatus.ACTIVE and l.remaining_quantity > 0)


def get_active_by_seller(seller_id: str) -> list[Listing]:
    return listing_repo.filter(lambda l: l.seller_id == seller_id and l.status == ListingStatus.ACTIVE)


def get_by_seller(seller_id: str) -> list[Listing]:
    return listing_repo.filter(lambda l: l.seller_id == seller_id)
