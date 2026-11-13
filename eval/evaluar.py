"""Evaluación de la Entrega 3: lo esperado se escribió en los .jsonl ANTES de correr nada.

    python eval/evaluar.py rag                       # sin Groq (gratis): 15 preguntas, acierto y silencio
    python eval/evaluar.py solicitudes [--pausa 30]  # con Groq: 15 solicitudes de itinerario
    python eval/evaluar.py agente [--pausa 40]       # con Groq: escenarios A, B y D del agente

    python eval/evaluar.py solicitudes --url https://planificador.bhsolutions.cloud   # contra la app DESPLEGADA
    python eval/evaluar.py agente --url https://planificador.bhsolutions.cloud

Con `--url` los mismos casos y las mismas revisiones se corren por HTTP contra producción, sin claves en el cliente. Por
HTTP no se ven las herramientas que usó el agente: `recalcular` se deduce de `cambios` y `buscar_fragmentos` de
`fuentes`; `consultar_clima` no se puede comprobar y esa condición del caso A5 se omite (se avisa en la salida).

Cada modo imprime una línea por caso con lo que NO se cumplió y guarda el detalle en eval/resultados_<modo>.json.
`rag` termina con código 1 si el acierto baja de 0.7 o el silencio de 0.9 (se puede usar como compuerta).
El escenario C (tope de vueltas) no se puede forzar con el modelo real: lo cubre tests/test_agente.py.
Las pausas respetan el límite del plan gratuito de Groq (8000 tokens por minuto).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import date, timedelta
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.stdout.reconfigure(encoding="utf-8")

from src.catalogo import Atractivo, cargar_catalogo  # noqa: E402
from src.schemas import (  # noqa: E402
    AtractivoElegido, DiaModelo, ItinerarioModelo, RespuestaAgente, RespuestaItinerario, SolicitudAgente,
    SolicitudItinerario,
)
from src.tools.buscar_fragmentos import BuscarFragmentosIn, BuscarFragmentosOut  # noqa: E402

META_ACIERTO, META_SILENCIO = 0.7, 0.9
SALIDA = {"solicitudes": "resultados_solicitudes.json", "agente": "resultados_agente.json"}


def leer(nombre: str) -> list[dict]:
    return [json.loads(x) for x in (RAIZ / "eval" / nombre).read_text(encoding="utf-8").splitlines() if x.strip()]


class ErrorHTTP(Exception):
    """La API desplegada respondió con un estado que no es 200 (p. ej. 503 si fallan los dos proveedores)."""

    def __init__(self, estado: int, detalle: str):
        super().__init__(f"HTTP {estado}: {detalle}")
        self.estado = estado


def por_http(url: str, ruta: str, cuerpo: dict, modelo):
    """POST a la app desplegada y la respuesta validada con el mismo esquema Pydantic que usa la API. Ante un 429
    (límite por IP) espera lo que indica Retry-After y reintenta una vez."""
    for intento in (1, 2):
        req = urllib.request.Request(url.rstrip("/") + ruta, data=json.dumps(cuerpo).encode("utf-8"), method="POST",
                                     headers={"Content-Type": "application/json", "User-Agent": "evaluar-planificador/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return modelo(**json.loads(r.read().decode("utf-8")))
        except urllib.error.HTTPError as e:
            texto = e.read().decode("utf-8", "replace")
            if e.code == 429 and intento == 1:
                espera = int({k.lower(): v for k, v in e.headers.items()}.get("retry-after", "30")) + 1
                print(f"      (429: se espera {espera} s)", flush=True)
                time.sleep(espera)
                continue
            raise ErrorHTTP(e.code, texto[:160]) from e


def guardar(nombre: str, datos) -> None:
    (RAIZ / "eval" / nombre).write_text(json.dumps(datos, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


# ---------------------------------------------------------------- revisiones (funciones puras, probadas en tests/)
def revisar_pregunta(out: BuscarFragmentosOut, esperada: list[str] | None) -> list[str]:
    """Con fuente esperada: algún fragmento devuelto debe ser de ese atractivo. Sin fuente: debe volver vacía."""
    ids = [f.atractivo_id for f in out.fragmentos]
    if esperada is None:
        return [f"debía callar y devolvió {ids}"] if ids else []
    return [] if set(ids) & set(esperada) else [f"esperaba {esperada}, devolvió {ids or 'nada'}"]


def revisar_solicitud(r: RespuestaItinerario, s: SolicitudItinerario, espera: dict,
                      catalogo: dict[str, Atractivo]) -> list[str]:
    fallas = []
    if r.estado != espera["estado"]:
        fallas.append(f"estado {r.estado} (esperaba {espera['estado']})")
    if r.estado != "ok":
        return fallas
    acts = [a for d in r.dias for a in d.actividades]
    if len(r.dias) != s.dias:                                      # HU-02
        fallas.append(f"{len(r.dias)} días (pidió {s.dias})")
    if inventados := [a.atractivo_id for a in acts if a.atractivo_id not in catalogo]:   # RNF-06
        fallas.append(f"inventados {inventados}")
    if (n := espera.get("min_actividades")) and len(acts) < n:
        fallas.append(f"{len(acts)} actividad(es) (mínimo {n})")
    if (p := espera.get("incluye_provincia")) and p not in {a.provincia for a in acts}:
        fallas.append(f"ninguna actividad en {p}")
    if faltan := [i for i in espera.get("incluye", []) if i not in {a.atractivo_id for a in acts}]:
        fallas.append(f"no incluye {faltan}")
    if espera.get("dentro_presupuesto") and r.presupuesto_excedido:
        fallas.append(f"excede el presupuesto (USD {r.costo_total_usd} > {s.presupuesto_usd})")
    if (f := espera.get("fraccion_tipo")) and acts:
        pedidos = {i.lower() for i in s.intereses}
        frac = sum(a.tipo in pedidos for a in acts) / len(acts)
        if frac < f:
            fallas.append(f"solo {frac:.0%} de actividades del tipo pedido")
    if (n := espera.get("min_citas")) and sum(len(a.citas) for a in acts) < n:
        fallas.append(f"{sum(len(a.citas) for a in acts)} cita(s) (mínimo {n})")
    return fallas


def revisar_agente(r: RespuestaAgente, usadas: list[str], espera: dict) -> list[str]:
    fallas = []
    if r.estado != espera["estado"]:
        fallas.append(f"estado {r.estado} (esperaba {espera['estado']})")
    if faltan := [h for h in espera.get("usa", []) if h not in usadas]:
        fallas.append(f"no usó {faltan} (usó {usadas})")
    if (n := espera.get("min_cambios")) and len(r.cambios) < n:
        fallas.append(f"{len(r.cambios)} cambio(s)")
    if "max_cambios" in espera and len(r.cambios) > espera["max_cambios"]:
        fallas.append(f"hizo cambios que no correspondían: {r.cambios}")
    if (sale := espera.get("sale")) and any(a.atractivo_id == sale for d in r.itinerario.dias for a in d.actividades):
        fallas.append(f"{sale} sigue en el itinerario")
    if (n := espera.get("min_fuentes")) and len(r.fuentes) < n:
        fallas.append(f"{len(r.fuentes)} fuente(s)")
    if "max_fuentes" in espera and len(r.fuentes) > espera["max_fuentes"]:
        fallas.append(f"devolvió fuentes que no aplican: {[c.fuente for c in r.fuentes]}")
    if espera.get("sin_datos_sin_respaldo") and r.advertencias:
        fallas.append(f"datos sin respaldo: {r.advertencias}")
    if espera.get("sin_confirmacion") and r.confirmacion is not None:
        fallas.append(f"pidió confirmar {r.confirmacion.accion}")
    if (accion := espera.get("accion")) and (r.confirmacion is None or r.confirmacion.accion != accion):
        fallas.append(f"esperaba confirmación de {accion}")
    if (correo := espera.get("correo")) and (r.confirmacion is None or r.confirmacion.argumentos.get("correo") != correo):
        fallas.append("el correo de la confirmación no es el que escribió el visitante")
    return fallas


def _resumen(nombre: str, filas: list[dict]) -> None:
    ok = sum(not f["fallas"] for f in filas if "error" not in f)
    errores = sum("error" in f for f in filas)
    print(f"\n{nombre}: cumplen lo esperado {ok}/{len(filas)}" + (f"  (errores del proveedor: {errores})" if errores else ""))


# ---------------------------------------------------------------- modos
def rag() -> int:
    from src.main import obtener_catalogo_agente as obtener_catalogo, obtener_rag
    from src.tools.buscar_fragmentos import buscar_fragmentos
    cliente, catalogo = obtener_rag(), obtener_catalogo()
    if cliente is None:
        print("El RAG no está disponible (índice ausente o RAG_ACTIVO=false).")
        return 1
    filas = []
    for p in leer("preguntas.jsonl"):
        out = buscar_fragmentos(BuscarFragmentosIn(pregunta=p["pregunta"]), cliente, catalogo)
        fallas = revisar_pregunta(out, p["fuente_esperada"])
        filas.append({"id": p["id"], "con_fuente": p["fuente_esperada"] is not None, "fallas": fallas,
                      "devueltos": [f.atractivo_id for f in out.fragmentos]})
        print(p["id"], "ok" if not fallas else fallas)
    con = [f for f in filas if f["con_fuente"]]
    sin = [f for f in filas if not f["con_fuente"]]
    acierto = sum(not f["fallas"] for f in con) / max(1, len(con))
    silencio = sum(not f["fallas"] for f in sin) / max(1, len(sin))
    print(f"\nacierto (fuente esperada entre los fragmentos): {acierto:.0%} ({len(con)} preguntas)   "
          f"silencio correcto: {silencio:.0%} ({len(sin)} preguntas)   catálogo: {len(catalogo)} atractivos")
    guardar("resultados_rag_preguntas.json", {"acierto": acierto, "silencio": silencio,
                                              "catalogo": len(catalogo), "casos": filas})
    return 0 if acierto >= META_ACIERTO and silencio >= META_SILENCIO else 1


def solicitudes(pausa: float, casos: set[str] | None = None, url: str | None = None) -> int:
    from src.services.llm import ErrorLLM
    completo = cargar_catalogo()
    if url is None:
        from src.main import obtener_catalogo, obtener_llm, obtener_rag
        from src.services.itinerario import generar_itinerario
        llm, catalogo, cliente_rag = obtener_llm(), obtener_catalogo(), obtener_rag()
    filas = []
    for i, c in enumerate(c for c in leer("solicitudes.jsonl") if not casos or c["id"] in casos):
        if i:
            time.sleep(pausa)
        s = SolicitudItinerario(**c["solicitud"])
        t0 = time.monotonic()
        try:
            if url is None:
                r = generar_itinerario(llm, s, catalogo, None, cliente_rag)
            else:
                r = por_http(url, "/itinerario", s.model_dump(mode="json"), RespuestaItinerario)
        except (ErrorLLM, ErrorHTTP) as e:
            nombre = f"HTTP {e.estado}" if isinstance(e, ErrorHTTP) else type(e).__name__
            filas.append({"id": c["id"], "error": nombre, "fallas": [nombre]})
            print(c["id"], "ERROR", nombre, flush=True)
            continue
        fallas = revisar_solicitud(r, s, c["espera"], completo)
        acts = [a for d in r.dias for a in d.actividades]
        filas.append({"id": c["id"], "fallas": fallas, "estado": r.estado, "actividades": len(acts),
                      "citas": sum(len(a.citas) for a in acts), "costo_total_usd": r.costo_total_usd,
                      "ms": int((time.monotonic() - t0) * 1000), "mensaje": r.mensaje[:160]})
        print(c["id"], "ok" if not fallas else fallas, flush=True)
    _resumen("solicitudes", filas)
    guardar(SALIDA["solicitudes"], filas)
    return 0


def itinerario_base(catalogo: dict[str, Atractivo]) -> tuple[RespuestaItinerario, SolicitudItinerario]:
    """Itinerario fijo (sin modelo) sobre el que conversa el agente: el mismo en todos los casos."""
    from src.services.itinerario import armar_itinerario
    s = SolicitudItinerario(dias=2, presupuesto_usd=100, punto_partida="Ambato", intereses=["natural", "cultural"],
                            fecha_inicio=date.today() + timedelta(days=2))
    prop = ItinerarioModelo(fuera_de_alcance=False, motivo_rechazo=None, supuestos=[], dias=[
        DiaModelo(numero=1, atractivos=[AtractivoElegido(id="termas-de-la-virgen", motivo="Natural."),
                                        AtractivoElegido(id="quinta-de-juan-leon-mera", motivo="Cultural.")]),
        DiaModelo(numero=2, atractivos=[AtractivoElegido(id="laguna-de-quilotoa", motivo="Natural.")])])
    return armar_itinerario(prop, s, catalogo), s


def agente(pausa: float, casos: set[str] | None = None, url: str | None = None) -> int:
    import src.agente as ag
    from src.main import obtener_catalogo_agente as obtener_catalogo
    from src.services.llm import ErrorLLM
    catalogo = obtener_catalogo()
    base, s = itinerario_base(catalogo)
    usadas: list[str] = []
    tokens: list[int] = []
    if url is None:
        from src.main import obtener_clima, obtener_llm, obtener_rag
        llm, cliente_rag, clima = obtener_llm(), obtener_rag(), obtener_clima()
        original = llm.generar_con_herramientas

        def medido(mensajes, herramientas):
            r = original(mensajes, herramientas)
            usadas.extend(x.nombre for x in r.datos.llamadas)
            tokens.append((r.tokens_entrada or 0) + (r.tokens_salida or 0))
            return r
        llm.generar_con_herramientas = medido

    filas = []
    for i, c in enumerate(c for c in leer("agente_casos.jsonl") if not casos or c["id"] in casos):
        if i:
            time.sleep(pausa)
        usadas.clear()
        tokens.clear()
        sol = SolicitudAgente(mensaje=c["mensaje"], itinerario=base, solicitud=s)
        espera = dict(c["espera"])
        try:
            if url is None:
                r = ag.conversar(llm, sol, catalogo, cliente_rag, clima, ag.AlmacenPendientes(ttl_s=60))
            else:
                r = por_http(url, "/agente", sol.model_dump(mode="json"), RespuestaAgente)
                # Por HTTP no se ven las herramientas: se deducen de lo que dejaron en la respuesta.
                usadas.extend(h for h, dejo in (("recalcular", r.cambios), ("buscar_fragmentos", r.fuentes)) if dejo)
                if "consultar_clima" in espera.get("usa", []):
                    espera["usa"] = [h for h in espera["usa"] if h != "consultar_clima"]
                    print(f"      ({c['id']}: consultar_clima no se puede comprobar por HTTP; se omite esa condición)")
                if r.confirmacion is not None:  # no dejar acciones pendientes en producción
                    por_http(url, f"/agente/confirmar/{r.confirmacion.id}", {"aprobar": False}, RespuestaAgente)
        except (ErrorLLM, ErrorHTTP) as e:
            nombre = f"HTTP {e.estado}" if isinstance(e, ErrorHTTP) else type(e).__name__
            filas.append({"id": c["id"], "escenario": c["escenario"], "error": nombre, "fallas": [nombre]})
            print(c["id"], "ERROR", nombre, flush=True)
            continue
        fallas = revisar_agente(r, list(usadas), espera)
        filas.append({"id": c["id"], "escenario": c["escenario"], "fallas": fallas, "estado": r.estado,
                      "vueltas": r.vueltas, "herramientas": list(usadas), "tokens": sum(tokens),
                      "cambios": r.cambios, "fuentes": [x.fuente for x in r.fuentes], "advertencias": r.advertencias,
                      "respuesta": r.respuesta})
        print(c["id"], "ok" if not fallas else fallas, flush=True)
    _resumen("agente", filas)
    validas = [f for f in filas if "error" not in f]
    if validas:
        print(f"vueltas: media {sum(f['vueltas'] for f in validas) / len(validas):.1f}, "
              f"máximo {max(f['vueltas'] for f in validas)} (tope {ag.parametros().agente.max_iter})"
              + ("" if url else f"; tokens por caso: media {sum(f['tokens'] for f in validas) / len(validas):.0f}"))
    guardar(SALIDA["agente"], filas)
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("modo", choices=["rag", "solicitudes", "agente"])
    ap.add_argument("--pausa", type=float, default=None, help="segundos entre casos (Groq gratuito: 8000 tokens/min)")
    ap.add_argument("--casos", default="", help="solo estos ids, separados por coma (p. ej. D1,D2)")
    ap.add_argument("--salida", default=None,
                    help="archivo de resultados (por defecto eval/resultados_<modo>.json; con --url, "
                         "eval/resultados_produccion_<modo>.json)")
    ap.add_argument("--url", default=None, help="evalúa contra la app desplegada en vez de en proceso")
    a = ap.parse_args()
    casos = {x.strip() for x in a.casos.split(",") if x.strip()} or None
    if a.modo == "rag":
        if a.url:
            ap.error("el modo rag no admite --url: mide el índice local")
        sys.exit(rag())
    if a.url and not a.url.startswith(("http://", "https://")):
        ap.error("--url debe empezar por http:// o https://")
    if a.salida:
        SALIDA[a.modo] = a.salida
    elif a.url:
        SALIDA[a.modo] = f"resultados_produccion_{a.modo}.json"
    sys.exit(solicitudes(a.pausa if a.pausa is not None else 30, casos, a.url) if a.modo == "solicitudes"
             else agente(a.pausa if a.pausa is not None else 40, casos, a.url))
