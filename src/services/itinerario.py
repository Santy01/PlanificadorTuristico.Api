"""Construye el itinerario: el modelo PROPONE (qué atractivos y en qué orden) y el código DISPONE
(valida contra el catálogo, reparte la jornada, calcula costos y arma la respuesta).
"""
from __future__ import annotations

import json
import logging
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from typing import Iterator

from pydantic import ValidationError

from src.catalogo import Atractivo
from src.schemas import (
    Actividad, Alternativa, DiaItinerario, ItinerarioModelo, RespuestaItinerario, SolicitudItinerario,
)
from src.services.clima import ClienteClima, no_disponible
from src.services.llm import ClienteLLM, ProveedorNoDisponible, SalidaInvalida, cargar_prompt

PROMPT = "system_v3"  # la versión ganadora de la comparación de prompts (docs/05-prompts.md)
JORNADA_MAX_H = 8.0
DURACION_POR_DEFECTO_H = 2.0  # cuando la duración del catálogo está POR VERIFICAR


TIPOS = {"natur": "natural", "cultur": "cultural", "gastron": "gastronómico"}
NL = chr(10)
ABREVIATURA_TIPO = {"natural": "n", "cultural": "c", "gastronómico": "g"}


def _sin_tildes(texto: str) -> str:
    return unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().lower()


def atractivos_para_el_modelo(s: SolicitudItinerario, catalogo: dict[str, Atractivo]) -> list[Atractivo]:
    """Solo se envían al modelo los tipos que le interesan al visitante: menos tokens (el plan gratuito de Groq
    limita a 8000 por minuto) y menos distracciones. Si no se reconoce ningún interés, o quedarían muy pocos
    atractivos para los días pedidos, se envía todo el catálogo."""
    pedidos = {t for i in s.intereses for k, t in TIPOS.items() if _sin_tildes(i).startswith(k)}
    elegidos = [a for a in catalogo.values() if a.tipo in pedidos] if pedidos else []
    return elegidos if len(elegidos) >= 4 * s.dias else list(catalogo.values())


def contexto_usuario(s: SolicitudItinerario, catalogo: dict[str, Atractivo]) -> str:
    """Mensaje de usuario: parámetros + catálogo. El texto libre va delimitado como DATOS, no como órdenes.
    Catálogo compacto, agrupado por provincia:  id|cantón|tipo|horas|calidad
    (tipo: n natural, c cultural, g gastronómico; «?» = dato faltante; calidad = estado de verificación)."""
    por_provincia: dict[str, list[str]] = {}
    for a in atractivos_para_el_modelo(s, catalogo):
        horas = "?" if a.duracion_h is None else f"{a.duracion_h:g}"
        por_provincia.setdefault(a.provincia, []).append(
            f"{a.id}|{a.canton or '?'}|{ABREVIATURA_TIPO.get(a.tipo, a.tipo)}|{horas}|{a.estado_verificacion[0]}")
    filas = NL.join(f"## {prov}" + NL + NL.join(lineas) for prov, lineas in por_provincia.items())
    peticion = {"dias": s.dias, "presupuesto_usd": s.presupuesto_usd, "punto_partida": s.punto_partida,
                "intereses": s.intereses, "notas": s.notas}
    return (
        "<peticion>" + NL + json.dumps(peticion, ensure_ascii=False) + NL + "</peticion>" + NL
        + '<catalogo formato="id|canton|tipo|horas|calidad">' + NL + filas + NL + "</catalogo>"
    )


def _fila(a: Atractivo, orden: int, motivo: str) -> Actividad:
    return Actividad(
        orden=orden, atractivo_id=a.id, nombre=a.nombre, canton=a.canton, provincia=a.provincia,
        tipo=a.tipo, motivo=motivo, duracion_h=a.duracion_h or DURACION_POR_DEFECTO_H,
        duracion_verificada=a.duracion_h is not None, costo_usd=a.costo_usd,
        costo_aproximado=a.costo_aproximado, costo_texto=a.costo_texto, fuente=a.fuente,
        url_fuente=list(a.url_fuente), estado_verificacion=a.estado_verificacion,
        precision_coord=a.precision_coord if a.latitud is not None else None, nota=a.notas,
        latitud=a.latitud, longitud=a.longitud,
    )


def armar_itinerario(propuesta: ItinerarioModelo, s: SolicitudItinerario,
                     catalogo: dict[str, Atractivo]) -> RespuestaItinerario:
    """Aplica las reglas del sistema sobre la propuesta del modelo."""
    avisos: list[str] = []
    dias: dict[int, list[Actividad]] = {n: [] for n in range(1, s.dias + 1)}
    horas: dict[int, float] = {n: 0.0 for n in dias}
    vistos: set[str] = set()
    inventados = repetidos = movidos = descartados = 0

    for dia in sorted(propuesta.dias, key=lambda d: d.numero):
        for elegido in dia.atractivos:
            a = catalogo.get(elegido.id)
            if a is None:                       # RNF-06: 0 atractivos fuera del catálogo
                inventados += 1
                continue
            if a.id in vistos:
                repetidos += 1
                continue
            vistos.add(a.id)
            dur = a.duracion_h or DURACION_POR_DEFECTO_H
            base = dia.numero if dia.numero in dias else 1
            candidatos = [*range(base, s.dias + 1), *range(1, base)]
            destino = next((n for n in candidatos if not dias[n] or horas[n] + dur <= JORNADA_MAX_H), None)
            if destino is None:
                descartados += 1
                continue
            movidos += destino != base
            horas[destino] += dur
            dias[destino].append(_fila(a, len(dias[destino]) + 1, elegido.motivo))

    if inventados:
        avisos.append(f"Se descartaron {inventados} atractivo(s) que no pertenecen al catálogo verificado.")
    if repetidos:
        avisos.append(f"Se quitaron {repetidos} visita(s) repetida(s).")
    if movidos:
        avisos.append(f"Se redistribuyeron {movidos} actividad(es) para no superar {JORNADA_MAX_H:g} h por día.")
    if descartados:
        avisos.append(f"{descartados} actividad(es) no cupieron en los {s.dias} día(s) solicitados.")

    resultado = [DiaItinerario(numero=n, actividades=acts, horas_total=horas[n],
                               fecha=s.fecha_inicio + timedelta(days=n - 1) if s.fecha_inicio else None,
                               costo_parcial_usd=sum(x.costo_usd or 0 for x in acts))
                 for n, acts in dias.items()]
    actividades = [x for d in resultado for x in d.actividades]
    if not actividades:
        return RespuestaItinerario(
            estado="revision_humana", advertencias=avisos,
            mensaje="No pudimos armar un itinerario con atractivos verificados para esta solicitud.")

    for d in resultado:
        if not d.actividades:
            avisos.append(f"El día {d.numero} quedó sin actividades.")
    sin_costo = [x for x in actividades if x.costo_usd is None]
    if sin_costo:
        avisos.append(f"El costo de {len(sin_costo)} actividad(es) está por verificar y no se suma al total.")
    aprox = [x for x in actividades if x.costo_usd is not None and x.costo_aproximado]
    if aprox:
        avisos.append(f"{len(aprox)} costo(s) son aproximados (rango, «desde» o inferido); se usó el valor más alto.")
    sin_fuente = [x for x in actividades if x.estado_verificacion == "C"]
    if sin_fuente:
        avisos.append(f"{len(sin_fuente)} atractivo(s) tienen información aún sin fuente verificada.")
    sin_dur = [x for x in actividades if not x.duracion_verificada]
    if sin_dur:
        avisos.append(f"Se asumieron {DURACION_POR_DEFECTO_H:g} h para {len(sin_dur)} actividad(es) sin duración verificada.")
    total = sum(d.costo_parcial_usd for d in resultado)
    excedido = total > s.presupuesto_usd
    if excedido:
        avisos.append("El costo estimado supera el presupuesto indicado; considere menos actividades o días.")
    return RespuestaItinerario(
        estado="ok", mensaje="Itinerario generado con atractivos del catálogo verificado.",
        dias=resultado, costo_total_usd=total, costo_parcial=bool(sin_costo), presupuesto_excedido=excedido,
        supuestos=propuesta.supuestos, advertencias=avisos,
    )


ORDEN_CALIDAD = {"A": 0, "A_parcial": 1, "B": 2, "C": 3}
MAX_ALTERNATIVAS = 3
log = logging.getLogger("itinerario")


def _alternativas(dia: DiaItinerario, catalogo: dict[str, Atractivo], usados: set[str]) -> list[Alternativa]:
    """Atractivos NO naturales de las mismas provincias del día, que no estén ya en el itinerario.
    Se prefieren los de mejor calidad de verificación y se evitan los de calidad C si hay otros."""
    provincias = {x.provincia for x in dia.actividades}
    candidatos = sorted(
        (a for a in catalogo.values() if a.provincia in provincias and a.tipo != "natural" and a.id not in usados),
        key=lambda a: ORDEN_CALIDAD.get(a.estado_verificacion, 3))
    if any(a.estado_verificacion != "C" for a in candidatos):
        candidatos = [a for a in candidatos if a.estado_verificacion != "C"]
    return [Alternativa(atractivo_id=a.id, nombre=a.nombre, canton=a.canton, provincia=a.provincia, tipo=a.tipo,
                        estado_verificacion=a.estado_verificacion,
                        motivo="Actividad no natural de la misma provincia; confirme si es bajo techo.")
            for a in candidatos[:MAX_ALTERNATIVAS]]


def agregar_clima(resp: RespuestaItinerario, catalogo: dict[str, Atractivo], clima: ClienteClima) -> None:
    """Agrega el pronóstico a cada día. NUNCA rompe el itinerario: ante cualquier falla el día queda con
    «clima no disponible». Pronostica el lugar principal del día: la primera actividad con coordenadas."""
    try:
        usados = {x.atractivo_id for d in resp.dias for x in d.actividades}

        def pedir(d: DiaItinerario):
            ref = next((x for x in d.actividades if x.latitud is not None and x.longitud is not None), None)
            c = clima.pronostico(ref.latitud if ref else None, ref.longitud if ref else None, d.fecha)
            if ref and c.disponible:
                c.lugar_referencia = ref.nombre
            return c

        with ThreadPoolExecutor(max_workers=max(1, len(resp.dias))) as ex:
            resultados = list(ex.map(pedir, resp.dias))
        for d, c in zip(resp.dias, resultados):
            d.clima = c
            if c.disponible and c.lluvia_intensa and any(x.tipo == "natural" for x in d.actividades):
                d.alternativas = _alternativas(d, catalogo, usados)
                resp.advertencias.append(
                    f"Día {d.numero}: se pronostica lluvia intensa y hay actividades al aire libre. "
                    "Considera las alternativas sugeridas." if d.alternativas else
                    f"Día {d.numero}: se pronostica lluvia intensa y hay actividades al aire libre.")
        if any(not c.disponible for c in resultados) and resp.dias and resp.dias[0].fecha is not None:
            resp.advertencias.append("El pronóstico no está disponible para algunos días.")
    except Exception:  # noqa: BLE001 — respaldo final: el clima jamás debe hacer fallar la solicitud
        log.warning("clima_enriquecimiento_fallo", exc_info=True)
        for d in resp.dias:
            d.clima = no_disponible("El servicio de clima no respondió.", d.fecha)


def generar_itinerario(llm: ClienteLLM, s: SolicitudItinerario, catalogo: dict[str, Atractivo],
                       clima: ClienteClima | None = None) -> RespuestaItinerario:
    """Lanza ProveedorNoDisponible si el modelo no responde; SalidaInvalida pasa a revisión humana."""
    try:
        r = llm.generar_json(cargar_prompt(PROMPT), contexto_usuario(s, catalogo), ItinerarioModelo)
    except SalidaInvalida as e:
        return RespuestaItinerario(estado="revision_humana", mensaje=e.mensaje_usuario)
    p = r.datos
    if p.fuera_de_alcance:
        return RespuestaItinerario(
            estado="rechazado", proveedor=r.proveedor,
            mensaje=p.motivo_rechazo or "Esta solicitud está fuera del alcance del planificador turístico.")
    resp = armar_itinerario(p, s, catalogo)
    resp.proveedor = r.proveedor
    if clima is not None and resp.estado == "ok":
        agregar_clima(resp, catalogo, clima)
    return resp


def _limpiar(texto: str) -> str:
    texto = texto.strip()
    if texto.startswith("```"):
        texto = texto.strip("`").removeprefix("json").strip()
    return texto


def stream_itinerario(llm: ClienteLLM, s: SolicitudItinerario, catalogo: dict[str, Atractivo],
                      clima: ClienteClima | None = None) -> Iterator[tuple[str, object]]:
    """Genera eventos (nombre, dato) para SSE:
      ("texto", trozo)           mientras el modelo escribe (el frontend lo muestra tal cual llega)
      ("itinerario", respuesta)  el resultado YA validado por el código; es lo único que se debe dibujar
      ("error", mensaje)         si el proveedor no está disponible
    El texto en vivo es solo progreso: nada de él se muestra como definitivo sin pasar por armar_itinerario."""
    acumulado: list[str] = []
    try:
        try:
            for trozo in llm.generar_stream(cargar_prompt(PROMPT),
                                            [{"role": "user", "content": contexto_usuario(s, catalogo)}], ItinerarioModelo):
                acumulado.append(trozo)
                yield "texto", trozo
        except ProveedorNoDisponible:
            acumulado = []  # el flujo falló (429, JSON inválido del modelo, corte): se intenta por la vía normal
        p = None
        if acumulado:
            try:
                p = ItinerarioModelo.model_validate_json(_limpiar("".join(acumulado)))
            except ValidationError:
                p = None
        if p is None:
            # Sin flujo utilizable: la vía no-stream reintenta con espera, corrige y valida.
            yield "itinerario", generar_itinerario(llm, s, catalogo, clima)
            return
        if p.fuera_de_alcance:
            yield "itinerario", RespuestaItinerario(
                estado="rechazado",
                mensaje=p.motivo_rechazo or "Esta solicitud está fuera del alcance del planificador turístico.")
            return
        resp = armar_itinerario(p, s, catalogo)
        if clima is not None and resp.estado == "ok":
            agregar_clima(resp, catalogo, clima)
        yield "itinerario", resp
    except ProveedorNoDisponible as e:
        yield "error", e.mensaje_usuario
    except Exception:  # noqa: BLE001 — con el flujo ya iniciado no hay HTTP 500 posible: se avisa por un evento
        log.exception("stream_itinerario_fallo")
        yield "error", "Ocurrió un problema al generar el itinerario. Inténtalo de nuevo."
