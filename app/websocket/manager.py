"""ConnectionManager para gestionar conexiones WebSocket, salas aisladas y broadcast."""

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from fastapi import WebSocket
from starlette.websockets import WebSocketState

from app.models.user import UserRole
from app.schemas.ws_events import WSEnvelope, WSServerEventType


@dataclass(eq=False)
class ClientConnection:
    """Representa una conexión WebSocket autenticada con su contexto de seguridad."""

    websocket: WebSocket
    user_id: int
    role: UserRole
    store_id: int | None
    rooms: set[str] = field(default_factory=set)


class ConnectionManager:
    """Gestiona el ciclo de vida de conexiones WebSocket, membresía en salas y difusión (broadcast)."""

    def __init__(self) -> None:
        # Mapa de nombre de sala -> conjunto de conexiones suscritas
        self._rooms: dict[str, set[ClientConnection]] = defaultdict(set)
        # Conjunto global de conexiones activas
        self._connections: set[ClientConnection] = set()

    @staticmethod
    def user_room(user_id: int) -> str:
        """Nombre canónico de la sala privada de un usuario."""
        return f"user:{user_id}"

    @staticmethod
    def store_room(store_id: int) -> str:
        """Nombre canónico de la sala de una tienda específica."""
        return f"store:{store_id}"

    @staticmethod
    def admin_room() -> str:
        """Nombre canónico de la sala global de administradores."""
        return "admin:global"

    def register(
        self,
        websocket: WebSocket,
        *,
        user_id: int,
        role: UserRole,
        store_id: int | None,
    ) -> ClientConnection:
        """Registra una conexión ya autenticada y la suscribe a las salas que le corresponden por rol."""
        conn = ClientConnection(
            websocket=websocket,
            user_id=user_id,
            role=role,
            store_id=store_id,
        )
        self._connections.add(conn)

        # 1. Todo usuario autenticado se une a su canal personal
        self.join_room(conn, self.user_room(user_id))

        # 2. Si es OPERADOR con tienda asignada, se une automáticamente al canal de SU tienda
        if role == UserRole.OPERATOR and store_id is not None:
            self.join_room(conn, self.store_room(store_id))

        # 3. Si es ADMIN, se une al canal global de administración
        if role == UserRole.ADMIN:
            self.join_room(conn, self.admin_room())

        return conn

    def join_room(self, conn: ClientConnection, room: str) -> None:
        """Suscribe una conexión a una sala específica."""
        conn.rooms.add(room)
        self._rooms[room].add(conn)

    def leave_room(self, conn: ClientConnection, room: str) -> None:
        """Elimina la suscripción de una conexión a una sala."""
        conn.rooms.discard(room)
        if room in self._rooms:
            self._rooms[room].discard(conn)
            if not self._rooms[room]:
                del self._rooms[room]

    def disconnect(self, conn: ClientConnection | None) -> None:
        """Limpia todas las suscripciones de una conexión al desconectarse."""
        if conn is None:
            return
        for room in list(conn.rooms):
            self.leave_room(conn, room)
        self._connections.discard(conn)

    async def send_personal_event(
        self,
        conn: ClientConnection,
        event: WSServerEventType,
        data: dict[str, Any],
        room: str | None = None,
    ) -> bool:
        """Envía un sobre JSON tipado y validado con Pydantic a una única conexión."""
        envelope = WSEnvelope(event=event, room=room, data=data)
        payload = envelope.model_dump(mode="json")
        try:
            if conn.websocket.client_state == WebSocketState.CONNECTED:
                await conn.websocket.send_json(payload)
                return True
        except Exception:
            # Si el socket se cerró abruptamente, limpiamos la conexión muerta
            self.disconnect(conn)
        return False

    async def broadcast_to_room(
        self,
        room: str,
        event: WSServerEventType,
        data: dict[str, Any],
    ) -> int:
        """Difunde un evento a todos los clientes conectados a una sala específica.

        Retorna la cantidad de conexiones que recibieron el mensaje exitosamente.
        """
        return await self.broadcast_to_rooms([room], event=event, data=data)

    async def broadcast_to_rooms(
        self,
        rooms: list[str],
        event: WSServerEventType,
        data: dict[str, Any],
    ) -> int:
        """Difunde un evento a múltiples salas deduplicando conexiones.

        Si un usuario (por ejemplo un Admin) está suscrito simultáneamente a
        'store:1' y 'admin:global', solo recibe el evento una vez.
        """
        targets: dict[ClientConnection, str] = {}
        for room in rooms:
            for conn in list(self._rooms.get(room, set())):
                if conn not in targets:
                    targets[conn] = room

        delivered = 0
        for conn, matched_room in targets.items():
            ok = await self.send_personal_event(
                conn,
                event=event,
                data=data,
                room=matched_room,
            )
            if ok:
                delivered += 1
        return delivered

    @property
    def active_connections_count(self) -> int:
        """Cantidad total de sockets activos actualmente."""
        return len(self._connections)


# Instancia global compartida por routers REST y WebSockets
ws_manager = ConnectionManager()
