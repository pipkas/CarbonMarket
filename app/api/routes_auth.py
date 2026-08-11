"""POST /auth/register, POST /auth/login"""
from fastapi import APIRouter

from app.schemas.auth import RegisterRequest, LoginRequest, AuthResponse
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=AuthResponse)
def register(payload: RegisterRequest):
    user = auth_service.register(
        email=payload.email,
        password=payload.password,
        user_type=payload.user_type,
        display_name=payload.display_name,
        inn=payload.inn,
        ogrn=payload.ogrn,
    )
    _, token = auth_service.login(payload.email, payload.password)
    return AuthResponse(token=token, user_id=user.id, user_type=user.user_type, display_name=user.display_name)


@router.post("/login", response_model=AuthResponse)
def login(payload: LoginRequest):
    user, token = auth_service.login(payload.email, payload.password)
    return AuthResponse(token=token, user_id=user.id, user_type=user.user_type, display_name=user.display_name)
