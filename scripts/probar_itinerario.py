"""NIVEL 2 · Itinerario completo a través del servicio (reintentos, validación y reglas del código).

    python scripts/probar_itinerario.py                      # ejemplo por defecto
    python scripts/probar_itinerario.py --dias 3 --presupuesto 200 --partida Quito --intereses natural cultural
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.catalogo import cargar_catalogo  # noqa: E402
from src.schemas import SolicitudItinerario  # noqa: E402
from src.services.itinerario import generar_itinerario  # noqa: E402
from src.services.llm import ClienteLLM, ErrorLLM  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--dias", type=int, default=2)
ap.add_argument("--presupuesto", type=float, default=150)
ap.add_argument("--partida", default="Ambato")
ap.add_argument("--intereses", nargs="+", default=["natural", "gastronómico"])
ap.add_argument("--notas", default=None)
a = ap.parse_args()

solicitud = SolicitudItinerario(dias=a.dias, presupuesto_usd=a.presupuesto, punto_partida=a.partida,
                                intereses=a.intereses, notas=a.notas)
try:
    r = generar_itinerario(ClienteLLM(), solicitud, cargar_catalogo())
except ErrorLLM as e:
    sys.exit(f"✗ {e.mensaje_usuario}")
print(r.model_dump_json(indent=2))
