/**
 * Cliente HTTP Fetch para la API REST con inyección automática del token JWT.
 */

export class ApiClient {
  constructor() {
    this.token = sessionStorage.getItem("jwt_token") || null;
  }

  setToken(token) {
    this.token = token;
    if (token) {
      sessionStorage.setItem("jwt_token", token);
    } else {
      sessionStorage.removeItem("jwt_token");
    }
  }

  async request(path, options = {}) {
    const headers = {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    };
    if (this.token) {
      headers["Authorization"] = `Bearer ${this.token}`;
    }

    const response = await fetch(path, {
      ...options,
      headers,
    });

    if (response.status === 204) {
      return null;
    }

    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const errorMsg = data.detail || `Error HTTP ${response.status}`;
      throw new Error(typeof errorMsg === "string" ? errorMsg : JSON.stringify(errorMsg));
    }
    return data;
  }

  login(email, password) {
    return this.request("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    });
  }

  getMe() {
    return this.request("/api/auth/me");
  }

  listStores() {
    return this.request("/api/stores");
  }

  listProducts(storeId) {
    const query = storeId ? `?store_id=${encodeURIComponent(storeId)}` : "";
    return this.request(`/api/products${query}`);
  }

  listOrders(storeId = null) {
    const query = storeId ? `?store_id=${encodeURIComponent(storeId)}` : "";
    return this.request(`/api/orders${query}`);
  }

  createOrder(payload) {
    return this.request("/api/orders", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }

  updateOrderStatus(orderId, status, comment = null) {
    return this.request(`/api/orders/${encodeURIComponent(orderId)}/status`, {
      method: "PATCH",
      body: JSON.stringify({ status, comment }),
    });
  }
}
