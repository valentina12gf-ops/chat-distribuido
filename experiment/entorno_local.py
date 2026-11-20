"""Levanta central simulado + dos servidores (g1 y g1b) como procesos locales, SIN Docker.
Sirve para probar y para ensayar el experimento en una máquina sin Docker."""
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_json(url: str, timeout: float = 2.0):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read())


def post_json(url: str, cuerpo: dict, timeout: float = 5.0):
    req = urllib.request.Request(url, data=json.dumps(cuerpo).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"null")


class EntornoLocal:
    def __init__(self, puerto_central=9100, puerto_a=8100, puerto_b=8101, **env_extra):
        self.tmp = tempfile.mkdtemp(prefix="chat_local_")
        self.urls = {"central": f"http://127.0.0.1:{puerto_central}",
                     "a": f"http://127.0.0.1:{puerto_a}", "b": f"http://127.0.0.1:{puerto_b}"}
        self.puertos = {"central": puerto_central, "a": puerto_a, "b": puerto_b}
        self.grupos = {"a": "g1", "b": "g1b"}
        self.extra = {"HEARTBEAT_INTERVAL": "1", "HEARTBEAT_MAX_FAILS": "2", "RETRY_BASE_SECONDS": "0.3",
                      "HISTORY_SYNC_INTERVAL": "3", "REQUEST_TIMEOUT": "2", "REGISTER_INTERVAL": "10"}
        self.extra.update({k: str(v) for k, v in env_extra.items()})
        self.procs: dict[str, subprocess.Popen] = {}

    def log_path(self, nombre: str) -> str:
        return os.path.join(self.tmp, f"{nombre}.log")

    def start(self, nombre: str) -> None:
        env = dict(os.environ, PYTHONUNBUFFERED="1")
        if nombre == "central":
            env["PORT"] = str(self.puertos["central"])
            cmd, cwd = [sys.executable, os.path.join(RAIZ, "mock_central", "main.py")], RAIZ
        else:
            env.update(self.extra)
            env.update(GROUP_NAME=self.grupos[nombre], PORT=str(self.puertos[nombre]),
                       PUBLIC_URL=self.urls[nombre], CENTRAL_URL=self.urls["central"],
                       DB_PATH=os.path.join(self.tmp, f"{nombre}.db"))
            cmd, cwd = [sys.executable, "-m", "app.main"], os.path.join(RAIZ, "server")
        salida = open(self.log_path(nombre), "ab")
        self.procs[nombre] = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=salida, stderr=subprocess.STDOUT)

    def kill(self, nombre: str) -> None:
        """Equivale a `docker kill`: SIGKILL, sin cierre ordenado."""
        p = self.procs.get(nombre)
        if p and p.poll() is None:
            p.kill()
            p.wait()

    def wait_ready(self, nombre: str, timeout: float = 20.0) -> float:
        t0 = time.time()
        path = "/registry" if nombre == "central" else "/health"
        while time.time() - t0 < timeout:
            try:
                get_json(self.urls[nombre] + path)
                return time.time() - t0
            except Exception:
                time.sleep(0.1)
        raise RuntimeError(f"{nombre} no respondió en {timeout}s (ver {self.log_path(nombre)})")

    def start_all(self) -> None:
        for n in ("central", "a", "b"):
            self.start(n)
            self.wait_ready(n)

    def stop_all(self) -> None:
        for n in list(self.procs):
            self.kill(n)
