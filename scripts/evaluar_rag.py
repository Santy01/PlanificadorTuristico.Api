"""Fase 5 · evaluación del RAG.

    python scripts/evaluar_rag.py recuperacion            # sin Groq: recall@k y margen (gratis)
    python scripts/evaluar_rag.py itinerario [--pausa 30] # con Groq: las 10 entradas, sin RAG y con RAG

`recuperacion` mide si el atractivo que el visitante nombra en sus notas aparece entre los recuperados.
`itinerario` compara tokens, latencia y citas con y sin RAG (el plan gratuito de Groq limita a 8000 tokens/min:
la pausa entre llamadas evita los 429). Los resultados se guardan en eval/resultados_rag.json.
"""
import argparse
import csv
import json
import sys
import time
from dataclasses import replace
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.stdout.reconfigure(encoding="utf-8")

from src.catalogo import cargar_catalogo  # noqa: E402
from src.schemas import SolicitudItinerario  # noqa: E402
from src.services.itinerario import generar_itinerario, tipos_pedidos  # noqa: E402
from src.services.llm import ClienteLLM, ErrorLLM  # noqa: E402
from src.services.rag import ClienteRAG  # noqa: E402

# (intereses, notas, ids aceptados): el visitante nombra un atractivo concreto y debe aparecer recuperado.
ORO = [
    (["natural", "cultural"], "quiero ver el tren y la Nariz del Diablo", {"tren-ecuador-nariz-del-diablo"}),
    (["natural"], "Me interesa la laguna de Quilotoa", {"laguna-de-quilotoa", "ruta-del-quilotoa-chugchilan"}),
    (["natural"], "la cascada Pailón del Diablo en Baños", {"cascada-pailon-del-diablo"}),
    (["natural"], "quiero ver el volcán Chimborazo", {"volcan-chimborazo-reserva-de-produccion-de-fauna-chimborazo"}),
    (["cultural"], "el carnaval de Guaranda", {"carnaval-de-guaranda", "museo-del-carnaval-guaranda"}),
    (["gastronómico"], "probar el hornado de Riobamba", {"hornado-de-riobamba"}),
    (["natural"], "subir al volcán Cotopaxi", {"parque-nacional-cotopaxi", "volcan-cotopaxi-y-refugio-jose-rivas"}),
    (["cultural"], "artesanía textil de Salasaca", {"salasaca-artesania-textil"}),
]


def recuperacion() -> None:
    catalogo = cargar_catalogo()
    rag = ClienteRAG()
    rag.precalentar()
    print(f"{'top_k':>5} {'margen':>7} | recall | atractivos recuperados (media)")
    for top_k in (3, 5, 8, 12):
        for margen in (0.02, 0.05, 0.10):
            rag.cfg = replace(rag.cfg, top_k=top_k, margen=margen)
            aciertos, tamanos = 0, []
            for intereses, notas, buenos in ORO:
                s = SolicitudItinerario(dias=2, presupuesto_usd=100, punto_partida="Ambato", intereses=intereses, notas=notas)
                rec = rag.recuperar(s, catalogo, tipos_pedidos(s) or None)
                aciertos += bool(buenos & set(rec.atractivo_ids))
                tamanos.append(len(rec.atractivo_ids))
            print(f"{top_k:>5} {margen:>7} | {aciertos}/{len(ORO)}  | {sum(tamanos) / len(tamanos):.1f}")


def itinerario(pausa: float) -> None:
    catalogo = cargar_catalogo()
    rag = ClienteRAG()
    rag.precalentar()
    llm = ClienteLLM()
    ultimo = {}
    original = llm.generar_json

    def medido(*a, **k):  # guarda los tokens y la latencia de la última respuesta
        r = original(*a, **k)
        ultimo.update(tokens_entrada=r.tokens_entrada, tokens_salida=r.tokens_salida, ms=r.latencia_ms)
        return r
    llm.generar_json = medido

    entradas = list(csv.DictReader(open(RAIZ / "eval/entradas_prompts.csv", encoding="utf-8")))
    filas = []
    for e in entradas:
        s = SolicitudItinerario(dias=int(e["dias"]), presupuesto_usd=float(e["presupuesto_usd"]),
                                punto_partida=e["punto_partida"], intereses=e["intereses"].split("|"),
                                notas=e["notas"] or None)
        for modo, cliente in (("sin_rag", None), ("con_rag", rag)):
            ultimo.clear()
            try:
                r = generar_itinerario(llm, s, catalogo, rag=cliente)
                acts = [a for d in r.dias for a in d.actividades]
                fila = {"id": e["id"], "tipo": e["tipo"], "modo": modo, "estado": r.estado, "dias": len(r.dias),
                        "actividades": len(acts), "con_citas": sum(bool(a.citas) for a in acts),
                        "citas": sum(len(a.citas) for a in acts),
                        "descartadas": [w for w in r.advertencias if "cita" in w.lower()],
                        "inventados": [a.atractivo_id for a in acts if a.atractivo_id not in catalogo], **ultimo}
            except ErrorLLM as err:
                fila = {"id": e["id"], "tipo": e["tipo"], "modo": modo, "estado": f"ERROR {type(err).__name__}"}
            filas.append(fila)
            print(fila, flush=True)
            time.sleep(pausa)
    (RAIZ / "eval/resultados_rag.json").write_text(json.dumps(filas, ensure_ascii=False, indent=2), encoding="utf-8")


ap = argparse.ArgumentParser()
ap.add_argument("modo", choices=["recuperacion", "itinerario"])
ap.add_argument("--pausa", type=float, default=30)
a = ap.parse_args()
recuperacion() if a.modo == "recuperacion" else itinerario(a.pausa)
