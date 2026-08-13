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
from app.services import auth_service, listing_service, matching_service, registry_client as registry_module, voucher_service

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
    Демо-данные: 4 продавца, 2 покупателя, набор проектов с разными
    характеристиками. Для каждого проекта продавец сначала ВЫПУСКАЕТ
    (минтит) один или два векселя из своего остатка в реестре, затем
    выставляет их на продажу за фиксированную цену — так сразу видно,
    что купить можно только вексель целиком, а не углеродные единицы
    "по цене за штуку".

    Отдельно разыгрываем цепочку перепродажи: seller1 минтит вексель,
    продаёт buyer'у, buyer перепродаёт его дальше buyer2 по более высокой
    цене — чтобы сразу было что посмотреть в поиске по номеру векселя
    (виден и первоначальный продавец, и промежуточный держатель).
    """
    # ── Продавцы и покупатели ────────────────────────────────────────────────
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

    buyer = auth_service.register(
        email="buyer@example.com", password="demo1234",
        user_type=UserType.INDIVIDUAL, display_name="Иван Иванов",
    )
    buyer2 = auth_service.register(
        email="buyer2@example.com", password="demo1234",
        user_type=UserType.LEGAL_ENTITY, display_name="ООО Карбон Трейд",
        inn="7704567890", ogrn="1027700456789",
    )

    # ── Остатки в псевдо-реестре ──────────────────────────────────────────────
    def bal(seller, chars, qty):
        registry_module.registry_client.seed_demo_balance(seller.registry_account_id, chars, qty)

    # Минтит вексель из остатка продавца и сразу выставляет его на продажу
    # за фиксированную цену (никаких "цен за единицу" на витрине больше нет).
    def mint_and_list(seller, chars, qty, fixed_price):
        voucher = voucher_service.mint_voucher(seller, chars, qty)
        listing_service.create_listing(seller, voucher.id, fixed_price)
        return voucher

    # ── seller1: лесоклиматика, Россия ────────────────────────────────────────
    c1 = CarbonUnitCharacteristics(
        project_name="Реликтовый лес — сохранение", project_type=ProjectType.FORESTRY,
        vintage_year=2024, methodology="VM0007", verifier="TÜV Nord", country="RU",
        status=UnitStatus.ISSUED,
    )
    bal(seller1, c1, 20_000)
    mint_and_list(seller1, c1, 5_000, 35_000.0)     # 7.00 ₽/УЕ
    mint_and_list(seller1, c1, 3_000, 19_200.0)     # ~6.40 ₽/УЕ

    c2 = CarbonUnitCharacteristics(
        project_name="Кедровая тайга — лесовосстановление", project_type=ProjectType.FORESTRY,
        vintage_year=2023, methodology="AR-ACM0003", verifier="Bureau Veritas",
        country="RU", status=UnitStatus.ISSUED,
    )
    bal(seller1, c2, 8_000)
    mint_and_list(seller1, c2, 4_000, 26_000.0)     # 6.50 ₽/УЕ
    mint_and_list(seller1, c2, 2_000, 12_400.0)     # 6.20 ₽/УЕ

    # ── seller2: ВИЭ и энергоэффективность ───────────────────────────────────
    c3 = CarbonUnitCharacteristics(
        project_name="Ветропарк Поволжье", project_type=ProjectType.RENEWABLE_ENERGY,
        vintage_year=2024, methodology="AMS-I.D", verifier="SGS",
        country="RU", status=UnitStatus.ISSUED,
    )
    bal(seller2, c3, 15_000)
    mint_and_list(seller2, c3, 6_000, 41_400.0)     # 6.90 ₽/УЕ
    mint_and_list(seller2, c3, 1_000, 6_800.0)      # 6.80 ₽/УЕ

    c4 = CarbonUnitCharacteristics(
        project_name="Солнечная станция — Крымский п-ов", project_type=ProjectType.RENEWABLE_ENERGY,
        vintage_year=2023, methodology="AMS-I.A", verifier="TÜV SÜD",
        country="RU", status=UnitStatus.ISSUED,
    )
    bal(seller2, c4, 10_000)
    mint_and_list(seller2, c4, 4_500, 28_350.0)     # 6.30 ₽/УЕ
    mint_and_list(seller2, c4, 2_000, 11_600.0)     # 5.80 ₽/УЕ ← самые дешёвые

    c5 = CarbonUnitCharacteristics(
        project_name="Модернизация ТЭЦ — снижение выбросов", project_type=ProjectType.ENERGY_EFFICIENCY,
        vintage_year=2022, methodology="AMS-II.C", verifier="DNV GL",
        country="RU", status=UnitStatus.ISSUED,
    )
    bal(seller2, c5, 5_000)
    mint_and_list(seller2, c5, 2_500, 14_750.0)     # 5.90 ₽/УЕ

    # ── seller3: Казахстан и Беларусь — улавливание метана ───────────────────
    c6 = CarbonUnitCharacteristics(
        project_name="Дегазация угольных шахт — Темиртау", project_type=ProjectType.METHANE_CAPTURE,
        vintage_year=2024, methodology="VM0004", verifier="SCS Global",
        country="KZ", status=UnitStatus.ISSUED,
    )
    bal(seller3, c6, 7_000)
    mint_and_list(seller3, c6, 3_500, 28_700.0)     # 8.20 ₽/УЕ
    mint_and_list(seller3, c6, 1_500, 12_300.0)     # 8.20 ₽/УЕ

    c7 = CarbonUnitCharacteristics(
        project_name="Полигон ТБО — сбор свалочного газа", project_type=ProjectType.WASTE_MANAGEMENT,
        vintage_year=2023, methodology="ACM0001", verifier="Bureau Veritas",
        country="BY", status=UnitStatus.ISSUED,
    )
    bal(seller3, c7, 4_000)
    mint_and_list(seller3, c7, 2_000, 15_000.0)     # 7.50 ₽/УЕ
    mint_and_list(seller3, c7, 1_000, 6_500.0)      # 6.50 ₽/УЕ

    # ── seller4: международные проекты — Индия, Бразилия ─────────────────────
    c8 = CarbonUnitCharacteristics(
        project_name="Биогаз из навоза — Пенджаб", project_type=ProjectType.METHANE_CAPTURE,
        vintage_year=2024, methodology="AMS-III.R", verifier="TÜV Nord",
        country="IN", status=UnitStatus.ISSUED,
    )
    bal(seller4, c8, 12_000)
    mint_and_list(seller4, c8, 5_000, 26_000.0)     # 5.20 ₽/УЕ ← очень дёшево
    mint_and_list(seller4, c8, 3_000, 15_000.0)     # 5.00 ₽/УЕ

    c9 = CarbonUnitCharacteristics(
        project_name="REDD+ Амазония — защита тропического леса",
        project_type=ProjectType.FORESTRY,
        vintage_year=2024, methodology="VM0015", verifier="SCS Global",
        country="BR", status=UnitStatus.ISSUED,
    )
    bal(seller4, c9, 20_000)
    mint_and_list(seller4, c9, 8_000, 76_000.0)     # 9.50 ₽/УЕ ← премиум
    mint_and_list(seller4, c9, 4_000, 35_200.0)     # 8.80 ₽/УЕ

    c10 = CarbonUnitCharacteristics(
        project_name="Геотермальная энергия — Исландия", project_type=ProjectType.RENEWABLE_ENERGY,
        vintage_year=2023, methodology="AMS-I.C", verifier="DNV GL",
        country="IS", status=UnitStatus.ISSUED,
    )
    bal(seller4, c10, 3_000)
    mint_and_list(seller4, c10, 1_500, 15_750.0)    # 10.50 ₽/УЕ ← самые дорогие

    c11 = CarbonUnitCharacteristics(
        project_name="Утилизация HFC-23 — химзавод Гуанчжоу",
        project_type=ProjectType.OTHER,
        vintage_year=2022, methodology="AM0001", verifier="TÜV SÜD",
        country="CN", status=UnitStatus.ISSUED,
    )
    bal(seller4, c11, 6_000)
    mint_and_list(seller4, c11, 2_500, 17_000.0)    # 6.80 ₽/УЕ

    # ── Демонстрация цепочки перепродажи (для поиска по номеру векселя) ──────
    c12 = CarbonUnitCharacteristics(
        project_name="Малая ГЭС — река Катунь", project_type=ProjectType.RENEWABLE_ENERGY,
        vintage_year=2024, methodology="AMS-I.D", verifier="SGS",
        country="RU", status=UnitStatus.ISSUED,
    )
    bal(seller1, c12, 2_000)
    chain_voucher = mint_and_list(seller1, c12, 1_000, 6_800.0)   # seller1 выпускает и продаёт за 6 800 ₽

    from app.repositories.listing_repo import get_active_listing_for_voucher
    first_listing = get_active_listing_for_voucher(chain_voucher.id)
    matching_service.buy_listing_direct(buyer.id, first_listing)               # buyer покупает у seller1

    listing_service.create_listing(buyer, chain_voucher.id, 7_500.0)           # buyer перепродаёт дороже
    resale_listing = get_active_listing_for_voucher(chain_voucher.id)
    matching_service.buy_listing_direct(buyer2.id, resale_listing)             # buyer2 покупает у buyer

    # Итог: вексель chain_voucher.number сейчас у buyer2, история —
    # seller1 (выпуск) -> buyer (купил за 6 800 ₽) -> buyer2 (купил за 7 500 ₽).
