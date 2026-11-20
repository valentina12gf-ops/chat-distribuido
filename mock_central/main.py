"""Servidor central SIMULADO, solo para pruebas locales. El real lo opera el profesor.
Guarda historial en memoria, reenvía a los servidores registrados (menos al origen)."""
import json
import logging
import os
import threading
import time
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s central %(message)s")
log = logging.getLogger("central")

REGISTRO: dict[str, str] = {}
MENSAJES: list[dict] = []
IDS: set[str] = set()
LOCK = threading.Lock()


def reenviar(nombre: str, url: str, msg: dict) -> None:
    for intento in (1, 2, 3):
        try:
            req = urllib.request.Request(f"{url}/fed/messages", data=json.dumps(msg).encode(), method="POST",
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=3) as r:
                if 200 <= r.status < 300:
                    log.info("FORWARDED id=%s to=%s attempt=%d", msg["id"], nombre, intento)
                    return
        except urllib.error.HTTPError as e:
            if 400 <= e.code < 500:
                log.warning("FORWARD rejected id=%s to=%s status=%d", msg["id"], nombre, e.code)
                return
        except (OSError, ValueError) as e:
            log.warning("FORWARD failed id=%s to=%s attempt=%d error=%s", msg["id"], nombre, intento, e)
        if intento < 3:
            time.sleep(intento)
    log.error("FORWARD gave up id=%s to=%s", msg["id"], nombre)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _out(self, status, obj):
        cuerpo = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    def _in(self):
        largo = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(largo)) if largo else None

    def do_GET(self):
        url = urlsplit(self.path)
        q = parse_qs(url.query)
        if url.path == "/health":
            return self._out(200, {"status": "ok"})
        if url.path == "/registry":
            return self._out(200, {"servers": REGISTRO, "messages": len(MENSAJES)})
        if url.path == "/history":
            since = int(q.get("since", ["0"])[0])
            with LOCK:
                lista = sorted((m for m in MENSAJES if m["lamport"] > since), key=lambda m: (m["lamport"], m["origin"]))
            return self._out(200, lista)
        self._out(404, {"error": "no encontrado"})

    def do_POST(self):
        url = urlsplit(self.path)
        try:
            cuerpo = self._in()
        except ValueError:
            return self._out(400, {"error": "JSON inválido"})
        if url.path == "/register":
            if not isinstance(cuerpo, dict) or not cuerpo.get("server") or not cuerpo.get("url"):
                return self._out(400, {"error": "faltan server/url"})
            REGISTRO[cuerpo["server"]] = cuerpo["url"]
            log.info("REGISTER server=%s url=%s total=%d", cuerpo["server"], cuerpo["url"], len(REGISTRO))
            return self._out(200, {"status": "registered"})
        if url.path == "/messages":
            campos = ("id", "from", "origin", "lamport", "body")
            if not isinstance(cuerpo, dict) or any(c not in cuerpo for c in campos):
                return self._out(400, {"error": "mensaje inválido"})
            with LOCK:
                if cuerpo["id"] in IDS:
                    log.info("DUP id=%s", cuerpo["id"])
                    return self._out(200, {"status": "duplicate"})
                IDS.add(cuerpo["id"])
                MENSAJES.append(cuerpo)
                destinos = {n: u for n, u in REGISTRO.items() if n != cuerpo["origin"]}
            log.info("STORED id=%s from=%s lamport=%s", cuerpo["id"], cuerpo["from"], cuerpo["lamport"])
            for n, u in destinos.items():
                threading.Thread(target=reenviar, args=(n, u, cuerpo), daemon=True).start()
            return self._out(200, {"status": "accepted"})
        self._out(404, {"error": "no encontrado"})


if __name__ == "__main__":
    puerto = int(os.environ.get("PORT", "9000"))
    s = ThreadingHTTPServer(("0.0.0.0", puerto), Handler)
    s.daemon_threads = True
    log.info("START puerto=%d", puerto)
    s.serve_forever()
