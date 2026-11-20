"""API HTTP del servidor de grupo: API local (libre, para el cliente) + API de federación (/fed/*)."""
import json
import logging
import re
import signal
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from . import config
from .clock import LamportClock
from .db import Database, utc_now
from .federation import Federation

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("server")

db: Database
clock: LamportClock
fed: Federation
NOMBRE_VALIDO = re.compile(r"[a-z0-9_.-]{1,32}")
MAX_CUERPO = 1_000_000


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):   # silenciar el log de accesos por defecto
        pass

    # ---- utilidades ----
    def _json_in(self):
        largo = int(self.headers.get("Content-Length") or 0)
        if largo > MAX_CUERPO:
            raise ValueError("cuerpo demasiado grande")
        crudo = self.rfile.read(largo) if largo else b""
        return json.loads(crudo) if crudo else None

    def _out(self, status: int, obj) -> None:
        cuerpo = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    def _despachar(self, rutas) -> None:
        url = urlsplit(self.path)
        manejador = rutas.get(url.path)
        if manejador is None:
            return self._out(404, {"error": "ruta no encontrada"})
        try:
            manejador(parse_qs(url.query))
        except (ValueError, json.JSONDecodeError) as e:
            self._out(400, {"error": f"JSON inválido: {e}"})
        except Exception:                                  # noqa: BLE001
            log.exception("ERROR interno en %s", self.path)
            self._out(500, {"error": "error interno"})

    def do_GET(self):
        self._despachar({
            "/health": self.h_health, "/status": self.h_status, "/users": self.h_users_get,
            "/messages": self.h_messages_get, "/fed/health": self.h_fed_health,
        })

    def do_POST(self):
        self._despachar({
            "/users": self.h_users_post, "/messages": self.h_messages_post,
            "/fed/messages": self.h_fed_messages,
        })

    # ---- API local (libre) ----
    def h_health(self, _q):
        self._out(200, {"status": "ok"})

    def h_status(self, _q):
        self._out(200, {"server": config.GROUP_NAME, "lamport": clock.value, "central_up": fed.central_up,
                        "pending": db.pending_count(), "users": len(db.list_users()),
                        "messages": db.count_messages()})

    def h_users_get(self, _q):
        self._out(200, {"users": db.list_users()})

    def h_users_post(self, _q):
        cuerpo = self._json_in()
        nombre = str((cuerpo or {}).get("name", "")).strip().lower().split("@")[0]
        if not NOMBRE_VALIDO.fullmatch(nombre):
            return self._out(400, {"error": "nombre inválido (a-z, 0-9, _ . -, máx. 32)"})
        completo = f"{nombre}@{config.GROUP_NAME}"
        if not db.create_user(completo):
            return self._out(409, {"error": "el usuario ya existe", "user": completo})
        log.info("USER created user=%s", completo)
        self._out(201, {"user": completo})

    def h_messages_post(self, _q):
        cuerpo = self._json_in() or {}
        remitente = str(cuerpo.get("from", "")).strip()
        texto = str(cuerpo.get("body", "")).strip()
        if remitente and "@" not in remitente:
            remitente += f"@{config.GROUP_NAME}"
        if not remitente.endswith(f"@{config.GROUP_NAME}"):
            return self._out(403, {"error": f"solo usuarios @{config.GROUP_NAME} pueden escribir aquí"})
        if not db.has_user(remitente):
            return self._out(404, {"error": "usuario desconocido"})
        if not texto or len(texto) > 4000:
            return self._out(400, {"error": "el mensaje debe tener entre 1 y 4000 caracteres"})
        mensaje = {
            "id": str(uuid.uuid4()),          # UUID: identidad estable, clave de deduplicación
            "from": remitente,
            "origin": config.GROUP_NAME,
            "lamport": clock.tick(),          # regla de envío: incrementar antes de enviar
            "sent_at": utc_now(),             # informativo; nunca se usa para ordenar
            "body": texto,
        }
        db.add_local_message(mensaje)         # guarda + encola en una transacción
        fed.notify_outbound()
        log.info("LOCAL id=%s from=%s lamport=%d", mensaje["id"], remitente, mensaje["lamport"])
        self._out(201, mensaje)

    def h_messages_get(self, q):
        since = int(q["since"][0]) if "since" in q else None
        self._out(200, {"server": config.GROUP_NAME, "messages": db.list_messages(since)})

    # ---- API de federación (la fija la especificación) ----
    def h_fed_health(self, _q):
        self._out(200, {"server": config.GROUP_NAME, "lamport": clock.value})

    def h_fed_messages(self, _q):
        resultado = fed.ingest(self._json_in(), source="federation")
        if resultado.startswith("invalid:"):
            return self._out(400, {"error": resultado[8:]})       # 4xx: el central no reintenta
        self._out(200, {"status": resultado})                     # duplicado también es 200 (idempotente)


def main() -> None:
    global db, clock, fed
    db = Database(config.DB_PATH)
    clock = LamportClock()
    clock.restore(db.max_lamport())
    fed = Federation(db, clock)
    log.info("START server=%s url=%s central=%s clock=%d db=%s",
             config.GROUP_NAME, config.PUBLIC_URL, config.CENTRAL_URL, clock.value, config.DB_PATH)
    fed.start()
    servidor = ThreadingHTTPServer((config.HOST, config.PORT), Handler)
    servidor.daemon_threads = True
    # docker stop envía SIGTERM: cerrar ordenadamente (si no, Docker espera 10 s y mata el proceso)
    signal.signal(signal.SIGTERM, lambda *_: threading.Thread(target=servidor.shutdown).start())
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        fed.stop()
        log.info("STOP server=%s", config.GROUP_NAME)


if __name__ == "__main__":
    main()
