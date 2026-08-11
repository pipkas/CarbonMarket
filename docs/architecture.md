# Архитектура Carbon Market — подробное описание

## 1. Идея и терминология

- **УЕ (углеродная единица)** — единица учёта сокращения/поглощения выбросов
  парниковых газов, хранится и учитывается во ВНЕШНЕМ реестре (сейчас —
  заглушка `RegistryClient`, потом — реальный API национального/
  международного реестра, аналог механизмов ст. 6 Парижского соглашения).
- **Вексель (SimpleVoucher)** — право требования покупателя на конкретный
  объём УЕ конкретных характеристик у конкретного продавца. Выпуск векселя
  **замораживает** соответствующий объём УЕ в реестре на счету продавца
  (продавец больше не может продать их повторно), но **не переносит** их
  на баланс покупателя.
- **Обналичивание (redeem)** — момент, когда покупателю нужны именно УЕ
  на балансе (например, для зачёта собственных выбросов), а не просто
  владение векселем. По каждому SimpleVoucher вызывается
  `RegistryClient.transfer_units`, и УЕ реально переходят покупателю.
- **Сборный вексель (CompositeVoucher)** — обёртка для UX: одна покупка
  пользователя может состоять из нескольких SimpleVoucher от разных
  продавцов, но пользователь видит один "чек".
- **Объявление (Listing)** — лот продавца: какие УЕ, сколько, по какой
  цене/комиссии, с какими ограничениями на объём одной сделки.

## 2. Модель данных и её связи

```
User (физ/юр лицо)
  └── registry_account_id ──────────► CarbonUnitBatch[] (в RegistryClient)
                                            (партии УЕ с характеристиками
                                             и полями quantity/frozen_quantity)

Listing (объявление продавца)
  ├── seller_id ──────────────────► User
  ├── characteristics ────────────► CarbonUnitCharacteristics (что продаём)
  ├── total_quantity / remaining_quantity
  ├── pricing_mode: PER_UNIT_MARKUP | FLAT_FEE_PER_DEAL
  └── min_deal_quantity / max_deal_quantity (гибкие правила из ТЗ)

SimpleVoucher (результат одной сделки по одному Listing)
  ├── listing_id, seller_id, buyer_id
  ├── quantity, price_per_unit, total_price
  ├── registry_freeze_ref ─────────► операция заморозки в RegistryClient
  └── status: ISSUED -> REDEEMED (или CANCELLED)

CompositeVoucher (агрегатор для покупателя)
  └── component_voucher_ids[] ─────► SimpleVoucher[]
```

## 3. Ценообразование

Из ТЗ: продавец либо назначает цену за единицу напрямую (наценка над
базовой ценой, например 7 руб. вместо 6), либо назначает фиксированную
комиссию за сделку (не за единицу). Оба варианта в `Listing`:

- `PER_UNIT_MARKUP` — `price_per_unit` используется как есть.
- `FLAT_FEE_PER_DEAL` — `flat_fee_per_deal` размазывается на объём
  конкретной сделки: `base_reference_price + flat_fee_per_deal / deal_quantity`.

Метод `Listing.effective_price_per_unit(deal_quantity)` приводит оба
режима к единой "цене за единицу" — именно по нему matching_service
сортирует и сравнивает предложения разных продавцов.

## 4. Три сценария покупки (маршруты `/market/*`)

### Сценарий 1 — "купить сейчас, точное количество"
`POST /market/buy-exact-quantity {quantity_needed, characteristics?}`
→ `matching_service.buy_exact_quantity`. Жадно берёт самые дешёвые
активные объявления (с учётом фильтра характеристик и min/max_deal),
пока не наберётся `quantity_needed`. Если не набралось —
`InsufficientMarketSupplyError` с `best_available`.

### Сценарий 2 — "инвестор, есть сумма денег"
`POST /market/invest-amount {budget_amount, characteristics?}`
→ `matching_service.invest_amount`. То же самое, но останавливается по
исчерпанию бюджета, а не по количеству УЕ — максимизирует объём на
заданные деньги.

### Режим "выбрать продавца" (ручной)
`GET /listings?...&sort_by=price|quantity|created_at` — покупатель сам
смотрит и сортирует предложения (`listing_service.browse_listings`), затем
`POST /market/reserve-from-listing {listing_id, quantity}` — оформляет
сделку по конкретному объявлению напрямую, без алгоритма подбора.

Все три пути в итоге вызывают `voucher_service.issue_simple_voucher` +
`voucher_service.build_composite_voucher` — бизнес-инвариант выпуска
векселя не дублируется.

## 5. Алгоритм подбора (matching_service) — ограничения и развитие

Реализован **жадный** алгоритм (сортировка по цене + последовательное
"откусывание" от дешёвых объявлений с уважением к `min/max_deal_quantity`).
Это быстро и просто, но НЕ гарантирует глобально оптимальную по цене
комбинацию в случаях, когда жёсткие `min_deal_quantity` создают
комбинаторные ограничения (классическая задача о рюкзаке).

**Точка расширения**: заменить шаг подбора на точный солвер (ILP через
`pulp`/`ortools`) с той же сигнатурой `buy_exact_quantity`/`invest_amount`,
не трогая остальной код — сервисы уже изолируют этот алгоритм от
API-слоя и от репозиториев.

**Известное упрощение MVP**: если `max_deal_quantity` одного объявления
не позволяет закрыть весь остаток потребности за один проход, повторного
захода на то же объявление в рамках одного запроса сейчас нет (можно
дважды купить у одного продавца, просто оформив два отдельных запроса).
Отмечено как TODO в `tests/test_matching_service.py`.

## 6. Продавец: сколько он может продать (`seller_capacity_service`)

```
доступно_для_продажи =
    остаток_в_реестре(характеристики)     # RegistryClient.get_balance(...).available_quantity
    - объём_уже_в_ДРУГИХ_активных_объявлениях_с_пересекающимися_характеристиками
```

Проверяется при создании каждого нового `Listing`
(`listing_service.create_listing`), чтобы нельзя было выставить один и
тот же объём УЕ в нескольких объявлениях одновременно (до фактической
заморозки под конкретную сделку остаток остаётся "виртуально" общим).

## 7. Аутентификация (заглушка)

`core/security.py` — простой opaque-токен в `dict` с TTL, `core/dependencies.py`
— `get_current_user` через заголовок `Authorization: Bearer <token>`.
Интерфейс (`create_token`/`get_user_id_by_token`/`revoke_token`) намеренно
такой же, какой будет и при переходе на JWT — переписывать вызывающий код
не придётся.

## 8. Интеграция с реальным реестром УЕ

Единственная точка интеграции — `services/registry_client.py`. Публичный
интерфейс (`get_balance`, `freeze_units`, `unfreeze_units`, `transfer_units`)
спроектирован так, как должен выглядеть и с реальным HTTP-клиентом к API
реестра. Замена реализации не потребует изменений в `matching_service`,
`voucher_service`, `seller_capacity_service` — они используют только
интерфейс, не детали.

## 9. Точки расширения (не входят в MVP, но заложены в модели)

- **Вторичный рынок векселей**: `SimpleVoucher.buyer_id` можно переуступать
  другому пользователю до `redeem` — сама операция переуступки и её API
  не реализованы, но модель это не блокирует.
- **Персистентность**: все `repositories/*_repo.py` сейчас — тонкая
  обёртка над `InMemoryStore`; переход на Postgres/SQLAlchemy — замена
  реализации репозиториев без изменения сервисов и роутов.
- **Оптимальный подбор предложений**: см. п. 5.
- **Частичная отмена/rollback сделки**: при ошибке в середине сборки
  композитного векселя (сценарий 1) уже выпущенные `SimpleVoucher` сейчас
  не откатываются автоматически — нужна транзакционность на уровне
  `matching_service` (unfreeze + отмена всех выпущенных в рамках запроса
  векселей при неудаче).
- **KYC/верификация юр. и физ. лиц** перед допуском к торгам — сейчас
  регистрация ничего не проверяет, кроме уникальности email.

## 10. Карта файлов

```
carbon-market/
├── README.md                          — как запустить
├── requirements.txt
├── docs/architecture.md               — этот файл
├── tests/test_matching_service.py     — описание тест-кейсов (заглушка)
└── app/
    ├── main.py                        — сборка FastAPI, обработчики ошибок, seed демо-данных
    ├── config.py                      — константы/настройки
    ├── core/
    │   ├── security.py                — токен-стор аутентификации (заглушка)
    │   ├── dependencies.py            — get_current_user
    │   └── exceptions.py              — доменные исключения
    ├── models/                        — доменные сущности (dataclass)
    │   ├── user.py
    │   ├── carbon_unit.py             — характеристики УЕ + партии в реестре
    │   ├── listing.py                 — объявления продавца
    │   └── voucher.py                 — SimpleVoucher / CompositeVoucher
    ├── repositories/                  — in-memory "БД"
    │   ├── memory_store.py            — generic-обёртка
    │   ├── user_repo.py
    │   ├── listing_repo.py
    │   └── voucher_repo.py
    ├── services/                      — бизнес-логика
    │   ├── registry_client.py         — заглушка внешнего реестра УЕ (единственная точка интеграции)
    │   ├── auth_service.py            — регистрация/логин
    │   ├── seller_capacity_service.py — сколько продавец реально может продать
    │   ├── listing_service.py         — создание/отмена/просмотр объявлений
    │   ├── matching_service.py        — ЯДРО: 3 сценария покупки, алгоритм подбора
    │   └── voucher_service.py         — выпуск и обналичивание векселей
    ├── schemas/                       — Pydantic DTO для API
    │   ├── auth.py
    │   ├── carbon_unit.py
    │   ├── listing.py
    │   └── market.py
    └── api/                           — HTTP-роуты
        ├── routes_auth.py
        ├── routes_listings.py
        ├── routes_market.py
        └── routes_vouchers.py
```
