"""Reduce el catálogo a un subconjunto equilibrado para gastar menos tokens y dar buenos resultados.

    python scripts/curar_catalogo.py                 # 60 registros -> data/catalogo/atractivos_reducido.csv
    python scripts/curar_catalogo.py --total 48

Reglas (deterministas: el mismo CSV de entrada da siempre la misma salida):
  1. Solo atractivos con latitud y longitud.
  2. Mismo número por provincia (Tungurahua, Chimborazo, Cotopaxi y Bolívar).
  3. En cada provincia se incluye toda la gastronomía disponible (es escasa) y el resto se reparte a partes
     iguales entre naturaleza y cultura; si falta de un tipo, se completa con el otro.
  4. Dentro de cada grupo se prefieren los mejor verificados (A > A_parcial > B > C), con mejor precisión de
     coordenadas, con costo y duración conocidos y de cantones distintos (para variedad).
El CSV original NO se modifica.
"""
import argparse
import csv
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from src.catalogo import RUTA_CATALOGO, RUTA_REDUCIDA, _slug, cargar_catalogo, con_ubicacion  # noqa: E402

PROVINCIAS = ["Tungurahua", "Chimborazo", "Cotopaxi", "Bolívar"]
CALIDAD = {"A": 0, "A_parcial": 1, "B": 2, "C": 3}
PRECISION = {"verificada_fuente": 0, "sitio_aprox": 1, "localidad_aprox": 2, None: 3}


def puntaje(a) -> tuple:
    return (CALIDAD.get(a.estado_verificacion, 3), PRECISION.get(a.precision_coord, 3),
            a.costo_usd is None, a.duracion_h is None, a.nombre)


def elegir(grupo: list, cuantos: int) -> list:
    """Los mejores `cuantos` del grupo, penalizando repetir cantón para dar variedad."""
    elegidos: list = []
    pendientes = sorted(grupo, key=puntaje)
    while pendientes and len(elegidos) < cuantos:
        cantones = [e.canton for e in elegidos]
        mejor = min(pendientes, key=lambda a: (cantones.count(a.canton), *puntaje(a)))
        elegidos.append(mejor)
        pendientes.remove(mejor)
    return elegidos


def curar(total: int) -> list:
    util = list(con_ubicacion(cargar_catalogo()).values())
    por_provincia = total // len(PROVINCIAS)
    resultado: list = []
    for prov in PROVINCIAS:
        de = lambda tipo: [a for a in util if a.provincia == prov and a.tipo == tipo]  # noqa: E731
        gastro = elegir(de("gastronómico"), por_provincia)
        resto = por_provincia - len(gastro)
        n_nat, n_cul = (resto + 1) // 2, resto // 2
        nat, cul = de("natural"), de("cultural")
        # si un tipo no alcanza, el otro cubre la diferencia
        n_nat, n_cul = min(n_nat + max(0, n_cul - len(cul)), len(nat)), min(n_cul + max(0, n_nat - len(nat)), len(cul))
        resultado += gastro + elegir(nat, n_nat) + elegir(cul, n_cul)
    return resultado


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--total", type=int, default=60)
    ap.add_argument("--salida", type=Path, default=RUTA_REDUCIDA)
    a = ap.parse_args()

    elegidos = {x.id for x in curar(a.total)}
    with open(RUTA_CATALOGO, encoding="utf-8-sig", newline="") as f:
        lector = csv.DictReader(f)
        columnas = lector.fieldnames
        filas = [r for r in lector if _slug(r["nombre"]) in elegidos]
    with open(a.salida, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columnas)
        w.writeheader()
        w.writerows(filas)

    print(f"✓ {len(filas)} atractivos -> {a.salida}\n")
    cat = cargar_catalogo(a.salida)
    tipos = ["natural", "cultural", "gastronómico"]
    print(f"{'':12}" + "".join(f"{t:>14}" for t in tipos) + f"{'total':>8}")
    for p in PROVINCIAS:
        n = [sum(x.provincia == p and x.tipo == t for x in cat.values()) for t in tipos]
        print(f"{p:12}" + "".join(f"{v:>14}" for v in n) + f"{sum(n):>8}")
