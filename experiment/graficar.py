#!/usr/bin/env python3
"""Gráfica para el póster a partir de uno o más CSV de medir_recuperacion.py.
Uso:  pip install matplotlib
      python3 experiment/graficar.py experiment/datos/resultados.csv --out experiment/datos/grafica_poster.png"""
import argparse
import csv
import statistics
from collections import defaultdict

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("csvs", nargs="+")
ap.add_argument("--out", default="grafica_poster.png")
ap.add_argument("--por", default="caida_s", choices=["caida_s", "tasa_msg_s", "mensajes"],
                help="parámetro variado (eje X)")
a = ap.parse_args()

grupos = defaultdict(list)
for ruta in a.csvs:
    for fila in csv.DictReader(open(ruta)):
        if fila["recuperacion_s"] != "":
            clave = round(float(fila[a.por])) if a.por == "caida_s" else float(fila[a.por])
            grupos[clave].append(float(fila["recuperacion_s"]))

xs = sorted(grupos)
medias = [statistics.mean(grupos[x]) for x in xs]
desv = [statistics.stdev(grupos[x]) if len(grupos[x]) > 1 else 0 for x in xs]
etiquetas = {"caida_s": "Duración de la caída (s)", "tasa_msg_s": "Tasa de envío (mensajes/s)",
             "mensajes": "Mensajes enviados durante la caída"}
fig, ax = plt.subplots(figsize=(7, 4.5))
ax.bar([str(x) for x in xs], medias, yerr=desv, capsize=6, color="#2a6f97", alpha=0.85, label="media ± desv. est.")
for i, x in enumerate(xs):
    ax.scatter([i] * len(grupos[x]), grupos[x], color="black", s=18, zorder=3, label="repeticiones" if i == 0 else None)
ax.set_xlabel(etiquetas[a.por])
ax.set_ylabel("Tiempo de recuperación (s)")
ax.set_title("Tiempo hasta que el historial coincide con el del central")
ax.legend()
fig.tight_layout()
fig.savefig(a.out, dpi=200)
print(f"Gráfica guardada en {a.out}")
print("\n| " + etiquetas[a.por] + " | n | media (s) | desv. (s) | min (s) | max (s) |\n|---|---|---|---|---|---|")
for x in xs:
    v = grupos[x]
    print(f"| {x} | {len(v)} | {statistics.mean(v):.2f} | {(statistics.stdev(v) if len(v) > 1 else 0):.2f} | {min(v):.2f} | {max(v):.2f} |")
