# Guía Acumulativa de Preguntas de Práctica y Entrevista Técnica

Este documento recopila todas las preguntas de verificación trabajadas en cada fase del proyecto junto con sus respuestas de nivel **Senior Software Engineer** para estudiar antes de una entrevista técnica.

---

## Fase 1: Modelo de Datos, Seguridad Financiera, RBAC y Anti-IDOR

### Pregunta 1.1: ¿Por qué en `OrderItemCreate` solo recibimos `product_id` y `quantity` (sin el precio), y por qué en la tabla `order_items` guardamos `unit_price_snapshot` además de la llave foránea `product_id`?
- **Seguridad (Zero Trust en el Cliente):** Jamás aceptamos precios ni totales calculados desde el navegador porque cualquier usuario puede modificar el JSON con las DevTools (F12) o un proxy y enviar `"price": 0.01`. El backend solo recibe qué producto y cuántas unidades quiere el cliente, consulta el precio real vigente en la tabla `products` y calcula el total en el servidor usando `Decimal` (para evitar errores de coma flotante IEEE 754).
- **Integridad Contable Histórica (Patrón Snapshot):** Si solo guardáramos `product_id` y calculáramos el total haciendo `JOIN` con `products.price`, el día que el Administrador suba el precio de un producto de `$12.50` a `$20.00`, todos los pedidos históricos de meses anteriores cambiarían su total contable retroactivamente. Al guardar `unit_price_snapshot` y `product_name_snapshot`, congelamos las condiciones exactas de la venta.

### Pregunta 1.2: ¿Cuál es la diferencia entre RBAC e IDOR en el endpoint `PATCH /api/orders/{order_id}/status`?
- **RBAC (*Role-Based Access Control*):** Valida si el **rol** del usuario tiene permiso para ejecutar la operación en general (por ejemplo, verificar que `user.role == OPERATOR`).
- **Anti-IDOR (*Insecure Direct Object Reference* / Autorización a nivel de objeto):** Incluso si el usuario tiene el rol `OPERATOR`, debemos validar que ese pedido específico pertenezca a **su** tienda (`actor.store_id == order.store_id`). Si omitimos esta validación, el operador de la Sucursal Norte (`store_id = 2`) podría iterar sobre los IDs de pedidos (`1, 2, 3...`) y cancelar o modificar pedidos de la Sucursal Centro (`store_id = 1`).

---

## Fase 2: Motor WebSocket, Handshake, Salas y Broadcast

### Pregunta 2.1: ¿Por qué autenticamos el WebSocket enviando el JWT en el primer mensaje JSON (`{"type": "auth", "token": "..."}`) o por query param, en vez de usar la cabecera `Authorization: Bearer` como en la API REST?
- Porque la API estándar `new WebSocket(url)` de los navegadores web **no permite definir cabeceras HTTP personalizadas** (a diferencia de `fetch()`, que sí acepta un objeto `headers`).
- Enviar el JWT como **primer mensaje JSON una vez abierto el túnel WebSocket** tiene además una ventaja de seguridad importante frente al query param (`?token=...`): el token viaja dentro del payload del WebSocket y no queda expuesto en la URL dentro de los logs de acceso de servidores proxy (Nginx, Cloudflare, etc.).

### Pregunta 2.2: Cuando una cliente (Ana, `user_id = 4`) crea un pedido en la Sucursal Centro (`store_id = 1`), ¿a qué salas debemos emitir el evento y por qué es necesaria la deduplicación en `broadcast_to_rooms`?
- Se emite a las 3 salas: `["user:4", "store:1", "admin:global"]`.
  - `"user:4"`: para que la propia cliente vea su pedido y cambios en tiempo real.
  - `"store:1"`: para que todos los operadores asignados a la Sucursal Centro lo reciban al instante, sin que la Sucursal Norte (`"store:2"`) reciba tráfico que no le corresponde.
  - `"admin:global"`: para el monitoreo y dashboard global de los administradores.
- **Deduplicación:** Si un Administrador está en `"admin:global"` y además se suscribió manualmente a `"store:1"`, su conexión aparece en ambos conjuntos. Nuestro método `broadcast_to_rooms` agrupa las conexiones en un diccionario único antes de enviar para que el Administrador reciba el evento **una sola vez**.

---

## Fase 3: Flujo de Pedidos en Vivo, Backoff Exponencial y Resincronización REST

### Pregunta 3.1: ¿Por qué al reconectar un WebSocket usamos "Backoff Exponencial con Jitter" en vez de reintentar cada 1 segundo fijo?
- Si el servidor se reinicia o hay un microcorte de red cuando hay 5.000 clientes conectados y todos reintentan exactamente cada 1 segundo fijo, los 5.000 clientes golpearán al servidor en el mismo milisegundo provocando una avalancha de peticiones (**Thundering Herd Problem** / autodenegación de servicio).
- El **Backoff Exponencial** (`1s, 2s, 4s, 8s, 16s...` hasta un tope de `30s`) espacia los reintentos progresivamente, y el **Jitter** (sumar unos milisegundos aleatorios entre `0` y `400ms`) desincroniza a los clientes para que las reconexiones lleguen distribuidas de forma suave.

### Pregunta 3.2: ¿Por qué el cliente debe llamar a `GET /api/orders` (API REST) automáticamente justo después de reconectar el WebSocket?
- Porque los WebSockets en memoria **no guardan cola de mensajes históricos** para clientes desconectados. Si el cliente estuvo sin señal durante 8 segundos y en ese lapso el operador cambió el pedido de `PREPARING` a `READY`, ese evento WebSocket se emitió cuando el cliente no estaba conectado.
- Al ejecutar una **resincronización REST (`GET /api/orders`)** apenas se restablece el WebSocket (`isReconnect === true`), la interfaz obtiene la "fuente de la verdad" desde la base de datos y nunca queda con un estado desactualizado.
