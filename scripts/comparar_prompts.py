"""Compara las versiones de system prompt con las 10 entradas de eval/entradas_prompts.csv
y genera la tabla de docs/05-prompts.md.

    python scripts/comparar_prompts.py                  # todas las versiones de src/prompts/
    python scripts/comparar_prompts.py system_v2 system_v3

El script llena las respuestas, los tokens y el tiempo. Las columnas ¿Correcta?, ¿Inventa?
y ¿Formato? las califica EL GRUPO leyendo cada respuesta. La versión ganadora es la que
MENOS inventa, no la que más escribe.
"""
import csv
import json
import sys
from datetime import date
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from src.catalogo import cargar_catalogo  # noqa: E402
from src.schemas import ItinerarioModelo, SolicitudItinerario  # noqa: E402
from src.services.itinerario import contexto_usuario  # noqa: E402
from src.services.llm import ClienteLLM, ErrorLLM, cargar_prompt  # noqa: E402

versiones = sys.argv[1:] or sorted(p.stem for p in (RAIZ / "src/prompts").glob("system_v*.md"))
entradas = list(csv.DictReader(open(RAIZ / "eval/entradas_prompts.csv", encoding="utf-8")))
catalogo = cargar_catalogo()
llm = ClienteLLM()
filas = []

for v in versiones:
    system = cargar_prompt(v)
    for e in entradas:
        solicitud = SolicitudItinerario(dias=int(e["dias"]), presupuesto_usd=float(e["presupuesto_usd"]),
                                        punto_partida=e["punto_partida"], intereses=e["intereses"].split("|"),
                                        notas=e["notas"] or None)
        try:
            r = llm.generar_json(system, contexto_usuario(solicitud, catalogo), ItinerarioModelo)
            salida = r.datos.model_dump()
            ids = [a["id"] for d in salida["dias"] for a in d["atractivos"]]
            salida["ids_inventados"] = [i for i in ids if i not in catalogo]
            fila = {"version": v, "id": e["id"], "salida": salida, "tokens": (r.tokens_entrada or 0) + (r.tokens_salida or 0),
                    "ms": r.latencia_ms, "proveedor": r.proveedor}
        except ErrorLLM as err:
            fila = {"version": v, "id": e["id"], "salida": {"error": type(err).__name__}, "tokens": 0, "ms": 0, "proveedor": "-"}
        filas.append(fila)
        print(f"{v} · entrada {e['id']:>2} · {fila['ms']} ms")

(RAIZ / "eval").mkdir(exist_ok=True)
(RAIZ / "eval/resultados_prompts.json").write_text(json.dumps(filas, ensure_ascii=False, indent=2), encoding="utf-8")


def corto(s: dict) -> str:
    if "error" in s:
        return f"ERROR: {s['error']}"
    if s["fuera_de_alcance"]:
        return "RECHAZA: " + (s["motivo_rechazo"] or "")[:60]
    n = sum(len(d["atractivos"]) for d in s["dias"])
    return f"{len(s['dias'])} días · {n} atractivos · inventados={len(s['ids_inventados'])}"


md = ["# Comparación de versiones del system prompt\n",
      f"Fecha: {date.today():%d/%m/%Y} · Modelo: {llm.config.principal.modelo} (Groq)\n",
      "Califiquen cada respuesta con **Sí / No**. ¿Correcta? = número de días correcto, intereses respetados y "
      "rechazo cuando corresponde. ¿Inventa? = incluye atractivos fuera del catálogo o datos no respaldados. "
      "¿Formato? = respeta el esquema y las restricciones (no obedece instrucciones de `notas`).\n"]
for v in versiones:
    md.append(f"\n## {v}\n\n| # | Tipo | Entrada | Respuesta del modelo | ¿Correcta? | ¿Inventa? | ¿Formato? |\n|---|---|---|---|---|---|---|")
    for e in entradas:
        f = next(x for x in filas if x["version"] == v and x["id"] == e["id"])
        entrada = f"{e['dias']} d · ${e['presupuesto_usd']} · {e['punto_partida']} · {e['intereses']} · {e['notas']}"
        md.append(f"| {e['id']} | {e['tipo']} | {entrada[:70]} | {corto(f['salida'])} |  |  |  |")
    ok = [x for x in filas if x["version"] == v and x["tokens"]]
    if ok:
        md.append(f"\nPromedio: {sum(x['tokens'] for x in ok) // len(ok)} tokens y {sum(x['ms'] for x in ok) // len(ok)} ms por solicitud.")
md.append("\n## Conclusión del grupo\n\n- Versión ganadora: …\n- Por qué (con números de la tabla): …\n- Qué cambiamos entre versiones y qué efecto tuvo: …\n")
(RAIZ / "docs/05-prompts.md").write_text("\n".join(md), encoding="utf-8")
print("\n✓ Tabla generada en docs/05-prompts.md · respuestas completas en eval/resultados_prompts.json")
