"""Agente de alcance controlado: el modelo dentro de un bucle que PIDE herramientas; el código decide si las ejecuta.

Lo que lo hace «de alcance controlado» son tres decisiones escritas aquí, no en el prompt (docs/09-decisiones.md):
  1. Lista cerrada — PERMITIDAS. El modelo solo ve esos esquemas, y si inventa otro nombre el código lo rechaza.
     Fuera de la lista, a propósito: reservar_hotel, cobrar_tarjeta (HU-09).
  2. Tope — `agente.max_iter` en config/parametros.yaml. Al llegar, responde «lo revisa un asesor».
  3. Confirmación — REQUIEREN_OK. El bucle se detiene, la interfaz muestra la acción con sus argumentos reales y
     solo se ejecuta si el visitante aprueba (POST /agente/confirmar/{id}).

Además: cada argumento se valida con Pydantic ANTES de ejecutar, una herramienta que falla devuelve un error al
modelo (no rompe el bucle) y cada decisión queda en logs/agente.jsonl (sin el texto del visitante).

El flujo que GENERA el itinerario no es un agente (es un flujo fijo: el modelo propone, el código dispone). El agente
trabaja sobre un itinerario ya generado, donde el camino no se puede escribir de antemano: «llueve», «está cerrado»,
«¿qué horario tiene?».
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from pydantic import BaseModel, ValidationError

from src.catalogo import Atractivo
from src.parametros import parametros
from src.schemas import Cita, Confirmacion, RespuestaAgente, RespuestaItinerario, SolicitudAgente, SolicitudItinerario
from src.services.clima import ClienteClima
from src.services.llm import ClienteLLM, LlamadaHerramienta, ProveedorNoDisponible, cargar_prompt
from src.services.rag import ClienteRAG
from src.tools import buscar_fragmentos as t_buscar
from src.tools import consultar_clima as t_clima
from src.tools import enviar_itinerario as t_enviar
from src.tools import recalcular as t_recalcular

PROMPT = "agente_v1"
TOPE = "No pude completar el ajuste del itinerario; un asesor turístico lo revisará."

# ---------------------------------------------------------------- auditoría
Path("logs").mkdir(exist_ok=True)
log = logging.getLogger("agente")
if not log.handlers:
    log.setLevel(logging.INFO)
    _f = logging.FileHandler("logs/agente.jsonl", encoding="utf-8")
    _f.setFormatter(logging.Formatter("%(message)s"))
    log.addHandler(_f)
# Las trazas de error van a otro logger (no hijo de «agente»): la auditoría queda en JSON, una línea por evento.
_errores = logging.getLogger("errores_agente")


def _auditar(**datos) -> None:
    """Quién decidió qué: vueltas, herramientas pedidas, rechazos y confirmaciones. Nunca el texto del visitante."""
    log.info(json.dumps({"ts": round(time.time(), 3), **datos}, ensure_ascii=False, default=str))


# ---------------------------------------------------------------- contexto y herramientas
@dataclass
class Contexto:
    """Lo que las herramientas leen y modifican. Vive en el servidor: el modelo nunca lo recibe completo."""
    itinerario: RespuestaItinerario
    solicitud: SolicitudItinerario | None
    catalogo: dict[str, Atractivo]
    rag: ClienteRAG | None
    clima: ClienteClima | None
    cambios: list[str] = field(default_factory=list)
    fuentes: dict[str, Cita] = field(default_factory=dict)


def _buscar(ctx: Contexto, d: t_buscar.BuscarFragmentosIn) -> BaseModel:
    out = t_buscar.buscar_fragmentos(d, ctx.rag, ctx.catalogo)
    for f in out.fragmentos:  # las fuentes que ve el visitante las arma el código, no el texto del modelo
        ctx.fuentes.setdefault(f.id, Cita(fragmento_id=f.id, texto=f.texto, fuente=f.fuente, url=f.url,
                                          tipo_fuente=f.tipo_fuente, estado_verificacion=f.estado_verificacion))
    return out


def _clima(ctx: Contexto, d: t_clima.ConsultarClimaIn) -> BaseModel:
    return t_clima.consultar_clima(d, ctx.itinerario, ctx.clima)


def _recalcular(ctx: Contexto, d: t_recalcular.RecalcularIn) -> BaseModel:
    presupuesto = ctx.solicitud.presupuesto_usd if ctx.solicitud else None
    nuevo, out = t_recalcular.recalcular(ctx.itinerario, d, ctx.catalogo, presupuesto)
    if out.aplicado:
        ctx.itinerario = nuevo
        ctx.cambios.append(out.aviso)
    return out


def _enviar(ctx: Contexto, d: t_enviar.EnviarItinerarioIn) -> BaseModel:
    return t_enviar.enviar_itinerario(d, ctx.itinerario)


@dataclass(frozen=True)
class Herramienta:
    entrada: type[BaseModel]
    ejecutar: Callable[[Contexto, BaseModel], BaseModel]
    esquema: dict
    describir: Callable[[Contexto, BaseModel], str] | None = None  # texto de la confirmación (si requiere OK)


# 1 · Lista cerrada: nombre → herramienta. Lo que no está aquí no existe para el modelo.
PERMITIDAS: dict[str, Herramienta] = {
    "buscar_fragmentos": Herramienta(t_buscar.BuscarFragmentosIn, _buscar, t_buscar.ESQUEMA),
    "consultar_clima": Herramienta(t_clima.ConsultarClimaIn, _clima, t_clima.ESQUEMA),
    "recalcular": Herramienta(t_recalcular.RecalcularIn, _recalcular, t_recalcular.ESQUEMA),
    "enviar_itinerario": Herramienta(t_enviar.EnviarItinerarioIn, _enviar, t_enviar.ESQUEMA,
                                     describir=lambda ctx, d: t_enviar.describir(d, ctx.itinerario)),
}
# 3 · Confirmación: estas se detienen y esperan al visitante.
REQUIEREN_OK = frozenset({"enviar_itinerario"})
ESQUEMAS = [h.esquema for h in PERMITIDAS.values()]
assert REQUIEREN_OK <= PERMITIDAS.keys()


@dataclass(frozen=True)
class Pendiente:
    tool_call_id: str
    nombre: str
    datos: BaseModel


@dataclass(frozen=True)
class Salida:
    estado: str  # respondido | requiere_confirmacion | tope_alcanzado
    respuesta: str | None
    vueltas: int
    pendiente: Pendiente | None = None
    advertencias: tuple[str, ...] = ()


# ---------------------------------------------------------------- verificación de datos de la respuesta
# Prueba con Groq: ante «¿qué horario tiene el Pailón?» el modelo respondió «según la ficha oficial abre de 9:00 a
# 19:00», y la ficha no trae horario. El prompt no basta: el código revisa que cada HORA y cada MONTO en USD de la
# respuesta final aparezca en lo que el modelo recibió (itinerario, resultados de herramientas, mensajes del visitante).
_HORA = re.compile(r"\b([01]?\d|2[0-3])\s*[:h]\s*([0-5]\d)\b")
_MONTO = re.compile(r"(?:USD|US\$|\$)\s*(\d+(?:[.,]\d{1,2})?)", re.I)
_NUMERO = re.compile(r"\d+(?:[.,]\d+)?")
_PREFIJO_CORRECCION = "[Revisión automática del sistema]"
CORRECCION = (_PREFIJO_CORRECCION + " Tu respuesta menciona datos que no aparecen en el itinerario ni en "
              "los resultados de las herramientas: {datos}. Reescríbela sin esos datos; si el visitante los necesita, "
              "dile que no están verificados y que los confirme con la fuente oficial.")
AVISO_SIN_RESPALDO = "La respuesta menciona datos sin fuente verificada ({datos}); confírmalos con la fuente oficial."


def _num(texto: str) -> float:
    return float(texto.replace(",", "."))


def datos_sin_respaldo(respuesta: str, respaldo: list[str]) -> list[str]:
    """Horas y montos de la respuesta que no aparecen en ningún texto de respaldo (en el orden en que aparecen)."""
    base = " ".join(respaldo)
    horas = {(int(h), int(m)) for h, m in _HORA.findall(base)}
    numeros = {_num(n) for n in _NUMERO.findall(base)}
    faltan = [f"{int(h)}:{m}" for h, m in _HORA.findall(respuesta) if (int(h), int(m)) not in horas]
    faltan += [f"USD {n}" for n in _MONTO.findall(respuesta) if _num(n) not in numeros]
    return list(dict.fromkeys(faltan))


def _respaldo(mensajes: list[dict]) -> list[str]:
    """Lo que el modelo RECIBIÓ: system (itinerario), herramientas y mensajes del visitante. No sus propias respuestas
    ni el pedido de corrección (que repite los datos inventados y los haría pasar por respaldados)."""
    return [m["content"] for m in mensajes
            if m["role"] in ("system", "tool", "user") and isinstance(m.get("content"), str)
            and not m["content"].startswith(_PREFIJO_CORRECCION)]


def _json(datos: dict) -> str:
    return json.dumps(datos, ensure_ascii=False)


def _atender(ll: LlamadaHerramienta, ctx: Contexto, hay_pendiente: bool, vuelta: int) -> tuple[str | None, Pendiente | None]:
    """(contenido del mensaje `tool`, pendiente). Valida todo antes de ejecutar; nunca lanza."""
    if ll.nombre not in PERMITIDAS:
        _auditar(evento="rechazada", motivo="no_permitida", herramienta=ll.nombre[:60], vuelta=vuelta)
        return _json({"error": f"herramienta no permitida: {ll.nombre[:60]}",
                      "permitidas": sorted(PERMITIDAS)}), None
    h = PERMITIDAS[ll.nombre]
    try:
        datos = h.entrada.model_validate(json.loads(ll.argumentos or "{}"))
    except (json.JSONDecodeError, ValidationError, TypeError) as e:
        detalle = ([f"{'.'.join(map(str, x['loc'])) or 'argumentos'}: {x['msg']}" for x in e.errors()]
                   if isinstance(e, ValidationError) else ["los argumentos no son un JSON válido"])
        _auditar(evento="rechazada", motivo="argumentos_invalidos", herramienta=ll.nombre, vuelta=vuelta)
        return _json({"error": "argumentos inválidos", "detalle": detalle}), None
    if ll.nombre in REQUIEREN_OK:
        if hay_pendiente:
            return _json({"error": "solo una acción con confirmación por turno"}), None
        _auditar(evento="pausa_confirmacion", herramienta=ll.nombre, vuelta=vuelta)
        return None, Pendiente(ll.id, ll.nombre, datos)
    try:
        out = h.ejecutar(ctx, datos)
    except Exception:  # noqa: BLE001 — una herramienta que falla no rompe el bucle: el modelo recibe el error
        _errores.warning("herramienta_fallo %s", ll.nombre, exc_info=True)
        _auditar(evento="fallo_herramienta", herramienta=ll.nombre, vuelta=vuelta)
        return _json({"error": "la herramienta falló; no la repitas, explícalo al visitante"}), None
    _auditar(evento="ejecutada", herramienta=ll.nombre, vuelta=vuelta,
             aplicado=getattr(out, "aplicado", None))
    return out.model_dump_json(), None


def ejecutar_agente(llm: ClienteLLM, mensajes: list[dict], ctx: Contexto, max_iter: int | None = None) -> Salida:
    """El bucle. `mensajes` se va completando (assistant + tool) y se conserva si queda una acción pendiente."""
    max_iter = max_iter or parametros().agente.max_iter        # 2 · Tope
    corregido = False
    for vuelta in range(1, max_iter + 1):
        r = llm.generar_con_herramientas(mensajes, ESQUEMAS)
        msg = r.datos
        _auditar(evento="vuelta", vuelta=vuelta, proveedor=r.proveedor, tokens_entrada=r.tokens_entrada,
                 tokens_salida=r.tokens_salida, latencia_ms=r.latencia_ms, pide=[x.nombre[:60] for x in msg.llamadas])
        if not msg.llamadas:                                     # sin pedidos: terminó
            texto = (msg.contenido or "").strip() or TOPE
            faltan = datos_sin_respaldo(texto, _respaldo(mensajes))
            if faltan and not corregido and vuelta < max_iter:   # UNA corrección, dentro del mismo tope
                corregido = True
                _auditar(evento="correccion_datos", vuelta=vuelta, cantidad=len(faltan))
                mensajes += [{"role": "assistant", "content": texto},
                             {"role": "user", "content": CORRECCION.format(datos=", ".join(faltan))}]
                continue
            if faltan:
                _auditar(evento="datos_sin_respaldo", vuelta=vuelta, cantidad=len(faltan))
            return Salida("respondido", texto, vuelta,
                          advertencias=(AVISO_SIN_RESPALDO.format(datos=", ".join(faltan)),) if faltan else ())
        mensajes.append(msg.como_mensaje())
        pendiente: Pendiente | None = None
        for ll in msg.llamadas:
            contenido, p = _atender(ll, ctx, pendiente is not None, vuelta)
            if p is not None:
                pendiente = p                                    # su respuesta se agrega cuando el visitante decida
                continue
            mensajes.append({"role": "tool", "tool_call_id": ll.id, "content": contenido})
        if pendiente is not None:
            return Salida("requiere_confirmacion", None, vuelta, pendiente)
    _auditar(evento="tope", vueltas=max_iter)
    return Salida("tope_alcanzado", TOPE, max_iter)


# ---------------------------------------------------------------- acciones pendientes
class AlmacenPendientes:
    """Acciones que esperan la decisión del visitante. En memoria con vencimiento: sirve con UN proceso de uvicorn
    (como en docker-compose). Con varios procesos haría falta un almacén compartido (Redis, base de datos).
    `tomar` saca el registro: una acción se decide una sola vez (idempotencia)."""

    def __init__(self, ttl_s: float, reloj: Callable[[], float] = time.monotonic):
        self.ttl_s, self._reloj = ttl_s, reloj
        self._datos: dict[str, tuple[float, dict]] = {}
        self._lock = threading.Lock()

    def guardar(self, registro: dict) -> str:
        id_ = uuid.uuid4().hex
        with self._lock:
            self._purgar()
            self._datos[id_] = (self._reloj() + self.ttl_s, registro)
        return id_

    def tomar(self, id_: str) -> dict | None:
        with self._lock:
            self._purgar()
            item = self._datos.pop(id_, None)
        return item[1] if item else None

    def _purgar(self) -> None:
        ahora = self._reloj()
        for k in [k for k, (vence, _) in self._datos.items() if vence <= ahora]:
            del self._datos[k]


# ---------------------------------------------------------------- servicio que usan los endpoints
def resumen_itinerario(it: RespuestaItinerario, catalogo: dict[str, Atractivo],
                       s: SolicitudItinerario | None) -> str:
    """El itinerario como lo ve el modelo: ids y datos del CATÁLOGO, nunca el texto libre que envió el cliente
    (nombres o motivos alterados serían otra vía de inyección)."""
    lineas = []
    if s is not None:
        lineas.append(f"Presupuesto: USD {s.presupuesto_usd:g}. Punto de partida: {s.punto_partida[:100]}.")
    if it.costo_total_usd is not None:
        lineas.append(f"Costo estimado actual: USD {it.costo_total_usd:.2f}.")
    for d in it.dias:
        lineas.append(f"Día {d.numero} ({d.fecha.isoformat() if d.fecha else 'sin fecha'}):")
        for x in d.actividades:
            a = catalogo.get(x.atractivo_id)
            if a is None:
                lineas.append(f"- {x.atractivo_id[:80]} (no está en el catálogo verificado)")
                continue
            costo = f"USD {a.costo_usd:g}" if a.costo_usd is not None else "costo por verificar"
            lineas.append(f"- {a.id} | {a.nombre} | {a.canton or '-'}, {a.provincia} | {a.tipo} | "
                          f"{x.duracion_h:g} h | {costo}")
    return "\n".join(lineas)


def mensajes_iniciales(sol: SolicitudAgente, catalogo: dict[str, Atractivo]) -> list[dict]:
    system = (cargar_prompt(PROMPT) + "\n\n<itinerario_actual>\n"
              + resumen_itinerario(sol.itinerario, catalogo, sol.solicitud) + "\n</itinerario_actual>")
    n = parametros().agente.max_historial
    historial = [{"role": "user" if m.rol == "visitante" else "assistant", "content": m.texto}
                 for m in (sol.historial[-n:] if n else [])]
    return [{"role": "system", "content": system}, *historial, {"role": "user", "content": sol.mensaje}]


def _responder(salida: Salida, ctx: Contexto, mensajes: list[dict], almacen: AlmacenPendientes) -> RespuestaAgente:
    confirmacion = None
    if salida.pendiente is not None:
        p = salida.pendiente
        h = PERMITIDAS[p.nombre]
        id_ = almacen.guardar({"mensajes": mensajes, "ctx": ctx, "pendiente": p})
        confirmacion = Confirmacion(
            id=id_, accion=p.nombre, argumentos=p.datos.model_dump(mode="json"),
            descripcion=h.describir(ctx, p.datos) if h.describir else f"Ejecutar {p.nombre}.",
            expira_en_s=int(almacen.ttl_s))
    return RespuestaAgente(estado=salida.estado, respuesta=salida.respuesta, itinerario=ctx.itinerario,
                           cambios=list(ctx.cambios), fuentes=list(ctx.fuentes.values()),
                           confirmacion=confirmacion, advertencias=list(salida.advertencias),
                           vueltas=salida.vueltas)


def conversar(llm: ClienteLLM, sol: SolicitudAgente, catalogo: dict[str, Atractivo], rag: ClienteRAG | None,
              clima: ClienteClima | None, almacen: AlmacenPendientes) -> RespuestaAgente:
    """Lanza ProveedorNoDisponible si el modelo no responde (el endpoint lo traduce a 503)."""
    ctx = Contexto(itinerario=sol.itinerario, solicitud=sol.solicitud, catalogo=catalogo, rag=rag, clima=clima)
    mensajes = mensajes_iniciales(sol, catalogo)
    _auditar(evento="inicio", dias=len(sol.itinerario.dias), historial=len(sol.historial))
    return _responder(ejecutar_agente(llm, mensajes, ctx), ctx, mensajes, almacen)


def confirmar(llm: ClienteLLM, id_: str, aprobar: bool, almacen: AlmacenPendientes) -> RespuestaAgente | None:
    """None si no hay acción pendiente con ese id (ya decidida o vencida). Recién aquí se ejecuta la acción."""
    reg = almacen.tomar(id_)
    if reg is None:
        return None
    ctx: Contexto = reg["ctx"]
    mensajes: list[dict] = reg["mensajes"]
    p: Pendiente = reg["pendiente"]
    if aprobar:
        try:
            out = PERMITIDAS[p.nombre].ejecutar(ctx, p.datos)
            contenido, resultado = out.model_dump_json(), getattr(out, "aviso", "Acción realizada.")
        except Exception:  # noqa: BLE001
            _errores.warning("confirmada_fallo %s", p.nombre, exc_info=True)
            contenido, resultado = _json({"error": "la acción falló"}), "La acción no se pudo completar."
    else:
        contenido = _json({"rechazado_por_el_visitante": True, "aviso": "No se ejecutó: el visitante no lo aprobó."})
        resultado = "No se realizó la acción: no la aprobaste."
    _auditar(evento="aprobada" if aprobar else "rechazada_por_visitante", herramienta=p.nombre)
    mensajes.append({"role": "tool", "tool_call_id": p.tool_call_id, "content": contenido})
    try:
        salida = ejecutar_agente(llm, mensajes, ctx)
    except ProveedorNoDisponible:
        # La decisión ya se aplicó: se informa el resultado aunque el modelo no pueda continuar la conversación.
        salida = Salida("respondido", resultado, 0)
    return _responder(salida, ctx, mensajes, almacen)
