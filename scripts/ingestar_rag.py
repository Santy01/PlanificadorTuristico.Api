"""Ingesta offline del RAG: del corpus (data/corpus/manifiesto.csv) al índice vectorial (Chroma).

    python scripts/ingestar_rag.py              # fragmenta, calcula embeddings e indexa
    python scripts/ingestar_rag.py --simular    # solo fragmenta y asigna: no carga el modelo ni toca Chroma

Antes se debe haber ejecutado scripts/construir_corpus.py. La ingesta es reproducible: reconstruye la colección
completa, así que reejecutarla no duplica fragmentos.
"""
import argparse
import csv
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from src.catalogo import cargar_catalogo  # noqa: E402
from src.services.indice import (  # noqa: E402
    cargar_config_rag, cargar_modelo, construir_registros, reconstruir_coleccion,
)

MANIFIESTO = RAIZ / "data" / "corpus" / "manifiesto.csv"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--simular", action="store_true", help="solo fragmenta y asigna; no indexa")
    args = ap.parse_args()

    if not MANIFIESTO.exists():
        sys.exit("No existe data/corpus/manifiesto.csv: ejecute primero scripts/construir_corpus.py")
    cfg = cargar_config_rag()
    catalogo = cargar_catalogo()
    with open(MANIFIESTO, encoding="utf-8", newline="") as f:
        filas = list(csv.DictReader(f))

    registros, est = construir_registros(
        filas, catalogo, lambda ruta: (RAIZ / ruta).read_text(encoding="utf-8"))
    sin_web = sorted(set(catalogo) - est.atractivos_con_web)
    print(f"Fragmentos: {est.fragmentos}  {est.por_clase}")
    print(f"Descartados (página con varios atractivos y el fragmento no nombra a ninguno o empata entre varios): {est.descartados}")
    print(f"Atractivos con al menos un fragmento web: {len(est.atractivos_con_web)} de {len(catalogo)} "
          f"(solo ficha: {len(sin_web)})")
    if est.sin_texto:
        print(f"Documentos del manifiesto sin archivo: {est.sin_texto}")
    if args.simular:
        return

    print(f"Cargando el modelo de embeddings «{cfg.modelo}» (la primera vez se descarga)...")
    inicio = time.perf_counter()
    modelo = cargar_modelo(cfg)
    total = reconstruir_coleccion(cfg, modelo, registros)
    print(f"Indexados {total} fragmentos en «{cfg.coleccion}» ({cfg.ruta.relative_to(RAIZ)}) "
          f"en {time.perf_counter() - inicio:.0f} s.")


if __name__ == "__main__":
    main()
