"""Регистрация и логин. Простая обёртка над user_repo + core.security."""
from app.core import security
from app.core.exceptions import AuthError, UserAlreadyExistsError
from app.models.user import User, UserType
from app.repositories.user_repo import user_repo, get_by_email


def register(email: str, password: str, user_type: UserType, display_name: str, inn: str | None = None, ogrn: str | None = None) -> User:
    if get_by_email(email):
        raise UserAlreadyExistsError(f"Пользователь с email {email} уже существует")
    user = User.new(
        email=email,
        password_hash=security.hash_password(password),
        user_type=user_type,
        display_name=display_name,
        inn=inn,
        ogrn=ogrn,
    )
    user_repo.add(user)
    return user


def login(email: str, password: str) -> tuple[User, str]:
    user = get_by_email(email)
    if not user or not security.verify_password(password, user.password_hash):
        raise AuthError("Неверный email или пароль")
    token = security.create_token(user.id)
    return user, token
