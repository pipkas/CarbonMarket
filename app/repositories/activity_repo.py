"""Репозиторий ленты активности ("История") — см. app/models/activity.py."""
from app.models.activity import ActivityEvent, ActivityType
from app.repositories.memory_store import InMemoryStore

activity_repo = InMemoryStore[ActivityEvent](id_getter=lambda e: e.id)


def log(
    user_id: str,
    type_: ActivityType,
    quantity: float | None = None,
    amount: float | None = None,
    project_name: str | None = None,
    counterparty_name: str | None = None,
    related_id: str | None = None,
) -> ActivityEvent:
    event = ActivityEvent.new(
        user_id=user_id,
        type_=type_,
        quantity=quantity,
        amount=amount,
        project_name=project_name,
        counterparty_name=counterparty_name,
        related_id=related_id,
    )
    return activity_repo.add(event)


def get_for_user(user_id: str) -> list[ActivityEvent]:
    events = activity_repo.filter(lambda e: e.user_id == user_id)
    return sorted(events, key=lambda e: e.created_at, reverse=True)
