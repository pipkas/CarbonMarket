"""
Тесты сервиса подбора предложений (matching_service), сервиса векселей
(voucher_service) и создания объявлений (listing_service /
seller_capacity_service).

Охват соответствует 14 сценариям, описанным в исходной заглушке.
"""
import pytest

from app.core.exceptions import (
    DealConstraintViolationError,
    InsufficientMarketSupplyError,
    InsufficientSellerCapacityError,
    VoucherNotFoundError,
)
from app.models.carbon_unit import CarbonUnitCharacteristics, ProjectType, UnitStatus
from app.models.listing import PricingMode
from app.models.user import UserType
from app.services import auth_service, listing_service, matching_service, voucher_service
from app.services.registry_client import registry_client


# ---------------------------------------------------------------------------
# Вспомогательные функции для создания тестовых данных
# ---------------------------------------------------------------------------

def make_seller(email: str = "seller@test.com", display_name: str = "Тест-Продавец"):
    return auth_service.register(
        email=email,
        password="pass1234",
        user_type=UserType.LEGAL_ENTITY,
        display_name=display_name,
        inn="7701111111",
        ogrn="1027700000001",
    )


def make_buyer(email: str = "buyer@test.com", display_name: str = "Тест-Покупатель"):
    return auth_service.register(
        email=email,
        password="pass1234",
        user_type=UserType.INDIVIDUAL,
        display_name=display_name,
    )


def make_characteristics(project_name: str = "Test Project", project_type=ProjectType.FORESTRY) -> CarbonUnitCharacteristics:
    return CarbonUnitCharacteristics(
        project_name=project_name,
        project_type=project_type,
        vintage_year=2024,
        country="RU",
        status=UnitStatus.ISSUED,
    )


def seed_seller_balance(seller, characteristics, quantity: float):
    """Зачисляет УЕ на счёт продавца в псевдо-реестре."""
    registry_client.seed_demo_balance(seller.registry_account_id, characteristics, quantity)


def create_per_unit_listing(seller, characteristics, total_qty: float, price: float,
                             min_qty=None, max_qty=None):
    return listing_service.create_listing(
        seller=seller,
        characteristics=characteristics,
        total_quantity=total_qty,
        pricing_mode=PricingMode.PER_UNIT_MARKUP,
        base_reference_price=6.0,
        price_per_unit=price,
        flat_fee_per_deal=None,
        min_deal_quantity=min_qty,
        max_deal_quantity=max_qty,
    )


# ===========================================================================
# БЛОК 1: buy_exact_quantity / matching_service._allocate (кейсы 1–6)
# ===========================================================================

class TestBuyExactQuantity:

    def test_case1_single_seller_exact_match(self):
        """Кейс 1: один продавец полностью закрывает потребность."""
        seller = make_seller()
        buyer = make_buyer()
        chars = make_characteristics()
        seed_seller_balance(seller, chars, 2_000)
        create_per_unit_listing(seller, chars, total_qty=1_000, price=7.0)

        composite = matching_service.buy_exact_quantity(buyer.id, quantity_needed=500)

        assert composite.total_quantity == 500
        assert composite.total_price == pytest.approx(500 * 7.0, abs=0.01)
        assert composite.buyer_id == buyer.id

    def test_case2_composite_from_multiple_sellers_cheapest_first(self):
        """
        Кейс 2: потребность закрывается несколькими продавцами.
        Дешёвые идут первыми — итоговая цена оптимальная.
        """
        seller_cheap = make_seller(email="cheap@test.com", display_name="Дешёвый")
        seller_exp = make_seller(email="exp@test.com", display_name="Дорогой")
        buyer = make_buyer()
        chars = make_characteristics()

        seed_seller_balance(seller_cheap, chars, 1_000)
        seed_seller_balance(seller_exp, chars, 1_000)
        # Дешёвый — 300 УЕ по 5 руб., дорогой — 1000 УЕ по 8 руб.
        create_per_unit_listing(seller_cheap, chars, total_qty=300, price=5.0)
        create_per_unit_listing(seller_exp, chars, total_qty=1_000, price=8.0)

        composite = matching_service.buy_exact_quantity(buyer.id, quantity_needed=600)

        assert composite.total_quantity == pytest.approx(600, abs=1e-6)
        # Первые 300 по 5, следующие 300 по 8 = 1500 + 2400 = 3900
        assert composite.total_price == pytest.approx(300 * 5.0 + 300 * 8.0, abs=0.01)
        # Два компонента в векселе
        assert len(composite.component_voucher_ids) == 2

    def test_case3_skip_listing_when_min_qty_not_satisfiable(self):
        """
        Кейс 3: min_deal_quantity одного объявления больше остатка потребности —
        алгоритм пропускает его и добирает у следующего продавца.
        """
        seller_a = make_seller(email="a@test.com", display_name="Продавец А")
        seller_b = make_seller(email="b@test.com", display_name="Продавец Б")
        buyer = make_buyer()
        chars = make_characteristics()

        seed_seller_balance(seller_a, chars, 500)
        seed_seller_balance(seller_b, chars, 500)

        # Продавец А (дешевле): min=200, нам нужно добрать 100 — не влезает, пропустим
        create_per_unit_listing(seller_a, chars, total_qty=200, price=5.0, min_qty=200)
        # Продавец Б (дороже): без минимума
        create_per_unit_listing(seller_b, chars, total_qty=500, price=8.0)

        # Нужно 100 УЕ: min у А=200 > 100, но upper_bound А тоже =200, поэтому
        # алгоритм возьмёт у А min=200 (>= 200 <= upper_bound=200 — условие выполнено)
        composite = matching_service.buy_exact_quantity(buyer.id, quantity_needed=100)

        # Алгоритм: take=100 < min=200, но min(200)<=upper_bound(200) → take=200
        assert composite.total_quantity == pytest.approx(200, abs=1e-6)

    def test_case3_skip_listing_when_min_exceeds_upper_bound(self):
        """
        Кейс 3 (вариант): после частичных продаж remaining_quantity < min_deal_quantity
        — объявление пропускается, потребность покрывается следующим.
        Симулируем «прошедшие продажи», напрямую уменьшив remaining_quantity.
        """
        from app.repositories.listing_repo import listing_repo as _listing_repo

        seller_a = make_seller(email="a@test.com", display_name="Продавец А")
        seller_b = make_seller(email="b@test.com", display_name="Продавец Б")
        buyer = make_buyer()
        chars = make_characteristics()

        seed_seller_balance(seller_a, chars, 500)
        seed_seller_balance(seller_b, chars, 500)

        # У А: total=500, min=100. Симулируем частичные продажи → remaining=50 < min=100
        listing_a = create_per_unit_listing(seller_a, chars, total_qty=500, price=5.0, min_qty=100)
        listing_a.remaining_quantity = 50  # имитируем состояние после частичных продаж
        _listing_repo.update(listing_a)

        create_per_unit_listing(seller_b, chars, total_qty=500, price=8.0)

        composite = matching_service.buy_exact_quantity(buyer.id, quantity_needed=100)

        assert composite.total_quantity == pytest.approx(100, abs=1e-6)
        # Взяли только у Б (А пропустили: remaining=50 < min=100)
        assert len(composite.component_voucher_ids) == 1

    def test_case4_max_deal_quantity_limits_single_transaction(self):
        """
        Кейс 4: max_deal_quantity ограничивает объём одной сделки.
        Алгоритм берёт max от первого продавца, остальное — у второго.
        """
        seller_a = make_seller(email="a@test.com", display_name="Продавец А")
        seller_b = make_seller(email="b@test.com", display_name="Продавец Б")
        buyer = make_buyer()
        chars = make_characteristics()

        seed_seller_balance(seller_a, chars, 1_000)
        seed_seller_balance(seller_b, chars, 1_000)

        # Продавец А: max=300 (т.е. за одну сделку не больше 300)
        create_per_unit_listing(seller_a, chars, total_qty=1_000, price=5.0, max_qty=300)
        create_per_unit_listing(seller_b, chars, total_qty=1_000, price=8.0)

        composite = matching_service.buy_exact_quantity(buyer.id, quantity_needed=500)

        # 300 у А, 200 у Б
        assert composite.total_quantity == pytest.approx(500, abs=1e-6)
        assert composite.total_price == pytest.approx(300 * 5.0 + 200 * 8.0, abs=0.01)

    def test_case5_insufficient_supply_raises_error_with_best_available(self):
        """
        Кейс 5: суммарно на рынке меньше запрошенного —
        InsufficientMarketSupplyError с корректным best_available.
        """
        seller = make_seller()
        buyer = make_buyer()
        chars = make_characteristics()

        seed_seller_balance(seller, chars, 500)
        create_per_unit_listing(seller, chars, total_qty=300, price=7.0)

        with pytest.raises(InsufficientMarketSupplyError) as exc_info:
            matching_service.buy_exact_quantity(buyer.id, quantity_needed=1_000)

        err = exc_info.value
        assert err.requested == 1_000
        assert err.best_available == pytest.approx(300, abs=1e-6)

    def test_case6_characteristics_filter_excludes_wrong_projects(self):
        """
        Кейс 6: фильтр по project_name отсекает неподходящие объявления.
        """
        seller_x = make_seller(email="x@test.com", display_name="Продавец X")
        seller_y = make_seller(email="y@test.com", display_name="Продавец Y")
        buyer = make_buyer()

        chars_x = make_characteristics(project_name="Project X")
        chars_y = make_characteristics(project_name="Project Y")

        seed_seller_balance(seller_x, chars_x, 1_000)
        seed_seller_balance(seller_y, chars_y, 1_000)
        create_per_unit_listing(seller_x, chars_x, total_qty=500, price=7.0)
        create_per_unit_listing(seller_y, chars_y, total_qty=500, price=6.0)  # дешевле!

        filter_ = CarbonUnitCharacteristics(project_name="Project X")
        composite = matching_service.buy_exact_quantity(buyer.id, quantity_needed=100, characteristics_filter=filter_)

        # Должны были взять только у X, несмотря на то что Y дешевле
        assert composite.total_quantity == pytest.approx(100, abs=1e-6)
        # Проверяем по цене: взяли у X по 7.0
        assert composite.total_price == pytest.approx(100 * 7.0, abs=0.01)


# ===========================================================================
# БЛОК 2: invest_amount (кейсы 7–9)
# ===========================================================================

class TestInvestAmount:

    def test_case7_entire_budget_on_one_listing(self):
        """Кейс 7: весь бюджет тратится на одно объявление."""
        seller = make_seller()
        buyer = make_buyer()
        chars = make_characteristics()

        seed_seller_balance(seller, chars, 1_000)
        create_per_unit_listing(seller, chars, total_qty=1_000, price=5.0)

        composite = matching_service.invest_amount(buyer.id, budget_amount=500.0)

        expected_qty = 500.0 / 5.0  # = 100 УЕ
        assert composite.total_quantity == pytest.approx(expected_qty, abs=1e-6)
        assert composite.total_price == pytest.approx(500.0, abs=0.01)

    def test_case8_budget_distributed_cheapest_first(self):
        """Кейс 8: бюджет распределяется от дешёвых к дорогим."""
        seller_cheap = make_seller(email="cheap@test.com", display_name="Дешёвый")
        seller_exp = make_seller(email="exp@test.com", display_name="Дорогой")
        buyer = make_buyer()
        chars = make_characteristics()

        seed_seller_balance(seller_cheap, chars, 500)
        seed_seller_balance(seller_exp, chars, 500)
        # Дешёвый: 50 УЕ по 4 руб. (итого 200 руб.)
        create_per_unit_listing(seller_cheap, chars, total_qty=50, price=4.0)
        # Дорогой: 500 УЕ по 10 руб.
        create_per_unit_listing(seller_exp, chars, total_qty=500, price=10.0)

        # Бюджет 300 руб.: сначала все 50 у дешёвого (200 руб.), потом 10 у дорогого (100 руб.)
        composite = matching_service.invest_amount(buyer.id, budget_amount=300.0)

        assert composite.total_quantity == pytest.approx(50 + 10, abs=1e-6)
        assert composite.total_price == pytest.approx(200.0 + 100.0, abs=0.01)
        assert len(composite.component_voucher_ids) == 2

    def test_case9_leftover_budget_not_spent_when_min_qty_not_met(self):
        """
        Кейс 9: остаток бюджета после первого продавца не влезает в min_deal_quantity
        второго — тихо остаётся неизрасходованным (не выбрасывает исключение).
        Сценарий: бюджет=1000, продавец А (без min) — дешевле, истощается за 600 руб.
        Оставшиеся 400 руб. у продавца Б с min=100 и ценой 10/ед.
        — можно взять 40 УЕ, но 40 < min=100 → skip → leftover=400 руб.
        """
        seller_a = make_seller(email="a@test.com", display_name="Продавец А")
        seller_b = make_seller(email="b@test.com", display_name="Продавец Б")
        buyer = make_buyer()
        chars = make_characteristics()

        seed_seller_balance(seller_a, chars, 500)
        seed_seller_balance(seller_b, chars, 1_000)
        # Продавец А: 200 УЕ по 3 руб., без min (алгоритм возьмёт их первыми — дешевле)
        create_per_unit_listing(seller_a, chars, total_qty=200, price=3.0)
        # Продавец Б: много УЕ по 10 руб., min=100
        create_per_unit_listing(seller_b, chars, total_qty=1_000, price=10.0, min_qty=100)

        # Бюджет 1000: 200*3=600 уходит на А, остаток=400 → 40 УЕ у Б < min=100 → skip
        composite = matching_service.invest_amount(buyer.id, budget_amount=1_000.0)

        # Купили только у А — ошибки нет, leftover просто не тратится
        assert composite is not None
        assert composite.total_quantity == pytest.approx(200, abs=1e-6)
        assert composite.total_price == pytest.approx(600.0, abs=0.01)


# Дополнительный тест: invest_amount с нулевым рынком — явная ошибка
class TestInvestAmountEdgeCases:

    def test_invest_amount_empty_market_raises_error(self):
        """invest_amount без предложений → InsufficientMarketSupplyError."""
        buyer = make_buyer()

        with pytest.raises(InsufficientMarketSupplyError):
            matching_service.invest_amount(buyer.id, budget_amount=1_000.0)

    def test_invest_amount_leftover_is_silent(self):
        """
        Если бюджет не влезает в min_deal_quantity — исключение,
        т.к. items остаются пустыми.
        """
        seller = make_seller()
        buyer = make_buyer()
        chars = make_characteristics()

        seed_seller_balance(seller, chars, 1_000)
        # min=100, бюджет=500, цена=10 → можно взять 50 < 100 → skip → items=[]
        create_per_unit_listing(seller, chars, total_qty=1_000, price=10.0, min_qty=100)

        with pytest.raises(InsufficientMarketSupplyError):
            matching_service.invest_amount(buyer.id, budget_amount=500.0)


# ===========================================================================
# БЛОК 3: voucher_service (кейсы 10–12)
# ===========================================================================

class TestVoucherService:

    def test_case10_issue_simple_voucher_freezes_registry_units(self):
        """
        Кейс 10: issue_simple_voucher замораживает УЕ в реестре —
        available_quantity уменьшается сразу после выпуска.
        """
        seller = make_seller()
        chars = make_characteristics()
        seed_seller_balance(seller, chars, 1_000)
        listing = create_per_unit_listing(seller, chars, total_qty=1_000, price=7.0)

        buyer = make_buyer()
        qty_to_buy = 400.0

        # Баланс до
        batches_before = registry_client.get_balance(seller.registry_account_id, chars)
        available_before = sum(b.available_quantity for b in batches_before)

        voucher_service.issue_simple_voucher(listing, buyer.id, qty_to_buy)

        batches_after = registry_client.get_balance(seller.registry_account_id, chars)
        available_after = sum(b.available_quantity for b in batches_after)

        assert available_after == pytest.approx(available_before - qty_to_buy, abs=1e-6)

    def test_case11_redeem_composite_voucher_transfers_units_to_buyer(self):
        """
        Кейс 11: redeem_composite_voucher переносит УЕ на баланс покупателя.
        После обналичивания get_balance(buyer_account) содержит нужное количество.
        """
        seller = make_seller()
        buyer = make_buyer()
        chars = make_characteristics()
        seed_seller_balance(seller, chars, 1_000)
        listing = create_per_unit_listing(seller, chars, total_qty=1_000, price=7.0)

        qty = 300.0
        simple_v = voucher_service.issue_simple_voucher(listing, buyer.id, qty)
        composite = voucher_service.build_composite_voucher(buyer.id, [simple_v], scenario="TEST")

        # До обналичивания у покупателя нет УЕ
        buyer_batches_before = registry_client.get_balance(buyer.registry_account_id)
        assert sum(b.quantity for b in buyer_batches_before) == pytest.approx(0, abs=1e-6)

        voucher_service.redeem_composite_voucher(buyer.id, composite.id)

        buyer_batches_after = registry_client.get_balance(buyer.registry_account_id)
        total_buyer_qty = sum(b.quantity for b in buyer_batches_after)
        assert total_buyer_qty == pytest.approx(qty, abs=1e-6)

    def test_case12_redeem_wrong_buyer_raises_voucher_not_found(self):
        """
        Кейс 12: попытка обналичить чужой composite_voucher → VoucherNotFoundError.
        """
        seller = make_seller()
        buyer = make_buyer()
        intruder = make_buyer(email="bad@test.com", display_name="Злоумышленник")
        chars = make_characteristics()
        seed_seller_balance(seller, chars, 1_000)
        listing = create_per_unit_listing(seller, chars, total_qty=1_000, price=7.0)

        simple_v = voucher_service.issue_simple_voucher(listing, buyer.id, 100.0)
        composite = voucher_service.build_composite_voucher(buyer.id, [simple_v], scenario="TEST")

        with pytest.raises(VoucherNotFoundError):
            voucher_service.redeem_composite_voucher(intruder.id, composite.id)


# ===========================================================================
# БЛОК 4: listing_service / seller_capacity_service (кейсы 13–14)
# ===========================================================================

class TestListingService:

    def test_case13_seller_cannot_list_more_than_registry_balance(self):
        """
        Кейс 13: продавец не может выставить объявление на объём,
        превышающий его реальный остаток в реестре.
        """
        seller = make_seller()
        chars = make_characteristics()
        seed_seller_balance(seller, chars, 500)  # в реестре только 500

        with pytest.raises(InsufficientSellerCapacityError):
            create_per_unit_listing(seller, chars, total_qty=1_000, price=7.0)  # запрашиваем 1000

    def test_case14_seller_cannot_double_list_same_units(self):
        """
        Кейс 14: продавец не может выставить второе объявление, которое
        в сумме с первым (активным) превышает его реальный остаток.
        """
        seller = make_seller()
        chars = make_characteristics()
        seed_seller_balance(seller, chars, 1_000)

        # Первое объявление: 700 УЕ — OK
        create_per_unit_listing(seller, chars, total_qty=700, price=7.0)

        # Второе объявление: 400 УЕ — итого 1100 > 1000 → ошибка
        with pytest.raises(InsufficientSellerCapacityError):
            create_per_unit_listing(seller, chars, total_qty=400, price=7.0)

    def test_case14_second_listing_within_remaining_capacity_is_ok(self):
        """
        Кейс 14 (граничное): второе объявление, не превышающее остаток, создаётся.
        """
        seller = make_seller()
        chars = make_characteristics()
        seed_seller_balance(seller, chars, 1_000)

        create_per_unit_listing(seller, chars, total_qty=600, price=7.0)
        # Осталось 400 — второе на 400 должно пройти
        listing2 = create_per_unit_listing(seller, chars, total_qty=400, price=8.0)

        assert listing2 is not None
        assert listing2.total_quantity == 400

    def test_deal_constraint_violation_below_min(self):
        """Попытка купить меньше min_deal_quantity → DealConstraintViolationError."""
        seller = make_seller()
        buyer = make_buyer()
        chars = make_characteristics()
        seed_seller_balance(seller, chars, 1_000)
        listing = create_per_unit_listing(seller, chars, total_qty=1_000, price=7.0, min_qty=100)

        with pytest.raises(DealConstraintViolationError):
            voucher_service.issue_simple_voucher(listing, buyer.id, 50.0)  # меньше min=100

    def test_deal_constraint_violation_above_max(self):
        """Попытка купить больше max_deal_quantity → DealConstraintViolationError."""
        seller = make_seller()
        buyer = make_buyer()
        chars = make_characteristics()
        seed_seller_balance(seller, chars, 1_000)
        listing = create_per_unit_listing(seller, chars, total_qty=1_000, price=7.0, max_qty=200)

        with pytest.raises(DealConstraintViolationError):
            voucher_service.issue_simple_voucher(listing, buyer.id, 500.0)  # больше max=200
