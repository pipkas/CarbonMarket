"""
ЯДРО РЫНКА — ПОСЛЕ смены модели.

Раньше объявления продавали "сырые" углеродные единицы, которые можно
было брать частями (сколько нужно). ТЕПЕРЬ каждое объявление — это ровно
ОДИН конкретный, уже выпущенный вексель (Voucher) с фиксированной ценой
за весь его объём целиком. Вексель НЕДЕЛИМ: либо берём его весь, либо не
берём вовсе. Это меняет сам алгоритм подбора — раньше можно было "отрезать"
от объявления ровно нужный остаток, теперь подбор — это выбор ЦЕЛЫХ
предложений (векселей), которые в сумме лучше всего закрывают запрос
(похоже на задачу о рюкзаке).

  1) buy_exact_quantity — покупатель называет нужный объём. Берём самые
     дешёвые (₽ за единицу) подходящие векселя один за другим, пока
     суммарный объём не достигнет требуемого. Поскольку векселя неделимы,
     точное совпадение не гарантировано — либо остаётся unmet_quantity
     (не набралось), либо последний вексель может "перекрыть" запрос
     (total_quantity выйдет чуть больше quantity_needed) — покупатель
     видит это в превью ДО оплаты и решает сам.

  2) invest_amount — покупатель называет бюджет. Идём по тем же
     отсортированным по цене векселям и берём целиком каждый, который
     укладывается в остаток бюджета (не обязательно подряд — если
     очередной вексель не влезает, пробуем следующий, вдруг он дешевле
     по общей цене).

  3) buy_listing_direct — покупатель уже сам выбрал конкретное
     объявление (конкретный вексель) на витрине — просто покупаем его.

ОГОВОРКА (честно фиксируем ограничение MVP): жадная эвристика, а не
гарантированно оптимальное решение задачи о рюкзаке. Точка расширения —
заменить `_allocate` на ILP/DP-солвер, не трогая остальной код.
"""
from dataclasses import dataclass, field

from app.core.exceptions import InsufficientMarketSupplyError
from app.models.activity import ActivityType
from app.models.carbon_unit import CarbonUnitCharacteristics
from app.models.listing import Listing
from app.models.voucher import Voucher
from app.repositories import activity_repo
from app.repositories.listing_repo import get_active
from app.repositories.voucher_repo import voucher_repo
from app.services import voucher_service


@dataclass
class AllocationItem:
    listing: Listing
    voucher: Voucher
    price: float          # = listing.fixed_price (вся цена за вексель целиком)
    price_per_unit: float  # только для отображения/сортировки, не для оплаты


@dataclass
class AllocationResult:
    items: list[AllocationItem] = field(default_factory=list)
    total_quantity: float = 0.0
    total_price: float = 0.0
    unmet_quantity: float = 0.0     # только для режима "точное количество"
    leftover_budget: float = 0.0    # только для режима "бюджет"


@dataclass
class PurchaseResult:
    vouchers: list[Voucher]
    total_quantity: float
    total_price: float
    scenario: str


def _candidate_pairs(characteristics_filter: CarbonUnitCharacteristics | None) -> list[tuple[Listing, Voucher]]:
    listings = get_active()
    pairs = [(l, voucher_repo.get(l.voucher_id)) for l in listings]
    pairs = [(l, v) for l, v in pairs if v is not None]
    if characteristics_filter:
        pairs = [(l, v) for l, v in pairs if v.characteristics.matches(characteristics_filter)]
    pairs.sort(key=lambda pair: pair[0].fixed_price / pair[1].quantity)
    return pairs


def _allocate(
    candidates: list[tuple[Listing, Voucher]],
    quantity_target: float | None = None,
    budget_target: float | None = None,
) -> AllocationResult:
    assert (quantity_target is None) != (budget_target is None), "укажите ровно одну цель"

    result = AllocationResult()

    if quantity_target is not None:
        remaining_needed = quantity_target
        for listing, voucher in candidates:
            if remaining_needed <= 1e-9:
                break
            price_per_unit = listing.fixed_price / voucher.quantity
            result.items.append(AllocationItem(listing, voucher, listing.fixed_price, price_per_unit))
            remaining_needed -= voucher.quantity
        result.unmet_quantity = max(0.0, remaining_needed)

    else:
        remaining_budget = budget_target
        for listing, voucher in candidates:
            if remaining_budget <= 1e-9:
                break
            if listing.fixed_price > remaining_budget + 1e-9:
                continue  # этот вексель не влезает в остаток бюджета — пробуем следующий
            price_per_unit = listing.fixed_price / voucher.quantity
            result.items.append(AllocationItem(listing, voucher, listing.fixed_price, price_per_unit))
            remaining_budget -= listing.fixed_price
        result.leftover_budget = max(0.0, remaining_budget)

    result.total_quantity = sum(i.voucher.quantity for i in result.items)
    result.total_price = sum(i.price for i in result.items)
    return result


# ---------------------------------------------------------------------------
# ПРЕВЬЮ — только расчёт, ничего не резервирует и не требует авторизации
# ---------------------------------------------------------------------------

def preview_buy_exact_quantity(quantity_needed: float, characteristics_filter: CarbonUnitCharacteristics | None = None) -> AllocationResult:
    return _allocate(_candidate_pairs(characteristics_filter), quantity_target=quantity_needed)


def preview_invest_amount(budget_amount: float, characteristics_filter: CarbonUnitCharacteristics | None = None) -> AllocationResult:
    return _allocate(_candidate_pairs(characteristics_filter), budget_target=budget_amount)


# ---------------------------------------------------------------------------
# ИСПОЛНЕНИЕ — реально покупает векселя (требует авторизованного покупателя)
# ---------------------------------------------------------------------------

def _execute(buyer_id: str, allocation: AllocationResult, scenario: str) -> PurchaseResult:
    purchased = [voucher_service.buy_listing(buyer_id, item.listing) for item in allocation.items]

    if purchased:
        only = purchased[0] if len(purchased) == 1 else None
        counterparty_name = None
        project_name = None
        if only:
            from app.repositories.user_repo import user_repo
            project_name = only.characteristics.project_name
            seller = user_repo.get(allocation.items[0].listing.seller_id)
            counterparty_name = seller.display_name if seller else None

        activity_repo.log(
            buyer_id, ActivityType.PURCHASE,
            quantity=allocation.total_quantity, amount=allocation.total_price,
            project_name=project_name, counterparty_name=counterparty_name,
            related_id=purchased[0].id,
        )

    return PurchaseResult(
        vouchers=purchased,
        total_quantity=allocation.total_quantity,
        total_price=allocation.total_price,
        scenario=scenario,
    )


def buy_exact_quantity(buyer_id: str, quantity_needed: float, characteristics_filter: CarbonUnitCharacteristics | None = None) -> PurchaseResult:
    allocation = _allocate(_candidate_pairs(characteristics_filter), quantity_target=quantity_needed)

    if allocation.unmet_quantity > 1e-6:
        raise InsufficientMarketSupplyError(requested=quantity_needed, best_available=allocation.total_quantity)

    return _execute(buyer_id, allocation, scenario="BUY_EXACT_QUANTITY")


def invest_amount(buyer_id: str, budget_amount: float, characteristics_filter: CarbonUnitCharacteristics | None = None) -> PurchaseResult:
    allocation = _allocate(_candidate_pairs(characteristics_filter), budget_target=budget_amount)

    if not allocation.items:
        raise InsufficientMarketSupplyError(requested=budget_amount, best_available=0)

    return _execute(buyer_id, allocation, scenario="INVEST_AMOUNT")


def buy_listing_direct(buyer_id: str, listing: Listing) -> Voucher:
    from app.repositories.user_repo import user_repo

    seller = user_repo.get(listing.seller_id)
    voucher = voucher_service.buy_listing(buyer_id, listing)

    activity_repo.log(
        buyer_id, ActivityType.PURCHASE,
        quantity=voucher.quantity, amount=listing.fixed_price,
        project_name=voucher.characteristics.project_name,
        counterparty_name=seller.display_name if seller else None,
        related_id=voucher.id,
    )
    return voucher
