"""
Тесты сервисов рынка ПОСЛЕ смены модели: продавец выставляет на продажу
только уже выпущенные (заминченные) векселя по фиксированной цене — не
углеродные единицы по цене за штуку. Покрывает: voucher_service
(минт/покупка/обналичивание/отмена покупки), listing_service (создание/
отмена объявлений на конкретный вексель), matching_service (подбор по
количеству/бюджету поверх неделимых предложений) и seller_capacity_service.
"""
import pytest

from app.core.exceptions import (
    InsufficientFundsError,
    InsufficientMarketSupplyError,
    InsufficientSellerCapacityError,
    TransferNotCancellableError,
    VoucherAlreadyListedError,
    VoucherAlreadyRedeemedError,
    VoucherNotFoundError,
    VoucherNotOwnedError,
)
from app.models.carbon_unit import CarbonUnitCharacteristics, ProjectType, UnitStatus
from app.models.user import UserType
from app.models.voucher import TransferType, VoucherStatus
from app.services import auth_service, listing_service, matching_service, seller_capacity_service, voucher_service
from app.repositories.voucher_repo import get_by_number
from app.services.registry_client import registry_client


# ---------------------------------------------------------------------------
# Вспомогательные функции для создания тестовых данных
# ---------------------------------------------------------------------------

def make_user(email: str, display_name: str, legal: bool = True):
    return auth_service.register(
        email=email, password="pass1234",
        user_type=UserType.LEGAL_ENTITY if legal else UserType.INDIVIDUAL,
        display_name=display_name,
        inn="7701111111" if legal else None,
        ogrn="1027700000001" if legal else None,
    )


def make_characteristics(project_name: str = "Test Project", project_type=ProjectType.FORESTRY) -> CarbonUnitCharacteristics:
    return CarbonUnitCharacteristics(
        project_name=project_name, project_type=project_type,
        vintage_year=2024, country="RU", status=UnitStatus.ISSUED,
    )


def seed_balance(user, characteristics, quantity: float):
    registry_client.seed_demo_balance(user.registry_account_id, characteristics, quantity)


def mint_and_list(seller, characteristics, quantity, price):
    voucher = voucher_service.mint_voucher(seller, characteristics, quantity)
    listing = listing_service.create_listing(seller, voucher.id, price)
    return voucher, listing


# ===========================================================================
# МИНТ: выпуск векселя и доступный остаток
# ===========================================================================

class TestMintVoucher:
    def test_mint_freezes_registry_and_creates_numbered_voucher(self):
        seller = make_user("seller@test.com", "Продавец")
        chars = make_characteristics()
        seed_balance(seller, chars, 1000)

        voucher = voucher_service.mint_voucher(seller, chars, 400)

        assert voucher.number.startswith("CM-")
        assert voucher.quantity == 400
        assert voucher.original_seller_id == seller.id
        assert voucher.current_holder_id == seller.id
        assert voucher.status == VoucherStatus.ACTIVE

        remaining = seller_capacity_service.get_available_to_mint(seller.registry_account_id, chars)
        assert remaining == pytest.approx(600)

    def test_mint_more_than_available_raises(self):
        seller = make_user("seller@test.com", "Продавец")
        chars = make_characteristics()
        seed_balance(seller, chars, 100)

        with pytest.raises(InsufficientSellerCapacityError):
            voucher_service.mint_voucher(seller, chars, 500)

    def test_each_mint_gets_a_unique_sequential_number(self):
        seller = make_user("seller@test.com", "Продавец")
        chars = make_characteristics()
        seed_balance(seller, chars, 1000)

        v1 = voucher_service.mint_voucher(seller, chars, 100)
        v2 = voucher_service.mint_voucher(seller, chars, 100)
        assert v1.number != v2.number


# ===========================================================================
# ЛИСТИНГ: можно выставить только вексель, которым владеешь
# ===========================================================================

class TestListing:
    def test_only_current_holder_can_list(self):
        seller = make_user("seller@test.com", "Продавец")
        stranger = make_user("stranger@test.com", "Чужой")
        chars = make_characteristics()
        seed_balance(seller, chars, 1000)
        voucher = voucher_service.mint_voucher(seller, chars, 100)

        with pytest.raises(VoucherNotOwnedError):
            listing_service.create_listing(stranger, voucher.id, 900.0)

    def test_cannot_list_same_voucher_twice(self):
        seller = make_user("seller@test.com", "Продавец")
        chars = make_characteristics()
        seed_balance(seller, chars, 1000)
        voucher, _ = mint_and_list(seller, chars, 100, 900.0)

        with pytest.raises(VoucherAlreadyListedError):
            listing_service.create_listing(seller, voucher.id, 950.0)

    def test_cancelling_listing_allows_relisting(self):
        seller = make_user("seller@test.com", "Продавец")
        chars = make_characteristics()
        seed_balance(seller, chars, 1000)
        voucher, listing = mint_and_list(seller, chars, 100, 900.0)

        listing_service.cancel_listing(seller, listing.id)
        new_listing = listing_service.create_listing(seller, voucher.id, 950.0)
        assert new_listing.fixed_price == 950.0


# ===========================================================================
# ПОКУПКА: вексель неделим, продаётся целиком за фиксированную цену
# ===========================================================================

class TestBuyListing:
    def test_buy_transfers_ownership_and_money(self):
        seller = make_user("seller@test.com", "Продавец")
        buyer = make_user("buyer@test.com", "Покупатель", legal=False)
        chars = make_characteristics()
        seed_balance(seller, chars, 1000)
        voucher, listing = mint_and_list(seller, chars, 100, 900.0)

        seller_cash_before = seller.cash_balance
        buyer_cash_before = buyer.cash_balance

        bought = matching_service.buy_listing_direct(buyer.id, listing)

        assert bought.current_holder_id == buyer.id
        assert buyer.cash_balance == pytest.approx(buyer_cash_before - 900.0)
        assert seller.cash_balance == pytest.approx(seller_cash_before + 900.0)

    def test_cannot_buy_own_listing(self):
        seller = make_user("seller@test.com", "Продавец")
        chars = make_characteristics()
        seed_balance(seller, chars, 1000)
        _, listing = mint_and_list(seller, chars, 100, 900.0)

        with pytest.raises(VoucherNotOwnedError):
            matching_service.buy_listing_direct(seller.id, listing)

    def test_insufficient_funds_raises(self):
        seller = make_user("seller@test.com", "Продавец")
        buyer = make_user("buyer@test.com", "Покупатель", legal=False)
        buyer.cash_balance = 10.0
        chars = make_characteristics()
        seed_balance(seller, chars, 1000)
        _, listing = mint_and_list(seller, chars, 100, 900.0)

        with pytest.raises(InsufficientFundsError):
            matching_service.buy_listing_direct(buyer.id, listing)

    def test_resold_voucher_cannot_be_bought_again_from_stale_listing(self):
        seller = make_user("seller@test.com", "Продавец")
        buyer1 = make_user("buyer1@test.com", "Покупатель 1", legal=False)
        buyer2 = make_user("buyer2@test.com", "Покупатель 2", legal=False)
        chars = make_characteristics()
        seed_balance(seller, chars, 1000)
        voucher, listing = mint_and_list(seller, chars, 100, 900.0)

        matching_service.buy_listing_direct(buyer1.id, listing)

        with pytest.raises(VoucherNotFoundError):
            matching_service.buy_listing_direct(buyer2.id, listing)


# ===========================================================================
# ЦЕПОЧКА ПЕРЕПРОДАЖ: главное новое требование — история по номеру векселя
# ===========================================================================

class TestOwnershipChain:
    def test_chain_shows_original_seller_and_all_intermediate_holders(self):
        seller = make_user("seller@test.com", "Первый продавец")
        buyer1 = make_user("buyer1@test.com", "Держатель 1", legal=False)
        buyer2 = make_user("buyer2@test.com", "Держатель 2", legal=False)
        chars = make_characteristics()
        seed_balance(seller, chars, 1000)

        voucher, listing1 = mint_and_list(seller, chars, 100, 900.0)
        matching_service.buy_listing_direct(buyer1.id, listing1)

        listing2 = listing_service.create_listing(buyer1, voucher.id, 1000.0)
        matching_service.buy_listing_direct(buyer2.id, listing2)

        chain = voucher_service.get_ownership_chain(voucher.id)
        assert [t.type for t in chain] == [TransferType.MINT, TransferType.SALE, TransferType.SALE]
        assert chain[0].to_user_id == seller.id
        assert chain[1].from_user_id == seller.id and chain[1].to_user_id == buyer1.id and chain[1].price == 900.0
        assert chain[2].from_user_id == buyer1.id and chain[2].to_user_id == buyer2.id and chain[2].price == 1000.0

        refreshed = get_by_number(voucher.number)
        assert refreshed.current_holder_id == buyer2.id
        assert refreshed.original_seller_id == seller.id

    def test_lookup_by_number_finds_the_right_voucher(self):
        seller = make_user("seller@test.com", "Продавец")
        chars = make_characteristics()
        seed_balance(seller, chars, 1000)
        voucher = voucher_service.mint_voucher(seller, chars, 100)

        found = get_by_number(voucher.number)
        assert found is not None
        assert found.id == voucher.id

        assert get_by_number("CM-999999") is None


# ===========================================================================
# ОБНАЛИЧИВАНИЕ И ОТМЕНА ПОКУПКИ
# ===========================================================================

class TestRedeemAndCancel:
    def test_redeem_marks_voucher_and_transfers_registry_units(self):
        seller = make_user("seller@test.com", "Продавец")
        buyer = make_user("buyer@test.com", "Покупатель", legal=False)
        chars = make_characteristics()
        seed_balance(seller, chars, 1000)
        voucher, listing = mint_and_list(seller, chars, 100, 900.0)
        matching_service.buy_listing_direct(buyer.id, listing)

        redeemed = voucher_service.redeem_voucher(buyer.id, voucher.id)
        assert redeemed.status == VoucherStatus.REDEEMED
        assert redeemed.redeemed_at is not None

        buyer_balance = registry_client.get_balance(buyer.registry_account_id, chars)
        assert sum(b.quantity for b in buyer_balance) == pytest.approx(100)

    def test_cannot_redeem_twice(self):
        seller = make_user("seller@test.com", "Продавец")
        buyer = make_user("buyer@test.com", "Покупатель", legal=False)
        chars = make_characteristics()
        seed_balance(seller, chars, 1000)
        voucher, listing = mint_and_list(seller, chars, 100, 900.0)
        matching_service.buy_listing_direct(buyer.id, listing)
        voucher_service.redeem_voucher(buyer.id, voucher.id)

        with pytest.raises(VoucherAlreadyRedeemedError):
            voucher_service.redeem_voucher(buyer.id, voucher.id)

    def test_cancel_purchase_reverts_ownership_money_and_reopens_listing(self):
        seller = make_user("seller@test.com", "Продавец")
        buyer = make_user("buyer@test.com", "Покупатель", legal=False)
        chars = make_characteristics()
        seed_balance(seller, chars, 1000)
        voucher, listing = mint_and_list(seller, chars, 100, 900.0)

        seller_cash_before = seller.cash_balance
        buyer_cash_before = buyer.cash_balance
        matching_service.buy_listing_direct(buyer.id, listing)

        voucher_service.cancel_purchase(buyer.id, voucher.id)

        refreshed = get_by_number(voucher.number)
        assert refreshed.current_holder_id == seller.id
        assert seller.cash_balance == pytest.approx(seller_cash_before)
        assert buyer.cash_balance == pytest.approx(buyer_cash_before)

        reopened = listing_service.browse_listings()
        assert any(l.id == listing.id and l.status == "ACTIVE" for l in reopened)

    def test_cannot_cancel_if_you_no_longer_hold_the_voucher(self):
        seller = make_user("seller@test.com", "Продавец")
        buyer1 = make_user("buyer1@test.com", "Держатель 1", legal=False)
        buyer2 = make_user("buyer2@test.com", "Держатель 2", legal=False)
        chars = make_characteristics()
        seed_balance(seller, chars, 1000)
        voucher, listing1 = mint_and_list(seller, chars, 100, 900.0)
        matching_service.buy_listing_direct(buyer1.id, listing1)

        listing2 = listing_service.create_listing(buyer1, voucher.id, 1000.0)
        matching_service.buy_listing_direct(buyer2.id, listing2)

        # buyer1 больше не держит вексель (перепродал buyer2) — отменить свою
        # старую покупку он больше не может, это прерогатива ТЕКУЩЕГО держателя.
        with pytest.raises(VoucherNotFoundError):
            voucher_service.cancel_purchase(buyer1.id, voucher.id)

        # а вот buyer2 (текущий держатель) может откатить именно свою, последнюю покупку
        reverted = voucher_service.cancel_purchase(buyer2.id, voucher.id)
        assert reverted.current_holder_id == buyer1.id

    def test_cannot_cancel_after_redeem(self):
        seller = make_user("seller@test.com", "Продавец")
        buyer = make_user("buyer@test.com", "Покупатель", legal=False)
        chars = make_characteristics()
        seed_balance(seller, chars, 1000)
        voucher, listing = mint_and_list(seller, chars, 100, 900.0)
        matching_service.buy_listing_direct(buyer.id, listing)
        voucher_service.redeem_voucher(buyer.id, voucher.id)

        with pytest.raises(TransferNotCancellableError):
            voucher_service.cancel_purchase(buyer.id, voucher.id)


# ===========================================================================
# ПОДБОР: buy_exact_quantity / invest_amount поверх неделимых предложений
# ===========================================================================

class TestMatching:
    def test_buy_exact_quantity_picks_cheapest_vouchers_first(self):
        seller = make_user("seller@test.com", "Продавец")
        buyer = make_user("buyer@test.com", "Покупатель", legal=False)
        chars = make_characteristics()
        seed_balance(seller, chars, 10_000)

        mint_and_list(seller, chars, 500, 4_000.0)   # 8.0 ₽/ед — дороже
        mint_and_list(seller, chars, 500, 3_000.0)   # 6.0 ₽/ед — дешевле

        result = matching_service.buy_exact_quantity(buyer.id, 500, chars)
        assert result.total_quantity == 500
        assert result.total_price == pytest.approx(3_000.0)   # взяли более дешёвый вексель

    def test_buy_exact_quantity_insufficient_supply_raises(self):
        seller = make_user("seller@test.com", "Продавец")
        buyer = make_user("buyer@test.com", "Покупатель", legal=False)
        chars = make_characteristics()
        seed_balance(seller, chars, 100)
        mint_and_list(seller, chars, 100, 900.0)

        with pytest.raises(InsufficientMarketSupplyError):
            matching_service.buy_exact_quantity(buyer.id, 10_000, chars)

    def test_invest_amount_respects_budget(self):
        seller = make_user("seller@test.com", "Продавец")
        buyer = make_user("buyer@test.com", "Покупатель", legal=False)
        chars = make_characteristics()
        seed_balance(seller, chars, 10_000)

        mint_and_list(seller, chars, 100, 900.0)
        mint_and_list(seller, chars, 200, 2_100.0)

        result = matching_service.invest_amount(buyer.id, 1_000.0, chars)
        assert result.total_price <= 1_000.0
        assert result.total_quantity == 100  # влезает только первый, более дешёвый вексель

    def test_invest_amount_no_affordable_voucher_raises(self):
        seller = make_user("seller@test.com", "Продавец")
        buyer = make_user("buyer@test.com", "Покупатель", legal=False)
        chars = make_characteristics()
        seed_balance(seller, chars, 100)
        mint_and_list(seller, chars, 100, 5_000.0)

        with pytest.raises(InsufficientMarketSupplyError):
            matching_service.invest_amount(buyer.id, 10.0, chars)
