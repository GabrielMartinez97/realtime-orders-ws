"""Rate Limiter en memoria basado en ventana deslizante (Sliding Window).

Protege endpoints sensibles como:
- Login (fuerza bruta de contraseñas)
- Creación de pedidos (spam / agotamiento de recursos)
"""

import time
from collections import defaultdict, deque
from threading import Lock
from fastapi import HTTPException, Request, status


class SlidingWindowRateLimiter:
    """Implementa un limitador de tasa por clave (IP o usuario) en una ventana de tiempo."""

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def check(self, key: str, max_requests: int, window_seconds: int = 60) -> None:
        """Verifica si la clave excede el límite dentro de la ventana y lanza HTTP 429 en caso afirmativo."""
        now = time.monotonic()
        cutoff = now - window_seconds

        with self._lock:
            queue = self._hits[key]
            # Limpiamos timestamps antiguos fuera de la ventana deslizante
            while queue and queue[0] <= cutoff:
                queue.popleft()

            if len(queue) >= max_requests:
                retry_after = max(1, int(window_seconds - (now - queue[0])))
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"Demasiadas solicitudes. Intenta nuevamente en {retry_after} segundos.",
                    headers={"Retry-After": str(retry_after)},
                )

            queue.append(now)

    def reset(self) -> None:
        """Limpia el estado del limitador (útil para aislamiento entre pruebas en pytest)."""
        with self._lock:
            self._hits.clear()


rate_limiter = SlidingWindowRateLimiter()


def get_client_ip(request: Request) -> str:
    """Obtiene la IP del cliente desde la conexión directa."""
    if request.client and request.client.host:
        return request.client.host
    return "unknown"
