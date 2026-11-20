"""Prueba de humo SIN Docker: central simulado + g1 + g1b como procesos.
Verifica registro, entrega, Lamport/orden, deduplicación, persistencia,
reintentos, detección de caída del central y recuperación de historial.
Uso:  python3 tests/prueba_local.py"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "experiment"))
from entorno_local import EntornoLocal, get_json, post_json  # noqa: E402

fallos = 0


def check(nombre: str, condicion: bool, detalle: str = "") -> None:
    global fallos
    print(f"  [{'OK ' if condicion else 'FALLO'}] {nombre}" + (f"  ({detalle})" if detalle and not condicion else ""))
    if not condicion:
        fallos += 1


def esperar(fn, timeout=20.0, paso=0.2) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if fn():
                return True
        except Exception:
            pass
        time.sleep(paso)
    return False


def msgs(env, n):
    return get_json(env.urls[n] + "/messages")["messages"]


def ids(env, n):
    return [m["id"] for m in msgs(env, n)]


def log_texto(env, n):
    return open(env.log_path(n), errors="replace").read()


env = EntornoLocal()
try:
    print("== 1. Arranque y registro")
    env.start_all()
    check("a y b registrados en el central", esperar(lambda: set(get_json(env.urls["central"] + "/registry")["servers"]) == {"g1", "g1b"}))
    check("central marcado arriba", esperar(lambda: get_json(env.urls["a"] + "/status")["central_up"]))
    post_json(env.urls["a"] + "/users", {"name": "ana"})
    post_json(env.urls["b"] + "/users", {"name": "beto"})
    st, _ = post_json(env.urls["a"] + "/users", {"name": "ana"})
    check("usuario repetido -> 409", st == 409)
    st, _ = post_json(env.urls["a"] + "/messages", {"from": "beto@g1b", "body": "x"})
    check("no se puede escribir como usuario de otro grupo -> 403", st == 403)

    print("== 2. Entrega, Lamport y orden")
    st, m1 = post_json(env.urls["a"] + "/messages", {"from": "ana@g1", "body": "hola desde g1"})
    check("mensaje local creado (201)", st == 201 and m1["origin"] == "g1")
    check("b recibe el mensaje de a", esperar(lambda: m1["id"] in ids(env, "b")))
    st, m2 = post_json(env.urls["b"] + "/messages", {"from": "beto@g1b", "body": "respuesta desde g1b"})
    check("lamport de b > lamport recibido de a", m2["lamport"] > m1["lamport"], f"{m2['lamport']} vs {m1['lamport']}")
    check("a recibe el mensaje de b", esperar(lambda: m2["id"] in ids(env, "a")))
    check("mismo orden en a y b", ids(env, "a") == ids(env, "b"))
    check("pendientes en 0 tras enviar", esperar(lambda: get_json(env.urls["a"] + "/status")["pending"] == 0))

    print("== 3. Deduplicación e idempotencia")
    extra = dict(m1, campo_desconocido="ignorar")
    s1, r1 = post_json(env.urls["b"] + "/fed/messages", extra)
    s2, r2 = post_json(env.urls["b"] + "/fed/messages", extra)
    check("reenviar un id conocido responde 200 (idempotente)", s1 == 200 and s2 == 200)
    check("el mensaje sigue apareciendo una sola vez", ids(env, "b").count(m1["id"]) == 1)
    check("campos desconocidos se ignoran sin error", s1 == 200)
    check("'DUP' queda en el log", "DUP discard" in log_texto(env, "b"))
    s, _ = post_json(env.urls["b"] + "/fed/messages", {"id": "x", "from": "z@g9"})
    check("mensaje inválido -> 400 (no se reintenta)", s == 400)

    print("== 4. Persistencia tras caída brusca (SIGKILL)")
    antes = ids(env, "a"); reloj_antes = get_json(env.urls["a"] + "/status")["lamport"]
    env.kill("a"); env.start("a"); env.wait_ready("a")
    check("historial intacto tras reinicio", ids(env, "a") == antes)
    check("usuarios intactos tras reinicio", "ana@g1" in get_json(env.urls["a"] + "/users")["users"])
    max_guardado = max(m["lamport"] for m in msgs(env, "a"))
    check("reloj de Lamport restaurado con el mayor lamport guardado", get_json(env.urls["a"] + "/status")["lamport"] == max_guardado)
    _, mpost = post_json(env.urls["a"] + "/messages", {"from": "ana@g1", "body": "tras reiniciar"})
    check("el primer mensaje tras reiniciar tiene lamport mayor que todos los guardados", mpost["lamport"] > max_guardado)

    print("== 5. Central caído: pendientes, reintentos y reenvío al volver")
    esperar(lambda: get_json(env.urls["a"] + "/status")["central_up"])
    env.kill("central")
    st, m3 = post_json(env.urls["a"] + "/messages", {"from": "ana@g1", "body": "escrito con el central caído"})
    check("el mensaje se guarda localmente aunque el central esté caído", st == 201)
    check("a detecta CENTRAL_DOWN", esperar(lambda: not get_json(env.urls["a"] + "/status")["central_up"]))
    check("el mensaje queda en pendientes", get_json(env.urls["a"] + "/status")["pending"] >= 1)
    check("hay RETRY o CENTRAL_DOWN en el log", "CENTRAL_DOWN" in log_texto(env, "a"))
    env.start("central"); env.wait_ready("central")
    check("a y b se registran de nuevo", esperar(lambda: len(get_json(env.urls["central"] + "/registry")["servers"]) == 2, 25))
    check("el pendiente se entrega al volver el central", esperar(lambda: get_json(env.urls["a"] + "/status")["pending"] == 0, 25))
    check("b recibe el mensaje escrito durante la caída", esperar(lambda: m3["id"] in ids(env, "b"), 25))

    print("== 6. Recuperación de historial tras caída de a")
    env.kill("a")
    enviados = []
    for i in range(5):
        _, m = post_json(env.urls["b"] + "/messages", {"from": "beto@g1b", "body": f"mientras a está caído {i}"})
        enviados.append(m["id"])
        time.sleep(0.2)
    time.sleep(5)  # el central agota sus reenvíos hacia a
    env.start("a"); env.wait_ready("a")
    check("a recupera los 5 mensajes perdidos", esperar(lambda: set(enviados) <= set(ids(env, "a")), 20))
    ids_a = ids(env, "a")
    check("sin duplicados en a", len(ids_a) == len(set(ids_a)))
    check("'HISTORY' queda en el log", "HISTORY since=" in log_texto(env, "a"))
    check("mismo orden final en a y b", esperar(lambda: ids(env, "a") == ids(env, "b")))
finally:
    env.stop_all()

print(f"\nRESULTADO: {'TODO OK' if fallos == 0 else str(fallos) + ' FALLO(S)'}   (logs en {env.tmp})")
sys.exit(1 if fallos else 0)
