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

from app.api import routes_auth, routes_listings, routes_market, routes_vouchers, routes_users
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
app.include_router(routes_users.router)


class NoCacheStaticFiles(StaticFiles):
    """
    Обычный StaticFiles + запрет кэширования браузером.

    Без сборки/хэширования имён файлов (static/app.js всегда называется
    одинаково) браузер после деплоя новой версии фронтенда может продолжать
    использовать старую закэшированную копию app.js/index.html — из-за этого
    в проде видно поведение "старого" кода (например, обращение к полям
    ответа API, которые уже переименованы на бэкенде), хотя на сервере
    лежит актуальный файл. Отключаем кэш для всей статики, чтобы после
    любого деплоя браузер гарантированно подтягивал свежие app.js/index.html.
    """

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response


# Статический фронтенд (static/index.html + style.css + app.js) — без
# сборки, обычный vanilla JS, обращается к API того же origin. Монтируется
# ПОСЛЕДНИМ и на корень "/", поэтому конкретные API-маршруты (/auth/...,
# /listings/..., /market/..., /vouchers/...), зарегистрированные выше,
# перехватываются раньше и не "затеняются" этим catch-all мемом.
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
app.mount("/", NoCacheStaticFiles(directory=STATIC_DIR, html=True), name="static")


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
    Демо-данные: 4 продавца, 1 покупатель, 20 объявлений с разными
    проектами, ценообразованием, ограничениями и характеристиками.
    """
    from app.models.carbon_unit import ProjectType, UnitStatus

    # ── Продавцы ──────────────────────────────────────────────────────────────
    seller1 = auth_service.register(
        email="seller@example.com", password="demo1234",
        user_type=UserType.LEGAL_ENTITY, display_name="ООО Зелёный Лес",
        inn="7701234567", ogrn="1027700123456",
    )
    seller2 = auth_service.register(
        email="seller2@example.com", password="demo1234",
        user_type=UserType.LEGAL_ENTITY, display_name="АО Экокарбон",
        inn="7702345678", ogrn="1027700234567",
    )
    seller3 = auth_service.register(
        email="seller3@example.com", password="demo1234",
        user_type=UserType.INDIVIDUAL, display_name="Петров Сергей",
    )
    seller4 = auth_service.register(
        email="seller4@example.com", password="demo1234",
        user_type=UserType.LEGAL_ENTITY, display_name="ПАО ЭнергоЧистота",
        inn="7703456789", ogrn="1027700345678",
    )

    auth_service.register(
        email="buyer@example.com", password="demo1234",
        user_type=UserType.INDIVIDUAL, display_name="Иван Иванов",
    )

    # ── Характеристики партий (добавляем в псевдо-реестр) ────────────────────
    def bal(seller, chars, qty):
        registry_module.registry_client.seed_demo_balance(
            seller.registry_account_id, chars, qty
        )

    def lst(seller, chars, qty, mode, base, ppu=None, flat=None, mn=None, mx=None):
        listing_service.create_listing(
            seller=seller, characteristics=chars,
            total_quantity=qty, pricing_mode=mode,
            base_reference_price=base, price_per_unit=ppu,
            flat_fee_per_deal=flat, min_deal_quantity=mn, max_deal_quantity=mx,
        )

    PU = PricingMode.PER_UNIT_MARKUP
    FF = PricingMode.FLAT_FEE_PER_DEAL

    # ── seller1: лесоклиматика, Россия ────────────────────────────────────────
    c1 = CarbonUnitCharacteristics(
        project_name="Реликтовый лес — сохранение", project_type=ProjectType.FORESTRY,
        vintage_year=2024, methodology="VM0007", verifier="TÜV Nord", country="RU",
        status=UnitStatus.ISSUED,
    )
    bal(seller1, c1, 20_000)
    lst(seller1, c1, 5_000, PU, 6.0, ppu=7.00, mn=500, mx=2_000)   # #1
    lst(seller1, c1, 3_000, FF, 6.0, flat=1_200.0, mn=200)          # #2

    c2 = CarbonUnitCharacteristics(
        project_name="Кедровая тайга — лесовосстановление", project_type=ProjectType.FORESTRY,
        vintage_year=2023, methodology="AR-ACM0003", verifier="Bureau Veritas",
        country="RU", status=UnitStatus.ISSUED,
    )
    bal(seller1, c2, 8_000)
    lst(seller1, c2, 4_000, PU, 6.0, ppu=6.50)                      # #3
    lst(seller1, c2, 2_000, PU, 6.0, ppu=6.20, mn=100, mx=500)      # #4

    # ── seller2: ВИЭ и энергоэффективность ───────────────────────────────────
    c3 = CarbonUnitCharacteristics(
        project_name="Ветропарк Поволжье", project_type=ProjectType.RENEWABLE_ENERGY,
        vintage_year=2024, methodology="AMS-I.D", verifier="SGS",
        country="RU", status=UnitStatus.ISSUED,
    )
    bal(seller2, c3, 15_000)
    lst(seller2, c3, 6_000, PU, 5.8, ppu=6.90)                      # #5
    lst(seller2, c3, 3_000, FF, 5.8, flat=800.0, mx=1_000)          # #6

    c4 = CarbonUnitCharacteristics(
        project_name="Солнечная станция — Крымский п-ов", project_type=ProjectType.RENEWABLE_ENERGY,
        vintage_year=2023, methodology="AMS-I.A", verifier="TÜV SÜD",
        country="RU", status=UnitStatus.ISSUED,
    )
    bal(seller2, c4, 10_000)
    lst(seller2, c4, 4_500, PU, 5.5, ppu=6.30, mn=300)              # #7
    lst(seller2, c4, 2_000, PU, 5.5, ppu=5.80)                      # #8  ← самые дешёвые

    c5 = CarbonUnitCharacteristics(
        project_name="Модернизация ТЭЦ — снижение выбросов", project_type=ProjectType.ENERGY_EFFICIENCY,
        vintage_year=2022, methodology="AMS-II.C", verifier="DNV GL",
        country="RU", status=UnitStatus.ISSUED,
    )
    bal(seller2, c5, 5_000)
    lst(seller2, c5, 2_500, PU, 5.0, ppu=5.90, mn=100, mx=800)      # #9

    # ── seller3: Казахстан и Беларусь — улавливание метана ───────────────────
    c6 = CarbonUnitCharacteristics(
        project_name="Дегазация угольных шахт — Темиртау", project_type=ProjectType.METHANE_CAPTURE,
        vintage_year=2024, methodology="VM0004", verifier="SCS Global",
        country="KZ", status=UnitStatus.ISSUED,
    )
    bal(seller3, c6, 7_000)
    lst(seller3, c6, 3_500, PU, 7.0, ppu=8.20, mn=200, mx=1_500)    # #10
    lst(seller3, c6, 2_000, FF, 7.0, flat=2_000.0, mn=500)          # #11

    c7 = CarbonUnitCharacteristics(
        project_name="Полигон ТБО — сбор свалочного газа", project_type=ProjectType.WASTE_MANAGEMENT,
        vintage_year=2023, methodology="ACM0001", verifier="Bureau Veritas",
        country="BY", status=UnitStatus.ISSUED,
    )
    bal(seller3, c7, 4_000)
    lst(seller3, c7, 2_000, PU, 6.5, ppu=7.50)                      # #12
    lst(seller3, c7, 1_000, FF, 6.5, flat=600.0, mn=100, mx=400)    # #13

    # ── seller4: международные проекты — Индия, Бразилия ─────────────────────
    c8 = CarbonUnitCharacteristics(
        project_name="Биогаз из навоза — Пенджаб", project_type=ProjectType.METHANE_CAPTURE,
        vintage_year=2024, methodology="AMS-III.R", verifier="TÜV Nord",
        country="IN", status=UnitStatus.ISSUED,
    )
    bal(seller4, c8, 12_000)
    lst(seller4, c8, 5_000, PU, 4.5, ppu=5.20, mn=300, mx=2_000)    # #14  ← очень дёшево
    lst(seller4, c8, 3_000, FF, 4.5, flat=500.0)                     # #15

    c9 = CarbonUnitCharacteristics(
        project_name="REDD+ Амазония — защита тропического леса",
        project_type=ProjectType.FORESTRY,
        vintage_year=2024, methodology="VM0015", verifier="SCS Global",
        country="BR", status=UnitStatus.ISSUED,
    )
    bal(seller4, c9, 20_000)
    lst(seller4, c9, 8_000, PU, 8.0, ppu=9.50, mn=1_000, mx=3_000)  # #16  ← премиум
    lst(seller4, c9, 4_000, PU, 8.0, ppu=8.80, mn=500)              # #17

    c10 = CarbonUnitCharacteristics(
        project_name="Геотермальная энергия — Исландия", project_type=ProjectType.RENEWABLE_ENERGY,
        vintage_year=2023, methodology="AMS-I.C", verifier="DNV GL",
        country="IS", status=UnitStatus.ISSUED,
    )
    bal(seller4, c10, 3_000)
    lst(seller4, c10, 1_500, PU, 9.0, ppu=10.50)                    # #18  ← самые дорогие

    c11 = CarbonUnitCharacteristics(
        project_name="Утилизация HFC-23 — химзавод Гуанчжоу",
        project_type=ProjectType.OTHER,
        vintage_year=2022, methodology="AM0001", verifier="TÜV SÜD",
        country="CN", status=UnitStatus.ISSUED,
    )
    bal(seller4, c11, 6_000)
    lst(seller4, c11, 2_500, PU, 6.0, ppu=6.80, mn=200, mx=1_000)   # #19
    lst(seller4, c11, 1_500, FF, 6.0, flat=900.0, mx=500)           # #20
