"""Conexión con el servidor central: registro, heartbeat, envío con reintentos,
deduplicación y recuperación de historial. Tres hilos en segundo plano."""
import http.client
import json
import logging
import threading
import time
import urllib.error
import urllib.request

from . import config
from .clock import LamportClock
from .db import Database

log = logging.getLogger("federation")

# Errores de red: sin conexión, timeout, conexión cortada a media respuesta.
ERRORES_RED = (OSError, http.client.HTTPException)


def http_request(method: str, url: str, body: dict | None = None, timeout: float = 5.0):
    """Devuelve (status, json|None). Lanza ERRORES_RED si no hubo respuesta HTTP."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status, raw = resp.status, resp.read()
    except urllib.error.HTTPError as e:      # 4xx/5xx también son respuestas
        status, raw = e.code, e.read()
    try:
        payload = json.loads(raw) if raw else None
    except ValueError:
        payload = None
    return status, payload


def validar_mensaje(m) -> tuple[dict | None, str | None]:
    """Valida el formato del protocolo. Los campos desconocidos se ignoran."""
    if not isinstance(m, dict):
        return None, "el cuerpo debe ser un objeto JSON"
    for campo in ("id", "from", "origin", "body"):
        if not isinstance(m.get(campo), str) or not m[campo]:
            return None, f"campo '{campo}' ausente o no es texto"
    lamport = m.get("lamport")
    if isinstance(lamport, bool) or not isinstance(lamport, int) or lamport < 0:
        return None, "campo 'lamport' ausente o no es un entero >= 0"
    sent_at = m.get("sent_at", "")
    return {"id": m["id"], "from": m["from"], "origin": m["origin"], "lamport": lamport,
            "sent_at": sent_at if isinstance(sent_at, str) else "", "body": m["body"]}, None


class Federation:
    def __init__(self, db: Database, clock: LamportClock) -> None:
        self.db = db
        self.clock = clock
        self.central_up = False
        self._fails = 0
        self._history_ok = False          # ¿ya nos pusimos al día con el central?
        self._last_sync = 0.0
        self._wake = threading.Event()    # despierta al hilo de envío
        self._register_now = threading.Event()
        self._stop = threading.Event()

    # ------------------------------------------------------------------ arranque
    def start(self) -> None:
        for objetivo in (self._register_loop, self._heartbeat_loop, self._sender_loop):
            threading.Thread(target=objetivo, daemon=True, name=objetivo.__name__).start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        self._register_now.set()

    def notify_outbound(self) -> None:
        self._wake.set()

    # ------------------------------------------------------------------ registro
    def _register(self) -> bool:
        cuerpo = {"server": config.GROUP_NAME, "url": config.PUBLIC_URL}
        try:
            status, _ = http_request("POST", f"{config.CENTRAL_URL}/register", cuerpo, config.REQUEST_TIMEOUT)
        except ERRORES_RED as e:
            log.warning("REGISTER failed error=%s", e)
            return False
        if 200 <= status < 300:
            log.info("REGISTER ok server=%s url=%s", config.GROUP_NAME, config.PUBLIC_URL)
            return True
        log.warning("REGISTER rejected status=%s", status)
        return False

    def _register_loop(self) -> None:
        while not self._stop.is_set():
            ok = self._register()
            espera = config.REGISTER_INTERVAL if ok else min(config.REGISTER_INTERVAL, 3.0)
            self._register_now.wait(espera)    # se despierta antes si el central vuelve
            self._register_now.clear()

    # ----------------------------------------------------------------- heartbeat
    def _central_vivo(self) -> bool:
        try:
            status, _ = http_request("GET", f"{config.CENTRAL_URL}/health", None, config.REQUEST_TIMEOUT)
        except ERRORES_RED:
            return False
        return 200 <= status < 300

    def _heartbeat_loop(self) -> None:
        while not self._stop.is_set():
            if self._central_vivo():
                self._fails = 0
                if not self.central_up:
                    self.central_up = True
                    log.info("CENTRAL_UP")
                    self._register_now.set()   # el central pudo haber perdido el registro
                    self._wake.set()           # vaciar la cola de pendientes
                vencido = (config.HISTORY_SYNC_INTERVAL > 0
                           and time.time() - self._last_sync >= config.HISTORY_SYNC_INTERVAL)
                if not self._history_ok or vencido:
                    self._history_ok = self.recover_history(quiet=self._history_ok)
                    self._last_sync = time.time()
            else:
                self._fails += 1
                log.warning("HEARTBEAT fail %d/%d", self._fails, config.HEARTBEAT_MAX_FAILS)
                if self.central_up and self._fails >= config.HEARTBEAT_MAX_FAILS:
                    self.central_up = False
                    self._history_ok = False   # al volver habrá que recuperar historial
                    log.warning("CENTRAL_DOWN fails=%d pending=%d", self._fails, self.db.pending_count())
            self._stop.wait(config.HEARTBEAT_INTERVAL)

    # ------------------------------------------------------------------ historial
    def recover_history(self, quiet: bool = False) -> bool:
        """GET /history?since=N. N = mayor lamport de mensajes ajenos menos un solape
        (por si dos mensajes comparten lamport o llegaron desordenados). Los repetidos
        se descartan por id, así que el solape no cuesta nada."""
        since = max(0, self.db.max_remote_lamport(config.GROUP_NAME) - config.HISTORY_OVERLAP)
        try:
            status, payload = http_request("GET", f"{config.CENTRAL_URL}/history?since={since}",
                                           None, config.REQUEST_TIMEOUT)
        except ERRORES_RED as e:
            log.warning("HISTORY failed since=%d error=%s", since, e)
            return False
        if status != 200:
            log.warning("HISTORY rejected since=%d status=%s", since, status)
            return False
        mensajes = payload.get("messages") if isinstance(payload, dict) else payload
        if not isinstance(mensajes, list):
            log.warning("HISTORY unexpected payload since=%d", since)
            return False

        def clave(m):
            l = m.get("lamport") if isinstance(m, dict) else 0
            return (l if isinstance(l, int) else 0, str(m.get("origin", "")) if isinstance(m, dict) else "")

        nuevos = 0
        for m in sorted(mensajes, key=clave):
            if self.ingest(m, source="sync" if quiet else "history", log_dup=not quiet) == "accepted":
                nuevos += 1
        if nuevos or not quiet:
            log.info("HISTORY since=%d recovered=%d total=%d", since, nuevos, len(mensajes))
        return True

    # ------------------------------------------------------------------ recepción
    def ingest(self, crudo, source: str, log_dup: bool = True) -> str:
        """Procesa un mensaje entrante. Devuelve 'accepted', 'duplicate' o 'invalid:<motivo>'."""
        m, error = validar_mensaje(crudo)
        if m is None:
            log.warning("RECV invalid source=%s reason=%s", source, error)
            return f"invalid:{error}"
        if not self.db.insert_message(m, source):          # atómico: INSERT OR IGNORE
            if log_dup:
                log.info("DUP discard id=%s from=%s lamport=%d source=%s", m["id"], m["from"], m["lamport"], source)
            return "duplicate"
        reloj = self.clock.observe(m["lamport"])           # regla de Lamport al recibir
        log.info("RECV id=%s from=%s lamport=%d clock=%d source=%s", m["id"], m["from"], m["lamport"], reloj, source)
        return "accepted"

    # ----------------------------------------------------------------------- envío
    def _backoff(self, intentos: int) -> float:
        return min(config.RETRY_BASE_SECONDS * (2 ** (intentos - 1)), config.RETRY_MAX_SECONDS)

    def _sender_loop(self) -> None:
        while not self._stop.is_set():
            self._wake.clear()                 # limpiar ANTES de mirar la cola (evita despertares perdidos)
            espera = 5.0
            if self.central_up:
                espera = self._vaciar_cola()
            self._wake.wait(espera)

    def _vaciar_cola(self) -> float:
        for item in self.db.due_pending(time.time()):
            if not self.central_up:
                break
            if not self._enviar(item):
                break                          # falló: esperar el backoff antes de seguir
        siguiente = self.db.seconds_until_next_pending(time.time())
        return 5.0 if siguiente is None else min(max(siguiente, 0.05), 5.0)

    def _enviar(self, item: dict) -> bool:
        """True si el mensaje salió de la cola (enviado o descartado); False si se reintentará."""
        mid, payload, intentos = item["id"], item["payload"], item["attempts"] + 1
        try:
            status, _ = http_request("POST", f"{config.CENTRAL_URL}/messages", payload, config.REQUEST_TIMEOUT)
        except ERRORES_RED as e:
            self._reintentar(mid, intentos, f"error={e}")
            return False
        if 200 <= status < 300:
            log.info("SENT id=%s from=%s lamport=%s attempt=%d", mid, payload.get("from"), payload.get("lamport"), intentos)
            self.db.remove_pending(mid)
            return True
        if 400 <= status < 500:                 # 4xx: el mensaje está mal, reintentar no lo arregla
            log.error("DROP id=%s attempt=%d status=%d", mid, intentos, status)
            self.db.remove_pending(mid)
            return True
        self._reintentar(mid, intentos, f"status={status}")   # 5xx u otro: reintentar
        return False

    def _reintentar(self, mid: str, intentos: int, motivo: str) -> None:
        espera = self._backoff(intentos)
        self.db.mark_attempt(mid, intentos, time.time() + espera)
        log.warning("RETRY id=%s attempt=%d delay=%.2fs %s", mid, intentos, espera, motivo)
