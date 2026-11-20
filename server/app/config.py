"""Configuración del servidor. TODO sale de variables de entorno (ninguna URL va en el código)."""
import os
import re
import sys


def _requerida(nombre: str) -> str:
    valor = os.environ.get(nombre, "").strip()
    if not valor:
        sys.exit(f"ERROR: falta la variable de entorno {nombre} (ver .env.example)")
    return valor


GROUP_NAME = _requerida("GROUP_NAME")
if not re.fullmatch(r"g[0-9]+[a-z]?", GROUP_NAME):
    sys.exit(f"ERROR: GROUP_NAME='{GROUP_NAME}' no es válido (formato gN, p. ej. g3 o g3b)")

PUBLIC_URL = _requerida("PUBLIC_URL").rstrip("/")    # cómo nos alcanza el servidor central
CENTRAL_URL = _requerida("CENTRAL_URL").rstrip("/")  # dónde está el servidor central

HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8000"))
DB_PATH = os.environ.get("DB_PATH", "/data/chat.db")

REGISTER_INTERVAL = float(os.environ.get("REGISTER_INTERVAL", "30"))      # s entre renovaciones
HEARTBEAT_INTERVAL = float(os.environ.get("HEARTBEAT_INTERVAL", "5"))     # s entre GET /health
HEARTBEAT_MAX_FAILS = int(os.environ.get("HEARTBEAT_MAX_FAILS", "3"))     # fallos para marcar caído
RETRY_BASE_SECONDS = float(os.environ.get("RETRY_BASE_SECONDS", "0.5"))   # backoff: base * 2^(n-1)
RETRY_MAX_SECONDS = float(os.environ.get("RETRY_MAX_SECONDS", "30"))      # tope del backoff
REQUEST_TIMEOUT = float(os.environ.get("REQUEST_TIMEOUT", "5"))           # timeout HTTP saliente
HISTORY_OVERLAP = int(os.environ.get("HISTORY_OVERLAP", "10"))            # solape al pedir /history
HISTORY_SYNC_INTERVAL = float(os.environ.get("HISTORY_SYNC_INTERVAL", "30"))  # 0 = desactivado
