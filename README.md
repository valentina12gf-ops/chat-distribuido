# Chat distribuido entre grupos — Sistemas Distribuidos (UIS · EISI)

Servidor de chat en contenedores que se registra en el servidor central del curso y
participa en la sala global `#general`. Integrantes: **Marly Riaño** y **Carol Gutiérrez**.

Implementado en **Python 3.12 con solo la biblioteca estándar** (http.server, sqlite3,
threading, urllib): no hay dependencias que instalar y todo el código se puede leer y explicar.

## Levantar el sistema en un equipo limpio

Requisitos: Docker y Docker Compose.

```bash
cp .env.example .env     # editar GROUP_NAME, PUBLIC_URL y CENTRAL_URL
docker compose up --build
```

El servidor queda en `http://localhost:${PORT}` (8000 por defecto).

### Pruebas locales sin el servidor central del profesor

```bash
docker compose --profile local up --build -d
# servidor del grupo (gN):   http://localhost:8000
# segundo servidor (gNb):    http://localhost:8001
# central simulado:          http://localhost:9000
```

### Prueba automática SIN Docker

```bash
python3 tests/prueba_local.py
```

Levanta el central simulado y dos servidores como procesos y verifica registro, entrega,
orden de Lamport, deduplicación, persistencia, reintentos, caída del central y recuperación
de historial (30+ comprobaciones).

## Cliente

```bash
python3 client/chat_client.py --server http://localhost:8000 --user ana
```

Crea el usuario si no existe, muestra el historial ordenado por `(lamport, origin)` y
envía lo que escribas. Los usuarios de otros grupos salen en amarillo con `[otro grupo: gX]`.

## Variables de entorno

| Variable | Por defecto | Significado |
| --- | --- | --- |
| `GROUP_NAME` | (obligatoria) | Nombre corto del servidor: `g1`, `g2`, … |
| `PUBLIC_URL` | (obligatoria) | URL con la que el central alcanza este servidor. |
| `CENTRAL_URL` | (obligatoria) | URL del servidor central. Nunca está escrita en el código. |
| `PORT` | `8000` | Puerto publicado en el equipo. |
| `DB_PATH` | `/data/chat.db` | Base SQLite (en un volumen). |
| `REGISTER_INTERVAL` | `30` | Segundos entre renovaciones de registro. |
| `HEARTBEAT_INTERVAL` | `5` | Segundos entre `GET /health` al central. |
| `HEARTBEAT_MAX_FAILS` | `3` | Fallos seguidos para marcar el central como caído. |
| `RETRY_BASE_SECONDS` | `0.5` | Base del backoff exponencial. |
| `RETRY_MAX_SECONDS` | `30` | Tope del backoff. |
| `REQUEST_TIMEOUT` | `5` | Timeout de cada petición saliente. |
| `HISTORY_OVERLAP` | `10` | Solape (en lamport) al pedir `/history`; los repetidos se descartan por id. |
| `HISTORY_SYNC_INTERVAL` | `30` | Cada cuántos s se reconcilia el historial con el central (0 = nunca). |

## Decisiones de diseño

- **SQLite en volumen** (`server-data`): usuarios, historial y cola de salida sobreviven a `docker compose restart`.
- **Lamport**: `tick()` antes de enviar; `observe(r) = max(local, r) + 1` al recibir; al arrancar se restaura con el mayor lamport guardado. `sent_at` es solo informativo.
- **Deduplicación por `id` (UUID)**: `messages.id` es clave primaria y se inserta con `INSERT OR IGNORE`; un `id` repetido responde `200` sin efectos (idempotencia) y deja `DUP` en el log.
- **Cola de salida persistente (`pending`)**: el mensaje local y su entrada en la cola se guardan en **una sola transacción**. El envío reintenta con backoff exponencial (`0.5·2^(n-1)`, tope 30 s) ante 5xx o falta de respuesta; los 4xx no se reintentan (`DROP`).
- **Heartbeat**: `GET /health` cada 5 s; tras 3 fallos seguidos → `CENTRAL_DOWN` y los mensajes quedan en `pending`. Al volver → `CENTRAL_UP`, se vuelve a registrar (el central pudo perder el registro), se recupera historial y se vacía la cola.
- **Recuperación de historial**: `GET /history?since=N`, con N = mayor lamport de mensajes *ajenos* − solape. Se usa el lamport de mensajes ajenos y no el máximo propio porque los mensajes escritos durante una caída suben nuestro reloj y haría saltarnos los ajenos perdidos. Además hay una reconciliación periódica silenciosa.
- **Logs**: cada evento deja rastro con `id` y `lamport`: `START LOCAL SENT RECV RETRY DROP DUP REGISTER HEARTBEAT CENTRAL_UP CENTRAL_DOWN HISTORY`.

## Endpoints

API local (libre, la usa el cliente):

| Método y ruta | Propósito |
| --- | --- |
| `POST /users` | `{"name":"ana"}` → crea `ana@gN` (409 si existe). |
| `GET /users` | Lista de usuarios locales. |
| `POST /messages` | `{"from":"ana@gN","body":"..."}` → escribe en `#general`. |
| `GET /messages[?since=N]` | Historial ordenado por `(lamport, origin)`. |
| `GET /status` | Reloj, central arriba/abajo, pendientes, totales. |
| `GET /health` | Salud local (healthcheck de Docker). |

API de federación (la fija la especificación):

| Método y ruta | Propósito |
| --- | --- |
| `GET /fed/health` | `{"server":"gN","lamport":N}`. |
| `POST /fed/messages` | Recibe un reenvío del central; idempotente por `id`; campos desconocidos se ignoran; 400 si el formato es inválido. |
| (saliente) `POST /register`, `POST /messages`, `GET /history`, `GET /health` | Llamadas al servidor central. |

> **Importante:** la especificación OpenAPI oficial manda sobre este README. Antes de la
> sesión de interoperabilidad hay que correr el script de conformidad y ajustar cualquier
> diferencia de campos o códigos de respuesta.

## Experimento: pérdidas y tiempo de recuperación tras una caída

**Pregunta:** ¿cuántos mensajes se pierden o duplican cuando el servidor del grupo se cae
unos segundos, y cuánto tarda en ponerse al día al volver?

```bash
docker compose --profile local up --build -d
python3 experiment/medir_recuperacion.py --repeats 3 --count 20 --rate 5 --outage 10
# variar un parámetro (suma en la nota): repetir con --outage 5 y --outage 20
pip install matplotlib
python3 experiment/graficar.py experiment/datos/resultados.csv --out experiment/datos/grafica_poster.png
```

Sin Docker (para ensayar): añadir `--modo local`. Los datos de ensayo NO sirven para el póster:
hay que medir con Docker. Cada fila del CSV trae caída, tiempo de arranque, tiempo de
recuperación (s), perdidos y duplicados.

## Estructura

```
server/app/      config.py clock.py db.py federation.py main.py
mock_central/    central simulado (solo pruebas)
client/          chat_client.py
experiment/      medir_recuperacion.py graficar.py entorno_local.py datos/
tests/           prueba_local.py
docs/            arquitectura.md  diagrama_arquitectura.png  bitacora_interoperabilidad.md  plan_trabajo.md
```
