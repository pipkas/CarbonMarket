"""
Приватный профиль текущего пользователя: денежный баланс, баланс УЕ в
реестре, единая лента активности (продажи/покупки/объявления по обеим
ролям — и как покупатель, и как продавец, см. app/models/activity.py).
"""
from fastapi import APIRouter, Depends

from app.core.dependencies import get_current_user
from app.models.user import User
from app.repositories import activity_repo
from app.schemas.user import ProfileResponse, ActivityEventResponse
from app.services.registry_client import registry_client

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=ProfileResponse)
def my_profile(user: User = Depends(get_current_user)):
    batches = registry_client.get_balance(user.registry_account_id)
    available = sum(b.available_quantity for b in batches)
    frozen = sum(b.frozen_quantity for b in batches)

    return ProfileResponse(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        user_type=user.user_type.value,
        inn=user.inn,
        ogrn=user.ogrn,
        cash_balance=user.cash_balance,
        carbon_units_available=available,
        carbon_units_frozen=frozen,
        carbon_units_total=available + frozen,
    )


@router.get("/me/activity", response_model=list[ActivityEventResponse])
def my_activity(user: User = Depends(get_current_user)):
    """
    Единая история: объявления (созданы/отменены), продажи по своим
    объявлениям, покупки, обналичивания и отмены векселей — отсортировано
    от новых к старым.
    """
    events = activity_repo.get_for_user(user.id)
    return [
        ActivityEventResponse(
            id=e.id,
            type=e.type.value,
            created_at=e.created_at,
            quantity=e.quantity,
            amount=e.amount,
            project_name=e.project_name,
            counterparty_name=e.counterparty_name,
            related_id=e.related_id,
        )
        for e in events
    ]
