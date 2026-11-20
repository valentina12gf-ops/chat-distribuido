#!/usr/bin/env python3
"""Experimento: PÉRDIDAS ANTE UNA CAÍDA + TIEMPO DE RECUPERACIÓN.

Por cada repetición:
  1. Mata el servidor del grupo (docker kill / SIGKILL).
  2. Desde OTRO servidor (g1b) envía --count mensajes a --rate mensajes/s.
  3. Espera hasta completar --outage segundos de caída y vuelve a levantar el servidor.
  4. Mide el tiempo hasta que su historial contiene TODOS los mensajes enviados,
     y cuenta mensajes faltantes y duplicados.

Modos:  --modo docker (por defecto; requiere `docker compose --profile local up -d`)
        --modo local  (procesos locales, sin Docker, para ensayar el script)
Ejemplo: python3 experiment/medir_recuperacion.py --repeats 3 --count 20 --rate 5 --outage 10
"""
import argparse
import csv
import os
import statistics
import subprocess
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from entorno_local import EntornoLocal, get_json, post_json  # noqa: E402

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class EntornoDocker:
    def __init__(self, url_a, url_b):
        self.urls = {"a": url_a, "b": url_b}

    def _compose(self, *args):
        subprocess.run(["docker", "compose", "--profile", "local", *args], cwd=RAIZ, check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def kill(self, n):
        # `stop -t 0` = SIGTERM seguido de SIGKILL inmediato (caída brusca). Se usa en vez de
        # `docker kill` porque con `restart: unless-stopped` Docker relanzaría el contenedor solo.
        self._compose("stop", "-t", "0", "server" if n == "a" else "server-b")

    def start(self, n):
        self._compose("start", "server" if n == "a" else "server-b")

    def wait_ready(self, n, timeout=60.0):
        t0 = time.time()
        while time.time() - t0 < timeout:
            try:
                get_json(self.urls[n] + "/health")
                return
            except Exception:
                time.sleep(0.1)
        raise RuntimeError(f"{n} no respondió en {timeout}s")

    def stop_all(self):
        pass


def asegurar_usuario(url, nombre):
    post_json(url + "/users", {"name": nombre})
    grupo = get_json(url + "/status")["server"]
    return f"{nombre}@{grupo}"


def una_repeticion(env, rep, args):
    ua, ub = env.urls["a"], env.urls["b"]
    emisor = asegurar_usuario(ub, "emisor")
    asegurar_usuario(ua, "receptor")
    for _ in range(100):                      # esperar a que ambos estén registrados y con el central arriba
        if get_json(ua + "/status")["central_up"] and get_json(ub + "/status")["central_up"]:
            break
        time.sleep(0.2)

    env.kill("a")
    t_caida = time.time()
    ids = []
    for i in range(args.count):
        st, m = post_json(ub + "/messages", {"from": emisor, "body": f"rep{rep} msg{i}"})
        ids.append(m["id"])
        time.sleep(1.0 / args.rate)
    restante = args.outage - (time.time() - t_caida)
    if restante > 0:
        time.sleep(restante)
    duracion_caida = time.time() - t_caida

    t0 = time.time()                           # aquí empieza a contar la recuperación
    env.start("a")
    env.wait_ready("a")
    t_http = time.time() - t0                  # el servidor ya responde HTTP
    t_completo, faltan = None, len(ids)
    while time.time() - t0 < args.timeout:
        presentes = {m["id"] for m in get_json(ua + "/messages")["messages"]}
        faltan = len([i for i in ids if i not in presentes])
        if faltan == 0:
            t_completo = time.time() - t0
            break
        time.sleep(0.05)
    todos = [m["id"] for m in get_json(ua + "/messages")["messages"]]
    duplicados = len(todos) - len(set(todos))
    return {
        "repeticion": rep, "caida_s": round(duracion_caida, 2), "mensajes": args.count, "tasa_msg_s": args.rate,
        "arranque_http_s": round(t_http, 2),
        "recuperacion_s": round(t_completo, 2) if t_completo is not None else "",
        "perdidos": faltan, "duplicados": duplicados,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--modo", choices=["docker", "local"], default="docker")
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--count", type=int, default=20, help="mensajes enviados durante la caída")
    ap.add_argument("--rate", type=float, default=5.0, help="mensajes por segundo")
    ap.add_argument("--outage", type=float, default=10.0, help="duración mínima de la caída (s)")
    ap.add_argument("--timeout", type=float, default=120.0)
    ap.add_argument("--url-a", default="http://localhost:8000")
    ap.add_argument("--url-b", default="http://localhost:8001")
    ap.add_argument("--out", default=os.path.join(RAIZ, "experiment", "datos", "resultados.csv"))
    args = ap.parse_args()

    if args.modo == "local":
        env = EntornoLocal(HEARTBEAT_INTERVAL=5, HEARTBEAT_MAX_FAILS=3, HISTORY_SYNC_INTERVAL=30)
        env.start_all()
    else:
        env = EntornoDocker(args.url_a, args.url_b)
        env.wait_ready("a"); env.wait_ready("b")

    filas = []
    try:
        for r in range(1, args.repeats + 1):
            fila = una_repeticion(env, r, args)
            fila.update(modo=args.modo, fecha=datetime.now().isoformat(timespec="seconds"))
            filas.append(fila)
            print(f"rep {r}: caída={fila['caida_s']}s  recuperación={fila['recuperacion_s']}s  "
                  f"perdidos={fila['perdidos']}  duplicados={fila['duplicados']}", flush=True)
    finally:
        env.stop_all()

    nuevo = not os.path.exists(args.out)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(filas[0]))
        if nuevo:
            w.writeheader()
        w.writerows(filas)
    rec = [f["recuperacion_s"] for f in filas if f["recuperacion_s"] != ""]
    if rec:
        sd = statistics.stdev(rec) if len(rec) > 1 else 0.0
        print(f"\nRecuperación (s): media={statistics.mean(rec):.2f}  min={min(rec):.2f}  max={max(rec):.2f}  "
              f"desv={sd:.2f}  n={len(rec)}\nCSV: {args.out}")


if __name__ == "__main__":
    main()
