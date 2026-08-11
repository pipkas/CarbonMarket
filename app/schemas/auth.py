"""DTO для регистрации/логина."""
from pydantic import BaseModel, EmailStr

from app.models.user import UserType


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    user_type: UserType
    display_name: str
    inn: str | None = None
    ogrn: str | None = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class AuthResponse(BaseModel):
    token: str
    user_id: str
    user_type: UserType
    display_name: str
