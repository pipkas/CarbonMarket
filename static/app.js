/* ==========================================================================
   Carbon Market — фронтенд без сборки (vanilla JS), работает поверх
   FastAPI-бэкенда из этого же проекта (тот же origin, поэтому пути
   вида '/auth/login' указывают прямо на API).
   ========================================================================== */

const state = {
  token: localStorage.getItem("cm_token") || null,
  user: JSON.parse(localStorage.getItem("cm_user") || "null"),
};

// Действие, отложенное до успешного входа (например, "купить", если
// человек нажал «Купить», не будучи авторизован — после входа сразу
// выполняем то, что он изначально хотел).
let pendingAction = null;

const PROJECT_TYPES = [
  ["", "Любой тип проекта"],
  ["RENEWABLE_ENERGY", "ВИЭ"],
  ["FORESTRY", "Лесоклиматический"],
  ["METHANE_CAPTURE", "Улавливание метана"],
  ["ENERGY_EFFICIENCY", "Энергоэффективность"],
  ["WASTE_MANAGEMENT", "Утилизация отходов"],
  ["OTHER", "Другое"],
];

const UNIT_STATUSES = [
  ["", "Любой статус"],
  ["ISSUED", "Выпущена"],
  ["FROZEN", "Заморожена"],
  ["RETIRED", "Погашена"],
  ["TRANSFERRED", "Передана"],
];

const PROJECT_TYPE_LABELS = Object.fromEntries(PROJECT_TYPES.filter(([v]) => v));
const STATUS_LABELS = Object.fromEntries(UNIT_STATUSES.filter(([v]) => v));

const SCENARIO_LABELS = {
  BUY_EXACT_QUANTITY: "Точный объём",
  INVEST_AMOUNT: "Инвестиция по бюджету",
  CHOOSE_SELLER: "Прямая покупка",
};

const STATUS_PILL_LABELS = { ACTIVE: "Активно", PAUSED: "Пауза", SOLD_OUT: "Распродано", CANCELLED: "Отменено" };

/* ---------------------------- API-хелпер ---------------------------- */

async function api(path, { method = "GET", body, auth = true, query } = {}) {
  let url = path;
  if (query) {
    const usp = new URLSearchParams();
    Object.entries(query).forEach(([k, v]) => { if (v !== undefined && v !== null && v !== "") usp.append(k, v); });
    const qs = usp.toString();
    if (qs) url += (url.includes("?") ? "&" : "?") + qs;
  }

  const headers = { "Content-Type": "application/json" };
  if (auth && state.token) headers["Authorization"] = `Bearer ${state.token}`;

  const res = await fetch(url, { method, headers, body: body !== undefined ? JSON.stringify(body) : undefined });

  let data = null;
  try { data = await res.json(); } catch (_) { /* no body */ }

  if (res.status === 401 && auth) {
    // Токен истёк/невалиден — тихо разлогиниваем и просим войти снова.
    handleLoggedOut();
    toast("Сессия истекла — войдите заново.", true);
  }

  if (!res.ok) {
    const message = data?.detail || data?.error || `Ошибка запроса (${res.status})`;
    const err = new Error(message);
    err.payload = data;
    err.status = res.status;
    throw err;
  }
  return data;
}

/* ---------------------------- Toast ---------------------------- */

let toastTimer = null;
function toast(message, isError = false) {
  const el = document.getElementById("toast");
  el.textContent = message;
  el.classList.toggle("toast--error", isError);
  el.classList.toggle("toast--success", !isError);
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.hidden = true; }, 4500);
}

/* ============================================================
   АВТОРИЗАЦИЯ: модалка по кнопке, меню профиля, requireAuth()
   ============================================================ */

function initAuthTabs() {
  document.querySelectorAll("[data-authtab]").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll("[data-authtab]").forEach((b) => b.classList.remove("is-active"));
      btn.classList.add("is-active");
      const target = btn.dataset.authtab;
      document.getElementById("login-form").hidden = target !== "login";
      document.getElementById("register-form").hidden = target !== "register";
      document.getElementById("auth-error").hidden = true;
    });
  });

  const userTypeSelect = document.querySelector('#register-form [name="user_type"]');
  userTypeSelect.addEventListener("change", () => {
    const isLegal = userTypeSelect.value === "LEGAL_ENTITY";
    document.querySelectorAll("[data-legal-only]").forEach((el) => { el.hidden = !isLegal; });
  });
}

function openAuthModal(note) {
  const overlay = document.getElementById("auth-modal-overlay");
  const noteEl = document.getElementById("auth-modal-note");
  if (note) { noteEl.textContent = note; noteEl.hidden = false; } else { noteEl.hidden = true; }
  document.getElementById("auth-error").hidden = true;
  overlay.hidden = false;
  document.body.style.overflow = "hidden";
}

// Закрывает окно, НЕ трогая pendingAction — оно должно пережить закрытие
// модалки внутри onAuthSuccess (успешный вход выполняет отложенное
// действие сразу после закрытия окна).
function closeAuthModal() {
  document.getElementById("auth-modal-overlay").hidden = true;
  document.body.style.overflow = "";
}

// А это — явная отмена: человек закрыл окно сам, не завершив вход,
// поэтому то, что он пытался сделать, тоже отменяем.
function cancelAuthModal() {
  closeAuthModal();
  pendingAction = null;
}

document.getElementById("open-auth-btn").addEventListener("click", () => openAuthModal());
document.getElementById("close-auth-btn").addEventListener("click", cancelAuthModal);
document.getElementById("auth-modal-overlay").addEventListener("click", (e) => {
  if (e.target.id === "auth-modal-overlay") cancelAuthModal();
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !document.getElementById("auth-modal-overlay").hidden) cancelAuthModal();
});
document.querySelectorAll("[data-open-auth]").forEach((btn) => btn.addEventListener("click", () => openAuthModal()));

function showAuthError(message) {
  const el = document.getElementById("auth-error");
  el.textContent = message;
  el.hidden = false;
}

function onAuthSuccess(data) {
  state.token = data.token;
  state.user = { id: data.user_id, user_type: data.user_type, display_name: data.display_name };
  localStorage.setItem("cm_token", state.token);
  localStorage.setItem("cm_user", JSON.stringify(state.user));
  closeAuthModal();
  refreshAuthUI();
  toast(`Добро пожаловать, ${state.user.display_name}!`);

  if (pendingAction) {
    const action = pendingAction;
    pendingAction = null;
    action();
  } else {
    loadListings();
  }
}

document.getElementById("login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const fd = new FormData(e.target);
  try {
    const data = await api("/auth/login", { method: "POST", auth: false, body: { email: fd.get("email"), password: fd.get("password") } });
    onAuthSuccess(data);
  } catch (err) { showAuthError(err.message); }
});

document.getElementById("register-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const fd = new FormData(e.target);
  try {
    const data = await api("/auth/register", { method: "POST", auth: false, body: {
      email: fd.get("email"), password: fd.get("password"), user_type: fd.get("user_type"),
      display_name: fd.get("display_name"), inn: fd.get("inn") || null, ogrn: fd.get("ogrn") || null,
    }});
    onAuthSuccess(data);
  } catch (err) { showAuthError(err.message); }
});

/* --- меню профиля --- */
document.getElementById("user-chip-btn").addEventListener("click", (e) => {
  e.stopPropagation();
  const menu = document.getElementById("user-menu");
  menu.hidden = !menu.hidden;
});
document.addEventListener("click", () => { document.getElementById("user-menu").hidden = true; });

document.getElementById("logout-btn").addEventListener("click", handleLoggedOut);

function handleLoggedOut() {
  state.token = null;
  state.user = null;
  localStorage.removeItem("cm_token");
  localStorage.removeItem("cm_user");
  refreshAuthUI();
  goToView("market"); // приватные разделы больше не должны показывать чужие данные
}

function refreshAuthUI() {
  const loggedIn = !!state.token;
  document.getElementById("open-auth-btn").hidden = loggedIn;
  document.getElementById("user-chip").hidden = !loggedIn;
  if (loggedIn) {
    document.getElementById("user-chip-name").textContent = state.user.display_name;
    document.getElementById("user-menu-name").textContent = state.user.display_name;
    document.getElementById("user-menu-type").textContent = state.user.user_type === "LEGAL_ENTITY" ? "Юридическое лицо" : "Физическое лицо";
    document.getElementById("user-avatar").textContent = state.user.display_name.trim().charAt(0).toUpperCase() || "A";
  }
  renderAuthGates();
}

/** Требует авторизации для действия; если не авторизован — открывает
 *  модалку и откладывает действие на момент успешного входа. */
function requireAuth(action) {
  if (state.token) { action(); return; }
  pendingAction = action;
  openAuthModal("Войдите, чтобы завершить это действие.");
}

/* ============================================================
   НАВИГАЦИЯ ПО РАЗДЕЛАМ
   ============================================================ */

function goToView(view) {
  document.querySelectorAll(".topnav-item").forEach((b) => b.classList.toggle("is-active", b.dataset.view === view));
  document.querySelectorAll(".view").forEach((v) => v.classList.remove("is-active"));
  document.getElementById(`view-${view}`).classList.add("is-active");

  if (view === "market") loadListings();
  if (view === "listings" && state.token) loadMyListings();
  if (view === "vouchers" && state.token) loadMyVouchers();
}

document.querySelectorAll("[data-view]").forEach((btn) => {
  btn.addEventListener("click", () => goToView(btn.dataset.view));
});

/** «Мои объявления» и «Мои векселя» — приватные разделы: если человек не
 *  авторизован, вместо контента показываем приглашение войти. */
function renderAuthGates() {
  const loggedIn = !!state.token;
  document.getElementById("listings-authgate").hidden = loggedIn;
  document.getElementById("listings-authcontent").hidden = !loggedIn;
  document.getElementById("vouchers-authgate").hidden = loggedIn;
  document.getElementById("vouchers-authcontent").hidden = !loggedIn;
}

/* ============================================================
   Поля фильтра характеристик (используются в 4 местах)
   ============================================================ */

function renderCharacteristicsFields(container) {
  container.innerHTML = `
    <label class="field"><span>Название проекта</span><input type="text" name="project_name" placeholder="например, Реликтовый лес"></label>
    <label class="field"><span>Тип проекта</span><select name="project_type">${PROJECT_TYPES.map(([v, l]) => `<option value="${v}">${l}</option>`).join("")}</select></label>
    <label class="field"><span>Год выпуска</span><input type="number" name="vintage_year" placeholder="2024"></label>
    <label class="field"><span>Методология</span><input type="text" name="methodology" placeholder="например, VM0007"></label>
    <label class="field"><span>Верификатор</span><input type="text" name="verifier" placeholder="например, TÜV Nord"></label>
    <label class="field"><span>Страна/регион</span><input type="text" name="country" placeholder="например, RU"></label>
    <label class="field"><span>Дата выпуска</span><input type="date" name="issue_date"></label>
    <label class="field"><span>Статус</span><select name="status">${UNIT_STATUSES.map(([v, l]) => `<option value="${v}">${l}</option>`).join("")}</select></label>
  `;
}

function readCharacteristicsFields(container) {
  const out = {};
  container.querySelectorAll("[name]").forEach((el) => { if (el.value) out[el.name] = el.value; });
  return out;
}

document.querySelectorAll("[data-filter-fields]").forEach(renderCharacteristicsFields);

function characteristicsTags(c) {
  const tags = [];
  if (c.project_type) tags.push(PROJECT_TYPE_LABELS[c.project_type] || c.project_type);
  if (c.vintage_year) tags.push(`Выпуск ${c.vintage_year}`);
  if (c.methodology) tags.push(c.methodology);
  if (c.country) tags.push(c.country);
  if (c.verifier) tags.push(`Верификатор: ${c.verifier}`);
  if (c.status) tags.push(STATUS_LABELS[c.status] || c.status);
  return tags;
}

/* ============================================================
   ВИТРИНА: карточки объявлений (публично)
   ============================================================ */

function stampSvg() {
  return `<svg viewBox="0 0 120 120"><path d="M 60,60 m -46,0 a 46,46 0 1,1 92,0 a 46,46 0 1,1 -92,0" fill="none" stroke="currentColor" stroke-width="3" stroke-dasharray="3 5.5" stroke-linecap="round"/></svg>`;
}

function listingCard(listing) {
  const priceLabel = listing.pricing_mode === "PER_UNIT_MARKUP"
    ? `${listing.price_per_unit.toFixed(2)} ₽ / УЕ`
    : `${listing.flat_fee_per_deal.toFixed(2)} ₽ комиссия / сделку`;

  const constraints = [];
  if (listing.min_deal_quantity) constraints.push(`от ${listing.min_deal_quantity}`);
  if (listing.max_deal_quantity) constraints.push(`до ${listing.max_deal_quantity}`);
  const constraintLabel = constraints.length ? constraints.join(" · ") + " за сделку" : "без ограничений на сделку";

  const wrap = document.createElement("div");
  wrap.className = "card";
  wrap.innerHTML = `
    <div class="card-stamp">${stampSvg()}</div>
    <div class="card-project">${listing.characteristics.project_name || "Без названия проекта"}</div>
    <div class="card-seller">Продавец: ${listing.seller_display_name}</div>
    <div class="card-tags">${characteristicsTags(listing.characteristics).map((t) => `<span class="tag">${t}</span>`).join("")}</div>
    <div class="card-rows">
      <div class="card-row"><span>Цена</span><b class="price">${priceLabel}</b></div>
      <div class="card-row"><span>Доступно</span><b>${listing.remaining_quantity} УЕ</b></div>
      <div class="card-row"><span>Условия сделки</span><b>${constraintLabel}</b></div>
    </div>
    <div class="card-foot">
      <input type="number" min="0" step="1" placeholder="кол-во" data-qty>
      <button class="btn btn--primary btn--sm" data-buy>Купить</button>
    </div>
  `;
  wrap.querySelector("[data-buy]").addEventListener("click", () => {
    const qty = Number(wrap.querySelector("[data-qty]").value);
    if (!qty || qty <= 0) { toast("Укажите количество", true); return; }
    requireAuth(() => doReserveFromListing(listing.id, qty));
  });
  return wrap;
}

async function doReserveFromListing(listingId, qty) {
  try {
    const composite = await api("/market/reserve-from-listing", { method: "POST", body: { listing_id: listingId, quantity: qty } });
    toast(`Куплено ${composite.total_quantity} УЕ за ${composite.total_price.toFixed(2)} ₽. Вексель оформлен — смотрите «Мои векселя».`);
    loadListings();
  } catch (err) { toast(err.message, true); }
}

async function loadListings() {
  const grid = document.getElementById("listings-grid");
  grid.innerHTML = `<p class="empty-row">Загружаю предложения…</p>`;
  const sortBy = document.getElementById("sort-by").value;
  const filterContainer = document.querySelector('[data-filter-fields="browse"]');
  const filters = readCharacteristicsFields(filterContainer);
  try {
    const listings = await api("/listings", { auth: false, query: { ...filters, sort_by: sortBy } });
    grid.innerHTML = "";
    if (!listings.length) { grid.innerHTML = `<p class="empty-row">Подходящих предложений пока нет.</p>`; return; }
    listings.forEach((l) => grid.appendChild(listingCard(l)));
  } catch (err) {
    grid.innerHTML = `<p class="empty-row">${err.message}</p>`;
  }
}

document.getElementById("sort-by").addEventListener("change", loadListings);
document.getElementById("refresh-listings").addEventListener("click", loadListings);
document.getElementById("apply-browse-filter").addEventListener("click", loadListings);

/* ============================================================
   ПОДБОР ПРЕДЛОЖЕНИЙ (превью топ-5 ДО покупки) — публично
   ============================================================ */

function quoteOfferRow(offer) {
  const constraints = [];
  if (offer.min_deal_quantity) constraints.push(`от ${offer.min_deal_quantity}`);
  if (offer.max_deal_quantity) constraints.push(`до ${offer.max_deal_quantity}`);
  return `
    <tr>
      <td>
        <div class="quote-seller">${offer.characteristics.project_name || "Без названия проекта"}</div>
        <div style="font-size:12px;color:var(--ink-soft)">${offer.seller_display_name}</div>
        <div class="quote-tags">${characteristicsTags(offer.characteristics).map((t) => `<span class="tag">${t}</span>`).join("")}</div>
      </td>
      <td class="num">${offer.price_per_unit.toFixed(2)} ₽</td>
      <td class="num">${offer.quantity}</td>
      <td class="num">${offer.subtotal.toFixed(2)} ₽</td>
      <td style="font-size:12px;color:var(--ink-soft)">${constraints.join(" · ") || "—"}</td>
    </tr>
  `;
}

function renderQuote(quote, mode, requestBody) {
  const container = document.getElementById("quote-result");

  if (!quote.offers.length) {
    container.hidden = false;
    container.innerHTML = `<p class="empty-row">Подходящих предложений не нашлось — попробуйте изменить количество, бюджет или характеристики.</p>`;
    return;
  }

  let warning = "";
  if (mode === "quantity" && quote.unmet_quantity > 0) {
    warning = `<div class="quote-warning">На рынке пока нет достаточного объёма: удастся набрать ${quote.total_quantity} из ${requestBody.quantity_needed} УЕ.</div>`;
  }
  if (mode === "budget" && quote.leftover_budget > 0) {
    warning = `<div class="quote-warning">${quote.leftover_budget.toFixed(2)} ₽ из бюджета останется неизрасходовано — не набирается минимальный объём сделки у оставшихся продавцов.</div>`;
  }

  const moreLine = quote.offers_beyond_shown > 0
    ? `<span class="quote-more">и ещё ${quote.offers_beyond_shown} предложени${quote.offers_beyond_shown === 1 ? "е" : "й"} войдёт в покупку</span>`
    : `<span class="quote-more">это всё предложения, которые войдут в покупку</span>`;

  container.hidden = false;
  container.innerHTML = `
    <div class="quote-head">
      <h3>Лучшие предложения под ваш запрос</h3>
      <div class="quote-total">${quote.total_quantity} УЕ · ${quote.total_price.toFixed(2)} ₽</div>
    </div>
    <div class="quote-subline">Показаны до 5 самых дешёвых подходящих предложений.</div>
    ${warning}
    <table class="quote-table">
      <thead><tr><th>Предложение</th><th>Цена</th><th>Кол-во</th><th>Сумма</th><th>Условия</th></tr></thead>
      <tbody>${quote.offers.map(quoteOfferRow).join("")}</tbody>
    </table>
    <div class="quote-foot">
      ${moreLine}
      <button class="btn btn--primary" id="confirm-quote-btn">Подтвердить покупку</button>
    </div>
  `;

  document.getElementById("confirm-quote-btn").addEventListener("click", () => {
    requireAuth(() => doConfirmPurchase(mode, requestBody));
  });

  container.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

async function doConfirmPurchase(mode, requestBody) {
  const path = mode === "quantity" ? "/market/buy-exact-quantity" : "/market/invest-amount";
  try {
    const composite = await api(path, { method: "POST", body: requestBody });
    toast(`Готово: ${composite.total_quantity} УЕ за ${composite.total_price.toFixed(2)} ₽. Вексель оформлен — смотрите «Мои векселя».`);
    document.getElementById("quote-result").hidden = true;
    loadListings();
  } catch (err) {
    if (err.payload?.error === "insufficient_market_supply") {
      toast(`На рынке недостаточно предложений: максимум ${err.payload.best_available} УЕ.`, true);
    } else {
      toast(err.message, true);
    }
  }
}

document.getElementById("find-by-quantity-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = e.target;
  const quantity = Number(new FormData(form).get("quantity_needed"));
  const filters = readCharacteristicsFields(form.querySelector("[data-filter-fields]"));
  const body = { quantity_needed: quantity, characteristics: Object.keys(filters).length ? filters : null };
  try {
    const quote = await api("/market/quote/buy-exact-quantity", { method: "POST", auth: false, body });
    renderQuote(quote, "quantity", body);
  } catch (err) { toast(err.message, true); }
});

document.getElementById("find-by-budget-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = e.target;
  const budget = Number(new FormData(form).get("budget_amount"));
  const filters = readCharacteristicsFields(form.querySelector("[data-filter-fields]"));
  const body = { budget_amount: budget, characteristics: Object.keys(filters).length ? filters : null };
  try {
    const quote = await api("/market/quote/invest-amount", { method: "POST", auth: false, body });
    renderQuote(quote, "budget", body);
  } catch (err) { toast(err.message, true); }
});

/* ============================================================
   ПРОДАВЕЦ: создание объявления, список моих объявлений
   ============================================================ */

document.getElementById("pricing-mode-select").addEventListener("change", (e) => {
  const mode = e.target.value;
  document.querySelectorAll("[data-pricing]").forEach((el) => { el.hidden = el.dataset.pricing !== mode; });
});

document.getElementById("check-capacity-btn").addEventListener("click", async () => {
  const container = document.querySelector('[data-filter-fields="create"]');
  const filters = readCharacteristicsFields(container);
  const result = document.getElementById("capacity-result");
  try {
    const res = await api("/listings/available-capacity", { query: filters });
    result.textContent = `Доступно для продажи по этим характеристикам: ${res.available_quantity} УЕ.`;
  } catch (err) { result.textContent = err.message; }
});

document.getElementById("create-listing-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = e.target;
  const fd = new FormData(form);
  const characteristics = readCharacteristicsFields(form.querySelector('[data-filter-fields="create"]'));
  const pricingMode = fd.get("pricing_mode");
  const body = {
    characteristics,
    total_quantity: Number(fd.get("total_quantity")),
    pricing_mode: pricingMode,
    base_reference_price: Number(fd.get("base_reference_price")),
    price_per_unit: pricingMode === "PER_UNIT_MARKUP" ? Number(fd.get("price_per_unit")) : null,
    flat_fee_per_deal: pricingMode === "FLAT_FEE_PER_DEAL" ? Number(fd.get("flat_fee_per_deal")) : null,
    min_deal_quantity: fd.get("min_deal_quantity") ? Number(fd.get("min_deal_quantity")) : null,
    max_deal_quantity: fd.get("max_deal_quantity") ? Number(fd.get("max_deal_quantity")) : null,
  };
  try {
    await api("/listings", { method: "POST", body });
    toast("Объявление выставлено на продажу.");
    form.reset();
    document.getElementById("capacity-result").textContent = "";
    loadMyListings();
  } catch (err) { toast(err.message, true); }
});

async function loadMyListings() {
  const container = document.getElementById("my-listings-table");
  container.innerHTML = `<p class="empty-row">Загружаю…</p>`;
  try {
    const listings = await api("/listings/mine");
    if (!listings.length) { container.innerHTML = `<p class="empty-row">Вы ещё не выставляли объявлений — заполните форму выше.</p>`; return; }
    const rows = listings.map((l) => `
      <tr>
        <td>${l.characteristics.project_name || "—"}</td>
        <td class="num">${l.remaining_quantity} / ${l.total_quantity}</td>
        <td class="num">${l.pricing_mode === "PER_UNIT_MARKUP" ? l.price_per_unit.toFixed(2) + " ₽/УЕ" : l.flat_fee_per_deal.toFixed(2) + " ₽/сделку"}</td>
        <td class="num">${l.min_deal_quantity ?? "—"} / ${l.max_deal_quantity ?? "—"}</td>
        <td><span class="status-pill status-pill--${l.status.toLowerCase()}">${STATUS_PILL_LABELS[l.status] || l.status}</span></td>
        <td>${l.status === "ACTIVE" ? `<button class="btn btn--danger btn--sm" data-cancel="${l.id}">Отменить</button>` : ""}</td>
      </tr>
    `).join("");
    container.innerHTML = `
      <table>
        <thead><tr><th>Проект</th><th>Остаток / всего</th><th>Цена</th><th>Мин / Макс за сделку</th><th>Статус</th><th></th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    `;
    container.querySelectorAll("[data-cancel]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        try { await api(`/listings/${btn.dataset.cancel}`, { method: "DELETE" }); toast("Объявление отменено."); loadMyListings(); }
        catch (err) { toast(err.message, true); }
      });
    });
  } catch (err) { container.innerHTML = `<p class="empty-row">${err.message}</p>`; }
}

/* ============================================================
   ПОКУПАТЕЛЬ: мои векселя
   ============================================================ */

function voucherCard(v) {
  const wrap = document.createElement("div");
  wrap.className = "card";
  wrap.innerHTML = `
    <div class="card-stamp">${stampSvg()}</div>
    <div class="card-project">${v.total_quantity} УЕ</div>
    <div class="card-tags"><span class="tag">${SCENARIO_LABELS[v.scenario] || v.scenario}</span><span class="tag">${v.component_voucher_ids.length} компонент(ов)</span></div>
    <div class="card-rows">
      <div class="card-row"><span>Стоимость</span><b class="price">${v.total_price.toFixed(2)} ₽</b></div>
      <div class="card-row"><span>Оформлен</span><b>${new Date(v.created_at).toLocaleString("ru-RU")}</b></div>
    </div>
    <div class="card-foot">
      <button class="btn btn--primary btn--sm" data-redeem>Обналичить — зачислить УЕ</button>
    </div>
  `;
  wrap.querySelector("[data-redeem]").addEventListener("click", async () => {
    try { await api(`/vouchers/${v.id}/redeem`, { method: "POST" }); toast("Вексель обналичен — УЕ зачислены на ваш баланс в реестре."); loadMyVouchers(); }
    catch (err) { toast(err.message, true); }
  });
  return wrap;
}

async function loadMyVouchers() {
  const grid = document.getElementById("vouchers-list");
  grid.innerHTML = `<p class="empty-row">Загружаю…</p>`;
  try {
    const vouchers = await api("/vouchers/mine");
    if (!vouchers.length) { grid.innerHTML = `<p class="empty-row">У вас пока нет векселей — оформите покупку на витрине.</p>`; return; }
    grid.innerHTML = "";
    vouchers.forEach((v) => grid.appendChild(voucherCard(v)));
  } catch (err) { grid.innerHTML = `<p class="empty-row">${err.message}</p>`; }
}

/* ---------------------------- Инициализация ---------------------------- */

initAuthTabs();
refreshAuthUI();
loadListings();
