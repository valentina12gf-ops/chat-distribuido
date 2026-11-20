# Plan de trabajo — 2 integrantes

| Integrante | Responsabilidad principal | Archivos |
| --- | --- | --- |
| **Marly Riaño** — Sistema y conformidad | Despliegue y persistencia, script de conformidad, foro del curso, sesión de interoperabilidad, **federación y reloj de Lamport**. | `docker-compose.yml`, `.env.example`, `server/app/federation.py`, `server/app/clock.py`, `docs/salida_conformidad.txt`, `docs/bitacora_interoperabilidad.md` |
| **Carol Gutiérrez** — Servidor local, cliente y experimento | API local, base de datos, cliente, experimento, gráfica y póster, demo de fallo. | `server/app/main.py`, `server/app/db.py`, `server/app/config.py`, `client/chat_client.py`, `experiment/*`, `poster/` |

Ambas deben poder explicar **cualquier** línea del código (lo pregunta el profesor a cualquiera).

## Puntos de control
1. **Arranque:** ambas levantan `docker compose --profile local up --build`.
2. **Servidor local:** dos clientes conversan; el historial sobrevive a `docker compose restart server`.
3. **Central:** `python3 tests/prueba_local.py` en verde; script de conformidad del profesor pasa; salida guardada.
4. **Experimento:** CSV con ≥ 3 repeticiones y gráfica con unidades.
5. **Interoperabilidad y póster:** bitácora llena, póster en PDF, demo ensayada (≤ 10 min).
