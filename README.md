# Sistema de Pedidos en Tiempo Real (`realtime-orders-ws`)

Proyecto de portafolio construido paso a paso con **Python 3.11+, FastAPI, WebSockets nativos, SQLAlchemy 2.0 y JavaScript puro**.

## Estado del Proyecto

- [x] **Fase 1:** Modelo de datos relacional (3FN), API REST, autenticación JWT, contraseñas con Bcrypt, Rate Limiting y control de acceso estricto por rol y por recurso (RBAC / Anti-IDOR).
- [ ] **Fase 2:** WebSocket básico (conexión autenticada, salas por tienda/usuario/admin y broadcast con `ConnectionManager`).
- [ ] **Fase 3:** Flujo de pedidos en vivo (creación, cambio de estado y recepción en tiempo real con reconexión y resincronización REST).
- [ ] **Fase 4:** Sistema de notificaciones en tiempo real y persistidas.
- [ ] **Fase 5:** Subida y descarga segura de archivos (validación de extensión, tamaño máximo 2 MB y *magic bytes*).
- [ ] **Fase 6:** Dashboard analítico en vivo con Chart.js.
- [ ] **Fase 7:** Suite completa de pruebas, guía de entrevista técnica y despliegue.
