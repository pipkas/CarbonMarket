"""
ЯДРО РЫНКА. Три пути покупки:

  1) buy_exact_quantity — покупатель точно знает, сколько УЕ ему нужно
     (опционально — с фильтром характеристик, например "именно от проекта X").
     Система сама собирает самую дешёвую комбинацию предложений.

  2) invest_amount — покупатель вводит сумму денег, а не количество УЕ.
     Система максимизирует объём УЕ, который можно купить на эту сумму
     (опять же — самые дешёвые предложения в первую очередь).

  3) reserve_from_listing — покупатель уже сам посмотрел витрину
     (listing_service.browse_listings) и выбрал конкретное объявление и
     объём — здесь просто оформляем сделку по этому объявлению напрямую,
     без алгоритма подбора.

Расчёт для (1) и (2) вынесен в чистую функцию `_allocate` — она НЕ
выпускает векселя и ничего не мутирует, только считает, из каких
предложений и по какой цене можно собрать нужный объём/бюджет. Это
позволяет отдельно:
  - `preview_*` — показать покупателю ДО оплаты, из чего сложится
    покупка (топ предложений, цена, продавцы), не резервируя ничего;
  - `buy_exact_quantity` / `invest_amount` — выполнить ту же самую
    раскладку и уже реально выпустить векселя (заморозить УЕ в реестре).

ГЛАВНЫЙ АЛГОРИТМ (жадный, greedy):
  a) Взять активные объявления, подходящие под фильтр характеристик.
  b) Отсортировать по effective_price_per_unit(remaining_quantity) —
     то есть по цене "если бы брали весь остаток" (первое приближение;
     цена пересчитывается под реальный взятый объём на каждом шаге,
     т.к. для FLAT_FEE_PER_DEAL цена за единицу зависит от объёма сделки).
  c) Идти от самых дешёвых к самым дорогим и "откусывать" от каждого
     объявления столько, сколько можно:
       - не больше remaining_quantity этого объявления
       - не больше max_deal_quantity (если задан)
       - не меньше min_deal_quantity (если задан) — если оставшаяся
         потребность меньше минимума объявления, либо добираем до
         минимума (если это укладывается в остаток), либо пропускаем
         объявление для этого запроса.
  d) Останавливаемся, когда потребность закрыта (количество или бюджет).

  ОГОВОРКА (честно фиксируем ограничение MVP): это быстрая эвристика, а
  не гарантированно оптимальное решение задачи о рюкзаке, которая здесь
  возникает из-за min/max_deal_quantity. Точку расширения — замену на
  ILP/DP-солвер — можно внести в `_allocate`, не трогая остальной код.
"""
from dataclasses import dataclass, field

from app.core.exceptions import InsufficientMarketSupplyError
from app.models.carbon_unit import CarbonUnitCharacteristics
from app.models.listing import Listing
from app.models.voucher import CompositeVoucher
from app.repositories.listing_repo import get_active
from app.services import voucher_service


@dataclass
class AllocationItem:
    listing: Listing
    quantity: float
    price_per_unit: float
    subtotal: float


@dataclass
class AllocationResult:
    items: list[AllocationItem] = field(default_factory=list)
    total_quantity: float = 0.0
    total_price: float = 0.0
    unmet_quantity: float = 0.0     # только для режима "точное количество"
    leftover_budget: float = 0.0    # только для режима "бюджет"


def _candidate_listings(characteristics_filter: CarbonUnitCharacteristics | None) -> list[Listing]:
    listings = get_active()
    if characteristics_filter:
        listings = [l for l in listings if l.characteristics.matches(characteristics_filter)]
    listings.sort(key=lambda l: l.effective_price_per_unit(l.remaining_quantity))
    return listings


def _allocate(
    candidates: list[Listing],
    quantity_target: float | None = None,
    budget_target: float | None = None,
) -> AllocationResult:
    assert (quantity_target is None) != (budget_target is None), "укажите ровно одну цель"

    result = AllocationResult()

    if quantity_target is not None:
        remaining_needed = quantity_target
        for listing in candidates:
            if remaining_needed <= 1e-9:
                break
            upper_bound = listing.remaining_quantity
            if listing.max_deal_quantity:
                upper_bound = min(upper_bound, listing.max_deal_quantity)
            take = min(upper_bound, remaining_needed)
            if listing.min_deal_quantity and take < listing.min_deal_quantity:
                if listing.min_deal_quantity <= upper_bound:
                    take = listing.min_deal_quantity
                else:
                    continue
            if take <= 1e-9:
                continue
            price = listing.effective_price_per_unit(take)
            result.items.append(AllocationItem(listing, take, price, round(take * price, 2)))
            remaining_needed -= take
        result.unmet_quantity = max(0.0, remaining_needed)

    else:
        remaining_budget = budget_target
        for listing in candidates:
            if remaining_budget <= 1e-9:
                break
            upper_bound_qty = listing.remaining_quantity
            if listing.max_deal_quantity:
                upper_bound_qty = min(upper_bound_qty, listing.max_deal_quantity)
            price_per_unit = listing.effective_price_per_unit(upper_bound_qty)
            affordable_qty = remaining_budget / price_per_unit
            take = min(upper_bound_qty, affordable_qty)
            if listing.min_deal_quantity and take < listing.min_deal_quantity:
                continue
            if take <= 1e-9:
                continue
            subtotal = round(take * price_per_unit, 2)
            result.items.append(AllocationItem(listing, take, price_per_unit, subtotal))
            remaining_budget -= subtotal
        result.leftover_budget = max(0.0, remaining_budget)

    result.total_quantity = sum(i.quantity for i in result.items)
    result.total_price = sum(i.subtotal for i in result.items)
    return result


# ---------------------------------------------------------------------------
# ПРЕВЬЮ — только расчёт, ничего не резервирует и не требует авторизации
# (используется, чтобы показать покупателю топ предложений ДО оформления).
# ---------------------------------------------------------------------------

def preview_buy_exact_quantity(quantity_needed: float, characteristics_filter: CarbonUnitCharacteristics | None = None) -> AllocationResult:
    return _allocate(_candidate_listings(characteristics_filter), quantity_target=quantity_needed)


def preview_invest_amount(budget_amount: float, characteristics_filter: CarbonUnitCharacteristics | None = None) -> AllocationResult:
    return _allocate(_candidate_listings(characteristics_filter), budget_target=budget_amount)


# ---------------------------------------------------------------------------
# ИСПОЛНЕНИЕ — реально выпускает векселя (требует авторизованного покупателя)
# ---------------------------------------------------------------------------

def buy_exact_quantity(buyer_id: str, quantity_needed: float, characteristics_filter: CarbonUnitCharacteristics | None = None) -> CompositeVoucher:
    allocation = _allocate(_candidate_listings(characteristics_filter), quantity_target=quantity_needed)

    if allocation.unmet_quantity > 1e-6:
        raise InsufficientMarketSupplyError(requested=quantity_needed, best_available=allocation.total_quantity)

    issued_vouchers = [
        voucher_service.issue_simple_voucher(item.listing, buyer_id, item.quantity)
        for item in allocation.items
    ]
    return voucher_service.build_composite_voucher(buyer_id, issued_vouchers, scenario="BUY_EXACT_QUANTITY")


def invest_amount(buyer_id: str, budget_amount: float, characteristics_filter: CarbonUnitCharacteristics | None = None) -> CompositeVoucher:
    allocation = _allocate(_candidate_listings(characteristics_filter), budget_target=budget_amount)

    if not allocation.items:
        raise InsufficientMarketSupplyError(requested=budget_amount, best_available=0)

    issued_vouchers = [
        voucher_service.issue_simple_voucher(item.listing, buyer_id, item.quantity)
        for item in allocation.items
    ]
    return voucher_service.build_composite_voucher(buyer_id, issued_vouchers, scenario="INVEST_AMOUNT")


def reserve_from_listing(buyer_id: str, listing: Listing, quantity: float) -> CompositeVoucher:
    voucher = voucher_service.issue_simple_voucher(listing, buyer_id, quantity)
    return voucher_service.build_composite_voucher(buyer_id, [voucher], scenario="CHOOSE_SELLER")
