"""
Заглушка аутентификации.

В реальной системе это будет полноценный JWT/OAuth2 (или интеграция с
Keycloak/ESIA для физ/юр лиц). Для MVP делаем простой in-memory токен-стор:
  email+password -> проверка хэша -> случайный opaque-токен -> в словаре
  token -> user_id, с TTL.

Важно: интерфейс (create_token/get_user_id_by_token/revoke_token) должен
остаться таким же при замене на настоящий JWT, чтобы dependencies.py и
роуты не пришлось переписывать.
"""
import hashlib
import secrets
import time
from typing import Optional

from app.config import settings

# token -> (user_id, expires_at_epoch)
_TOKENS: dict[str, tuple[str, float]] = {}


def hash_password(raw_password: str) -> str:
    # ЗАГЛУШКА: в проде — bcrypt/argon2 через passlib. Тут — просто sha256,
    # этого достаточно для демонстрации потоков аутентификации.
    return hashlib.sha256(raw_password.encode("utf-8")).hexdigest()


def verify_password(raw_password: str, password_hash: str) -> bool:
    return hash_password(raw_password) == password_hash


def create_token(user_id: str) -> str:
    token = secrets.token_urlsafe(32)
    _TOKENS[token] = (user_id, time.time() + settings.AUTH_TOKEN_TTL_SECONDS)
    return token


def get_user_id_by_token(token: str) -> Optional[str]:
    entry = _TOKENS.get(token)
    if not entry:
        return None
    user_id, expires_at = entry
    if time.time() > expires_at:
        _TOKENS.pop(token, None)
        return None
    return user_id


def revoke_token(token: str) -> None:
    _TOKENS.pop(token, None)
