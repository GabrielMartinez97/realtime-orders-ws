/**
 * Controlador principal de la interfaz de Pedidos y Notificaciones en Tiempo Real (Fase 4).
 * Construye nodos DOM seguros (textContent) sin usar handlers inline (CSP-friendly).
 */

import { ApiClient } from "./api.js";
import { RealtimeWSClient } from "./ws_client.js";

const STATUS_LABELS = {
  RECEIVED: "Recibido",
  PREPARING: "Preparando",
  READY: "Listo para retirar",
  DELIVERED: "Entregado",
  CANCELLED: "Cancelado",
};

const NEXT_OPERATOR_ACTIONS = {
  RECEIVED: [
    { status: "PREPARING", label: "Pasar a Preparando", style: "btn-primary" },
    { status: "CANCELLED", label: "Cancelar pedido", style: "btn-danger" },
  ],
  PREPARING: [
    { status: "READY", label: "Marcar como Listo", style: "btn-primary" },
    { status: "CANCELLED", label: "Cancelar pedido", style: "btn-danger" },
  ],
  READY: [
    { status: "DELIVERED", label: "Marcar como Entregado", style: "btn-primary" },
  ],
  DELIVERED: [],
  CANCELLED: [],
};

const api = new ApiClient();

const state = {
  user: null,
  stores: [],
  products: [],
  cart: {}, // { productId: quantity }
  orders: new Map(), // orderId -> order object
  notifications: [], // lista ordenada de notificaciones
  unreadCount: 0,
  selectedAdminStoreId: "",
};

// Referencias del DOM
const authSection = document.getElementById("auth-section");
const workspaceSection = document.getElementById("workspace-section");
const sessionBar = document.getElementById("session-bar");
const wsDot = document.getElementById("ws-dot");
const wsStatusText = document.getElementById("ws-status-text");
const wsLatency = document.getElementById("ws-latency");
const userNameLabel = document.getElementById("user-name-label");
const userRoleBadge = document.getElementById("user-role-badge");

const btnToggleNotifications = document.getElementById("btn-toggle-notifications");
const notifUnreadBadge = document.getElementById("notif-unread-badge");
const panelUnreadCount = document.getElementById("panel-unread-count");
const notificationsPanel = document.getElementById("notifications-panel");
const notificationsListEl = document.getElementById("notifications-list");
const btnMarkAllRead = document.getElementById("btn-mark-all-read");

const loginForm = document.getElementById("login-form");
const loginEmail = document.getElementById("login-email");
const loginPassword = document.getElementById("login-password");
const loginError = document.getElementById("login-error");
const loginSubmitBtn = document.getElementById("login-submit-btn");
const demoButtonsGrid = document.getElementById("demo-buttons-grid");

const customerOrderPanel = document.getElementById("customer-order-panel");
const storeSelect = document.getElementById("store-select");
const catalogList = document.getElementById("catalog-list");
const orderNotes = document.getElementById("order-notes");
const cartTotalLabel = document.getElementById("cart-total-label");
const createOrderForm = document.getElementById("create-order-form");
const createOrderSubmit = document.getElementById("create-order-submit");
const orderFormError = document.getElementById("order-form-error");

const staffInfoPanel = document.getElementById("staff-info-panel");
const staffScopeDescription = document.getElementById("staff-scope-description");
const adminStoreFilterBox = document.getElementById("admin-store-filter-box");
const adminStoreFilter = document.getElementById("admin-store-filter");
const activeRoomsList = document.getElementById("active-rooms-list");

const ordersListEl = document.getElementById("orders-list");
const resyncTimestampEl = document.getElementById("resync-timestamp");
const wsLogBox = document.getElementById("ws-log-box");
const toastContainer = document.getElementById("toast-container");

function showToast(title, message) {
  const toast = document.createElement("div");
  toast.className = "toast";
  const strong = document.createElement("strong");
  strong.textContent = `${title}: `;
  const span = document.createElement("span");
  span.textContent = message;
  toast.append(strong, span);
  toastContainer.appendChild(toast);

  window.setTimeout(() => {
    toast.remove();
  }, 4500);
}

function appendWireLog(direction, payload) {
  const timeStr = new Date().toLocaleTimeString();
  const line = `[${timeStr}] ${direction} ${JSON.stringify(payload)}\n`;
  if (wsLogBox.textContent === "Esperando conexión...") {
    wsLogBox.textContent = line;
  } else {
    wsLogBox.textContent = `${line}${wsLogBox.textContent}`.slice(0, 8000);
  }
}

const wsClient = new RealtimeWSClient({
  onEvent: handleRealtimeEvent,
  onStatusChange: handleWSStatusChange,
  onReconnectResync: async () => {
    showToast("Reconexión exitosa", "Resincronizando pedidos y notificaciones con la API REST...");
    await Promise.all([resyncOrdersFromREST(), loadNotificationsFromREST()]);
  },
  onWireLog: appendWireLog,
});

function handleWSStatusChange({ state: connState, latencyMs, attempt, delayMs, rooms }) {
  wsDot.className = `ws-dot ${connState}`;
  if (connState === "connected") {
    wsStatusText.textContent = "En línea (WS)";
    if (latencyMs !== null && latencyMs !== undefined) {
      wsLatency.textContent = `(${latencyMs} ms)`;
    }
  } else if (connState === "reconnecting") {
    const secs = (delayMs / 1000).toFixed(1);
    wsStatusText.textContent = `Reconectando #${attempt} en ${secs}s...`;
    wsLatency.textContent = "";
  } else {
    wsStatusText.textContent = "Desconectado";
    wsLatency.textContent = "";
  }

  if (Array.isArray(rooms)) {
    renderActiveRooms(rooms);
  }
}

function renderActiveRooms(rooms) {
  activeRoomsList.replaceChildren();
  for (const r of rooms) {
    const li = document.createElement("li");
    li.textContent = r;
    activeRoomsList.appendChild(li);
  }
}

function handleRealtimeEvent(envelope) {
  if (envelope.event === "pedido_creado" && envelope.data?.order) {
    const order = envelope.data.order;
    upsertOrderInMemory(order, true);
  } else if (envelope.event === "estado_actualizado" && envelope.data?.order) {
    const order = envelope.data.order;
    upsertOrderInMemory(order, true);
  } else if (envelope.event === "notificacion" && envelope.data?.notification) {
    const notif = envelope.data.notification;
    state.unreadCount = envelope.data.unread_count ?? state.unreadCount + 1;
    // Evitamos duplicados si ya existía en la lista
    state.notifications = [
      notif,
      ...state.notifications.filter((n) => n.id !== notif.id),
    ].slice(0, 30);
    renderNotifications();
    showToast(notif.title, notif.message);
  } else if (envelope.event === "subscribed" && envelope.data?.rooms) {
    renderActiveRooms(envelope.data.rooms);
  } else if (envelope.event === "error") {
    showToast("Error WebSocket", envelope.data?.message || "Acción no permitida");
  }
}

async function loadNotificationsFromREST() {
  if (!state.user) return;
  const summary = await api.listNotifications(30);
  state.notifications = summary.items || [];
  state.unreadCount = summary.unread_count || 0;
  renderNotifications();
}

function renderNotifications() {
  // Actualizar badges de contador de no leídas
  if (state.unreadCount > 0) {
    notifUnreadBadge.textContent = String(state.unreadCount);
    notifUnreadBadge.hidden = false;
    panelUnreadCount.textContent = String(state.unreadCount);
    panelUnreadCount.hidden = false;
  } else {
    notifUnreadBadge.hidden = true;
    panelUnreadCount.hidden = true;
  }

  notificationsListEl.replaceChildren();
  if (state.notifications.length === 0) {
    const empty = document.createElement("p");
    empty.className = "muted small";
    empty.textContent = "No tienes notificaciones registradas.";
    notificationsListEl.appendChild(empty);
    return;
  }

  for (const notif of state.notifications) {
    const item = document.createElement("div");
    item.className = `notif-item ${notif.is_read ? "read" : "unread"}`;

    const body = document.createElement("div");
    body.className = "notif-item-body";

    const titleEl = document.createElement("strong");
    const timeStr = new Date(notif.created_at).toLocaleTimeString();
    titleEl.textContent = `${notif.title} · ${timeStr}`;

    const msgEl = document.createElement("p");
    msgEl.textContent = notif.message;

    body.append(titleEl, msgEl);
    item.appendChild(body);

    if (!notif.is_read) {
      const readBtn = document.createElement("button");
      readBtn.type = "button";
      readBtn.className = "btn btn-outline btn-sm";
      readBtn.dataset.notifId = String(notif.id);
      readBtn.textContent = "Leída";
      item.appendChild(readBtn);
    }

    notificationsListEl.appendChild(item);
  }
}

function upsertOrderInMemory(order, flash = false) {
  if (
    state.user?.role === "ADMIN" &&
    state.selectedAdminStoreId &&
    String(order.store_id) !== String(state.selectedAdminStoreId)
  ) {
    return;
  }
  state.orders.set(order.id, order);
  renderOrdersList(flash ? order.id : null);
}

async function resyncOrdersFromREST() {
  if (!state.user) return;
  const storeFilter =
    state.user.role === "ADMIN" && state.selectedAdminStoreId
      ? state.selectedAdminStoreId
      : null;

  const ordersArray = await api.listOrders(storeFilter);
  state.orders.clear();
  for (const o of ordersArray) {
    state.orders.set(o.id, o);
  }
  renderOrdersList();
  resyncTimestampEl.textContent = `Sincronizado con API REST a las ${new Date().toLocaleTimeString()}`;
}

function getStoreName(storeId) {
  const found = state.stores.find((s) => s.id === storeId);
  return found ? found.name : `Tienda #${storeId}`;
}

function renderOrdersList(highlightOrderId = null) {
  ordersListEl.replaceChildren();
  const sorted = Array.from(state.orders.values()).sort((a, b) => b.id - a.id);

  if (sorted.length === 0) {
    const empty = document.createElement("p");
    empty.className = "muted";
    empty.textContent = "Aún no hay pedidos para mostrar en este canal.";
    ordersListEl.appendChild(empty);
    return;
  }

  for (const order of sorted) {
    const card = document.createElement("article");
    card.className = "order-card";
    if (highlightOrderId === order.id) {
      card.classList.add("highlight-flash");
    }

    const header = document.createElement("div");
    header.className = "order-header";

    const titleGroup = document.createElement("div");
    const strongId = document.createElement("strong");
    strongId.textContent = `Pedido #${order.id} · ${getStoreName(order.store_id)}`;
    const subMeta = document.createElement("span");
    subMeta.className = "muted small";
    subMeta.textContent = ` · Cliente ID #${order.customer_id} · Total: $${order.total_amount}`;
    titleGroup.append(strongId, subMeta);

    const badge = document.createElement("span");
    badge.className = `status-badge status-${order.status}`;
    badge.textContent = STATUS_LABELS[order.status] || order.status;

    header.append(titleGroup, badge);
    card.appendChild(header);

    const ul = document.createElement("ul");
    ul.className = "order-items-ul";
    for (const item of order.items || []) {
      const li = document.createElement("li");
      li.textContent = `${item.quantity}x ${item.product_name_snapshot} ($${item.unit_price_snapshot} c/u) = $${item.subtotal}`;
      ul.appendChild(li);
    }
    card.appendChild(ul);

    if (order.notes) {
      const notesP = document.createElement("p");
      notesP.className = "muted small";
      notesP.textContent = `Nota del cliente: "${order.notes}"`;
      card.appendChild(notesP);
    }

    const actionsDiv = document.createElement("div");
    actionsDiv.className = "order-actions";

    if (state.user.role === "OPERATOR" || state.user.role === "ADMIN") {
      const nextActions = NEXT_OPERATOR_ACTIONS[order.status] || [];
      for (const act of nextActions) {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = `btn btn-sm ${act.style}`;
        btn.dataset.orderId = String(order.id);
        btn.dataset.targetStatus = act.status;
        btn.textContent = act.label;
        actionsDiv.appendChild(btn);
      }
    } else if (state.user.role === "CUSTOMER" && order.status === "RECEIVED") {
      const cancelBtn = document.createElement("button");
      cancelBtn.type = "button";
      cancelBtn.className = "btn btn-sm btn-danger";
      cancelBtn.dataset.orderId = String(order.id);
      cancelBtn.dataset.targetStatus = "CANCELLED";
      cancelBtn.textContent = "Cancelar mi pedido";
      actionsDiv.appendChild(cancelBtn);
    }

    if (actionsDiv.childElementCount > 0) {
      card.appendChild(actionsDiv);
    }

    const details = document.createElement("details");
    details.className = "history-details";
    const summary = document.createElement("summary");
    summary.textContent = `Historial de auditoría (${(order.status_history || []).length} eventos)`;
    details.appendChild(summary);

    const histUl = document.createElement("ul");
    for (const h of order.status_history || []) {
      const hLi = document.createElement("li");
      const fromText = h.from_status ? `${STATUS_LABELS[h.from_status] || h.from_status} -> ` : "";
      const toText = STATUS_LABELS[h.to_status] || h.to_status;
      const timeText = new Date(h.changed_at).toLocaleTimeString();
      const commentText = h.comment ? ` (${h.comment})` : "";
      hLi.textContent = `[${timeText}] ${fromText}${toText} · Usuario #${h.changed_by_user_id}${commentText}`;
      histUl.appendChild(hLi);
    }
    details.appendChild(histUl);
    card.appendChild(details);

    ordersListEl.appendChild(card);
  }
}

async function loadCatalogForSelectedStore() {
  const storeId = Number(storeSelect.value);
  if (!storeId) return;

  state.products = await api.listProducts(storeId);
  state.cart = {};
  renderCatalog();
  updateCartTotal();
}

function renderCatalog() {
  catalogList.replaceChildren();
  for (const prod of state.products) {
    const row = document.createElement("div");
    row.className = "catalog-item";

    const info = document.createElement("div");
    info.className = "catalog-item-info";
    const nameEl = document.createElement("strong");
    nameEl.textContent = `${prod.name} ($${prod.price})`;
    const descEl = document.createElement("span");
    descEl.textContent = prod.description || "";
    info.append(nameEl, descEl);

    const controls = document.createElement("div");
    controls.className = "qty-controls";

    const minusBtn = document.createElement("button");
    minusBtn.type = "button";
    minusBtn.className = "qty-btn";
    minusBtn.dataset.productId = String(prod.id);
    minusBtn.dataset.delta = "-1";
    minusBtn.textContent = "-";

    const qtySpan = document.createElement("span");
    qtySpan.className = "qty-value";
    qtySpan.id = `qty-prod-${prod.id}`;
    qtySpan.textContent = String(state.cart[prod.id] || 0);

    const plusBtn = document.createElement("button");
    plusBtn.type = "button";
    plusBtn.className = "qty-btn";
    plusBtn.dataset.productId = String(prod.id);
    plusBtn.dataset.delta = "1";
    plusBtn.textContent = "+";

    controls.append(minusBtn, qtySpan, plusBtn);
    row.append(info, controls);
    catalogList.appendChild(row);
  }
}

function updateCartTotal() {
  let total = 0;
  for (const prod of state.products) {
    const qty = state.cart[prod.id] || 0;
    if (qty > 0) {
      total += Number(prod.price) * qty;
    }
  }
  cartTotalLabel.textContent = `$${total.toFixed(2)}`;
}

async function initializeAuthenticatedWorkspace(user, token) {
  state.user = user;
  userNameLabel.textContent = user.full_name;
  userRoleBadge.textContent = user.role;

  authSection.hidden = true;
  workspaceSection.hidden = false;
  sessionBar.hidden = false;

  state.stores = await api.listStores();

  if (user.role === "CUSTOMER") {
    customerOrderPanel.hidden = false;
    staffInfoPanel.hidden = false;
    adminStoreFilterBox.hidden = true;
    staffScopeDescription.textContent =
      "Estás en tu canal personal. Solo recibes eventos de tus propios pedidos.";

    storeSelect.replaceChildren();
    for (const st of state.stores) {
      const opt = document.createElement("option");
      opt.value = String(st.id);
      opt.textContent = `${st.name} (${st.address})`;
      storeSelect.appendChild(opt);
    }
    await loadCatalogForSelectedStore();
  } else if (user.role === "OPERATOR") {
    customerOrderPanel.hidden = true;
    staffInfoPanel.hidden = false;
    adminStoreFilterBox.hidden = true;
    staffScopeDescription.textContent = `Operador asignado a ${getStoreName(
      user.store_id
    )}. Recibes en tiempo real todos los pedidos de tu sucursal.`;
  } else if (user.role === "ADMIN") {
    customerOrderPanel.hidden = true;
    staffInfoPanel.hidden = false;
    adminStoreFilterBox.hidden = false;
    staffScopeDescription.textContent =
      "Acceso global de Administrador. Recibes eventos de todas las sucursales en tiempo real.";

    adminStoreFilter.replaceChildren();
    const allOpt = document.createElement("option");
    allOpt.value = "";
    allOpt.textContent = "Todas las tiendas (Global)";
    adminStoreFilter.appendChild(allOpt);
    for (const st of state.stores) {
      const opt = document.createElement("option");
      opt.value = String(st.id);
      opt.textContent = st.name;
      adminStoreFilter.appendChild(opt);
    }
  }

  await Promise.all([resyncOrdersFromREST(), loadNotificationsFromREST()]);
  wsClient.connect(token);
}

// Eventos de UI (Delegación de eventos sin inline handlers)
demoButtonsGrid.addEventListener("click", (e) => {
  const btn = e.target.closest("button[data-email]");
  if (!btn) return;
  loginEmail.value = btn.dataset.email;
  loginPassword.value = btn.dataset.pass;
  loginForm.requestSubmit();
});

loginForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  loginError.hidden = true;
  loginSubmitBtn.disabled = true;

  try {
    const res = await api.login(loginEmail.value, loginPassword.value);
    api.setToken(res.access_token);
    await initializeAuthenticatedWorkspace(res.user, res.access_token);
  } catch (err) {
    loginError.textContent = err.message;
    loginError.hidden = false;
  } finally {
    loginSubmitBtn.disabled = false;
  }
});

storeSelect.addEventListener("change", () => {
  loadCatalogForSelectedStore();
});

catalogList.addEventListener("click", (e) => {
  const btn = e.target.closest("button.qty-btn");
  if (!btn) return;
  const prodId = Number(btn.dataset.productId);
  const delta = Number(btn.dataset.delta);
  const current = state.cart[prodId] || 0;
  const next = Math.max(0, Math.min(50, current + delta));
  state.cart[prodId] = next;

  const span = document.getElementById(`qty-prod-${prodId}`);
  if (span) span.textContent = String(next);
  updateCartTotal();
});

createOrderForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  orderFormError.hidden = true;

  const items = Object.entries(state.cart)
    .filter(([, qty]) => qty > 0)
    .map(([prodId, qty]) => ({
      product_id: Number(prodId),
      quantity: Number(qty),
    }));

  if (items.length === 0) {
    orderFormError.textContent = "Agrega al menos un producto al pedido.";
    orderFormError.hidden = false;
    return;
  }

  createOrderSubmit.disabled = true;
  try {
    const created = await api.createOrder({
      store_id: Number(storeSelect.value),
      notes: orderNotes.value.trim() || null,
      items,
    });
    upsertOrderInMemory(created, true);
    state.cart = {};
    orderNotes.value = "";
    renderCatalog();
    updateCartTotal();
  } catch (err) {
    orderFormError.textContent = err.message;
    orderFormError.hidden = false;
  } finally {
    createOrderSubmit.disabled = false;
  }
});

ordersListEl.addEventListener("click", async (e) => {
  const btn = e.target.closest("button[data-order-id][data-target-status]");
  if (!btn) return;

  const orderId = Number(btn.dataset.orderId);
  const targetStatus = btn.dataset.targetStatus;
  btn.disabled = true;

  try {
    await api.updateOrderStatus(
      orderId,
      targetStatus,
      `Cambio a ${targetStatus} desde panel en vivo`
    );
  } catch (err) {
    showToast("Error al actualizar estado", err.message);
    btn.disabled = false;
  }
});

notificationsListEl.addEventListener("click", async (e) => {
  const btn = e.target.closest("button[data-notif-id]");
  if (!btn) return;

  const notifId = Number(btn.dataset.notifId);
  btn.disabled = true;
  try {
    await api.markNotificationRead(notifId);
    const target = state.notifications.find((n) => n.id === notifId);
    if (target && !target.is_read) {
      target.is_read = true;
      state.unreadCount = Math.max(0, state.unreadCount - 1);
    }
    renderNotifications();
  } catch (err) {
    showToast("Error", err.message);
    btn.disabled = false;
  }
});

btnMarkAllRead.addEventListener("click", async () => {
  if (state.unreadCount === 0) return;
  btnMarkAllRead.disabled = true;
  try {
    await api.markAllNotificationsRead();
    for (const n of state.notifications) {
      n.is_read = TrueBoolean();
    }
    state.unreadCount = 0;
    renderNotifications();
  } catch (err) {
    showToast("Error", err.message);
  } finally {
    btnMarkAllRead.disabled = false;
  }
});

function TrueBoolean() {
  return true;
}

btnToggleNotifications.addEventListener("click", () => {
  const isHidden = notificationsPanel.hidden;
  notificationsPanel.hidden = !isHidden;
  btnToggleNotifications.setAttribute("aria-expanded", String(isHidden));
});

adminStoreFilter.addEventListener("change", async () => {
  state.selectedAdminStoreId = adminStoreFilter.value;
  if (state.selectedAdminStoreId) {
    wsClient.send({
      type: "subscribe_store",
      store_id: Number(state.selectedAdminStoreId),
    });
  }
  await resyncOrdersFromREST();
});

document.getElementById("btn-manual-resync").addEventListener("click", () => {
  resyncOrdersFromREST();
  loadNotificationsFromREST();
});

document.getElementById("btn-simulate-drop").addEventListener("click", () => {
  wsClient.simulateNetworkDrop();
});

document.getElementById("btn-clear-ws-log").addEventListener("click", () => {
  wsLogBox.textContent = "";
});

document.getElementById("btn-logout").addEventListener("click", () => {
  wsClient.disconnect();
  api.setToken(null);
  state.user = null;
  state.orders.clear();
  state.notifications = [];
  state.unreadCount = 0;
  workspaceSection.hidden = true;
  sessionBar.hidden = true;
  authSection.hidden = false;
});

// Auto-restaurar sesión si hay un JWT en sessionStorage de esta pestaña
(async function restoreSessionIfPresent() {
  if (!api.token) return;
  try {
    const me = await api.getMe();
    await initializeAuthenticatedWorkspace(me, api.token);
  } catch {
    api.setToken(null);
  }
})();
