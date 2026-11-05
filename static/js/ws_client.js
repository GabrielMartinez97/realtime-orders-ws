/**
 * Cliente WebSocket con:
 * 1. Autenticación por primer mensaje JSON ({"type": "auth", "token": ...}).
 * 2. Heartbeat activo cada 15s (ping/pong) con medición de latencia RTT.
 * 3. Reconexión automática con Backoff Exponencial + Jitter.
 * 4. Disparo de resincronización REST automática tras recuperar la conexión.
 */

export class RealtimeWSClient {
  constructor({ onEvent, onStatusChange, onReconnectResync, onWireLog }) {
    this.onEvent = onEvent;
    this.onStatusChange = onStatusChange;
    this.onReconnectResync = onReconnectResync;
    this.onWireLog = onWireLog;

    this.ws = null;
    this.token = null;
    this.shouldReconnect = false;
    this.reconnectAttempts = 0;
    this.hasConnectedOnce = false;
    this.heartbeatTimer = null;
    this.reconnectTimer = null;
  }

  connect(token) {
    this.token = token;
    this.shouldReconnect = true;
    this._openSocket();
  }

  disconnect() {
    this.shouldReconnect = false;
    this.hasConnectedOnce = false;
    this.reconnectAttempts = 0;
    this._clearTimers();
    if (this.ws) {
      this.ws.close(1000, "Cierre de sesión por el usuario");
      this.ws = null;
    }
    this.onStatusChange({ state: "disconnected", latencyMs: null });
  }

  /**
   * Permite simular una caída abrupta de red desde la UI para demostrar
   * cómo entra en acción el Backoff Exponencial y la resincronización REST.
   */
  simulateNetworkDrop() {
    if (this.ws) {
      this.onWireLog("SIMULACIÓN", { info: "Cerrando socket para probar reconexión y resync REST..." });
      this.ws.close(4000, "Caída de red simulada");
    }
  }

  send(payload) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.onWireLog("ENVIADO ->", payload);
      this.ws.send(JSON.stringify(payload));
    }
  }

  _openSocket() {
    this._clearTimers();
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${protocol}//${window.location.host}/ws`;

    this.ws = new WebSocket(wsUrl);

    this.ws.addEventListener("open", () => {
      // Enviamos el JWT en el primer mensaje para no exponerlo en la URL
      this.send({ type: "auth", token: this.token });
      this._startHeartbeat();
    });

    this.ws.addEventListener("message", (event) => {
      try {
        const envelope = JSON.parse(event.data);
        this.onWireLog("<- RECIBIDO", envelope);

        if (envelope.event === "connection_established") {
          const isReconnect = this.hasConnectedOnce;
          this.hasConnectedOnce = true;
          this.reconnectAttempts = 0;
          this.onStatusChange({
            state: "connected",
            latencyMs: null,
            rooms: envelope.data.rooms || [],
          });

          if (isReconnect && typeof this.onReconnectResync === "function") {
            this.onReconnectResync();
          }
        } else if (envelope.event === "pong") {
          const sentAt = envelope.data?.client_timestamp;
          const rtt = sentAt ? Math.max(1, Date.now() - sentAt) : null;
          this.onStatusChange({ state: "connected", latencyMs: rtt });
        }

        this.onEvent(envelope);
      } catch (err) {
        console.error("Error procesando trama WS:", err);
      }
    });

    this.ws.addEventListener("close", () => {
      this._clearTimers();
      if (!this.shouldReconnect) {
        this.onStatusChange({ state: "disconnected", latencyMs: null });
        return;
      }
      this._scheduleReconnect();
    });
  }

  _startHeartbeat() {
    this.heartbeatTimer = window.setInterval(() => {
      this.send({ type: "ping", client_timestamp: Date.now() });
    }, 15000);
  }

  _scheduleReconnect() {
    this.reconnectAttempts += 1;
    // Backoff exponencial: base 1000ms * 2^(intento-1), tope 30s + jitter aleatorio (0-400ms)
    const expDelay = Math.min(30000, 1000 * Math.pow(2, this.reconnectAttempts - 1));
    const jitter = Math.floor(Math.random() * 400);
    const delayMs = expDelay + jitter;

    this.onStatusChange({
      state: "reconnecting",
      attempt: this.reconnectAttempts,
      delayMs,
    });

    this.reconnectTimer = window.setTimeout(() => {
      if (this.shouldReconnect) {
        this._openSocket();
      }
    }, delayMs);
  }

  _clearTimers() {
    if (this.heartbeatTimer) {
      clearInterval(this.heartbeatTimer);
      this.heartbeatTimer = null;
    }
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
  }
}
