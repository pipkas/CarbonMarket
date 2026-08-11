"""
FastAPI-зависимости общего назначения: извлечение текущего пользователя
из заголовка Authorization: Bearer <token>.
"""
from fastapi import Header

from app.core import security
from app.core.exceptions import AuthError
from app.models.user import User
from app.repositories.user_repo import user_repo


def get_current_user(authorization: str = Header(default="")) -> User:
    if not authorization.startswith("Bearer "):
        raise AuthError("Отсутствует или некорректный заголовок Authorization")

    token = authorization.removeprefix("Bearer ").strip()
    user_id = security.get_user_id_by_token(token)
    if not user_id:
        raise AuthError("Токен недействителен или истёк")

    user = user_repo.get(user_id)
    if not user:
        raise AuthError("Пользователь не найден")

    return user
