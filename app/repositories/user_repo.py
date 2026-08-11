"""Репозиторий пользователей + поиск по email для логина."""
from app.models.user import User
from app.repositories.memory_store import InMemoryStore

user_repo = InMemoryStore[User](id_getter=lambda u: u.id)


def get_by_email(email: str) -> User | None:
    found = user_repo.filter(lambda u: u.email.lower() == email.lower())
    return found[0] if found else None
