"""
Точка входа. Собирает роутеры, регистрирует обработчики доменных
исключений (core/exceptions.py -> JSON-ответ с нужным статусом) и
сидирует демо-данные при старте, чтобы сценарии можно было проверить
руками через /docs (Swagger UI) сразу после запуска.
"""
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api import routes_auth, routes_listings, routes_market, routes_vouchers
from app.config import settings
from app.core.exceptions import DomainError, InsufficientMarketSupplyError
from app.models.carbon_unit import CarbonUnitCharacteristics, ProjectType, UnitStatus
from app.models.user import UserType
from app.services import auth_service, listing_service, registry_client as registry_module
from app.models.listing import PricingMode

app = FastAPI(title=settings.APP_NAME)

app.include_router(routes_auth.router)
app.include_router(routes_listings.router)
app.include_router(routes_market.router)
app.include_router(routes_vouchers.router)

# Статический фронтенд (static/index.html + style.css + app.js) — без
# сборки, обычный vanilla JS, обращается к API того же origin. Монтируется
# ПОСЛЕДНИМ и на корень "/", поэтому конкретные API-маршруты (/auth/...,
# /listings/..., /market/..., /vouchers/...), зарегистрированные выше,
# перехватываются раньше и не "затеняются" этим catch-all мемом.
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")


@app.exception_handler(InsufficientMarketSupplyError)
def handle_insufficient_supply(request: Request, exc: InsufficientMarketSupplyError):
    return JSONResponse(
        status_code=exc.http_status,
        content={"error": "insufficient_market_supply", "detail": str(exc), "best_available": exc.best_available},
    )


@app.exception_handler(DomainError)
def handle_domain_error(request: Request, exc: DomainError):
    return JSONResponse(status_code=exc.http_status, content={"error": exc.__class__.__name__, "detail": str(exc)})


@app.on_event("startup")
def seed_demo_data():
    """
    Наполняет псевдо-реестр и создаёт демо-пользователей: одного продавца
    (юрлицо, с УЕ от лесоклиматического проекта) и одного покупателя
    (физлицо), плюс одно активное объявление — чтобы сразу можно было
    дернуть /market/buy-exact-quantity и /market/invest-amount из Swagger.
    """
    seller = auth_service.register(
        email="seller@example.com",
        password="demo1234",
        user_type=UserType.LEGAL_ENTITY,
        display_name="ООО Зелёный Лес",
        inn="7701234567",
        ogrn="1027700123456",
    )
    auth_service.register(
        email="buyer@example.com",
        password="demo1234",
        user_type=UserType.INDIVIDUAL,
        display_name="Иван Иванов",
    )

    characteristics = CarbonUnitCharacteristics(
        project_name="Реликтовый лес — сохранение",
        project_type=ProjectType.FORESTRY,
        vintage_year=2024,
        methodology="VM0007",
        verifier="TÜV Nord",
        country="RU",
        status=UnitStatus.ISSUED,
    )
    registry_module.registry_client.seed_demo_balance(seller.registry_account_id, characteristics, quantity=10_000)

    listing_service.create_listing(
        seller=seller,
        characteristics=characteristics,
        total_quantity=5_000,
        pricing_mode=PricingMode.PER_UNIT_MARKUP,
        base_reference_price=6.0,
        price_per_unit=7.0,
        flat_fee_per_deal=None,
        min_deal_quantity=500,
        max_deal_quantity=2_000,
    )
