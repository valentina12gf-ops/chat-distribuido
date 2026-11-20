#!/usr/bin/env python3
"""Cliente de línea de comandos. Habla SOLO con el servidor de su grupo.
Uso:  python3 client/chat_client.py --server http://localhost:8000 --user ana
Comandos: /salir  termina.   Cualquier otra línea se envía a #general."""
import argparse
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request

VERDE, AMARILLO, GRIS, RESET = "\033[92m", "\033[93m", "\033[90m", "\033[0m"
os.system("")  # activa colores ANSI en la consola de Windows


def llamar(metodo, url, cuerpo=None):
    datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
    req = urllib.request.Request(url, data=datos, method=metodo, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"null")


def mostrar(m, mi_grupo):
    propio = m["origin"] == mi_grupo
    color, etiqueta = (VERDE, "") if propio else (AMARILLO, f" {GRIS}[otro grupo: {m['origin']}]{RESET}")
    print(f"\r{GRIS}[{m['lamport']:>4}]{RESET} {color}{m['from']}{RESET}{etiqueta}: {m['body']}")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--server", default="http://localhost:8000")
    ap.add_argument("--user", required=True, help="nombre de usuario (sin @grupo)")
    a = ap.parse_args()
    base = a.server.rstrip("/")

    try:
        _, estado = llamar("GET", f"{base}/status")
    except OSError as e:
        sys.exit(f"No se pudo conectar con {base}: {e}")
    grupo = estado["server"]
    llamar("POST", f"{base}/users", {"name": a.user})   # 201 si es nuevo, 409 si ya existía
    yo = f"{a.user.lower()}@{grupo}"
    print(f"Conectado como {VERDE}{yo}{RESET} a {base}. Escribe un mensaje y Enter; /salir para terminar.\n")

    vistos: set[str] = set()
    activo = True

    def sondear():
        while activo:
            try:
                _, r = llamar("GET", f"{base}/messages")
                for m in r["messages"]:
                    if m["id"] not in vistos:
                        vistos.add(m["id"])
                        mostrar(m, grupo)
            except OSError:
                pass
            time.sleep(1)

    hilo = threading.Thread(target=sondear, daemon=True)
    hilo.start()
    try:
        for linea in sys.stdin:
            linea = linea.strip()
            if linea == "/salir":
                break
            if linea:
                st, r = llamar("POST", f"{base}/messages", {"from": yo, "body": linea})
                if st >= 400:
                    print(f"[error {st}] {r}")
    except KeyboardInterrupt:
        pass
    activo = False


if __name__ == "__main__":
    main()
