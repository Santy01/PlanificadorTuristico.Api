"""Herramienta `recalcular` (HU-08): cambia UN atractivo de un día por otro del catálogo verificado.

El modelo entiende el cambio («llueve el día 2», «el museo está cerrado», «no me interesa la laguna»); el CÓDIGO
decide qué entra en su lugar. Es determinista: misma entrada, mismo reemplazo, y nunca un atractivo inventado.

Reglas (todas obligatorias):
  1. Misma provincia que el atractivo que sale.
  2. Que no esté ya en el viaje.
  3. Que quepa: dura como mucho lo que el que sale + `holgura_h`, y el día no supera la jornada máxima.
  4. Con lluvia, que no sea al aire libre (tipo `natural`).
Preferencias para elegir entre los que cumplen, en este orden: mismo cantón, mismo tipo (salvo con lluvia),
mejor verificado, costo conocido, más barato y, al final, el nombre (para que el desempate sea estable).

El itinerario original no se modifica: se devuelve una copia con el cambio, las horas y los costos recalculados
con la misma función que usa `armar_itinerario`.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from src.catalogo import Atractivo
from src.parametros import parametros
from src.schemas import RespuestaItinerario
from src.services.itinerario import ORDEN_CALIDAD, actividad_desde, totalizar

MOTIVO_TEXTO = {"lluvia": "por lluvia", "cerrado": "porque está cerrado", "preferencia": "a pedido del visitante"}


class RecalcularIn(BaseModel):
    """Lo que el modelo pide. Se valida ANTES de ejecutar: un día 0 o un motivo inventado se rechazan."""
    model_config = ConfigDict(extra="forbid")
    dia: int = Field(ge=1, le=7, description="Número del día del itinerario donde está el atractivo")
    quitar_id: str = Field(min_length=1, max_length=80, description="id EXACTO del atractivo que sale")
    motivo: Literal["lluvia", "cerrado", "preferencia"] = Field(
        description="lluvia: se pronostica lluvia; cerrado: el atractivo no abre; preferencia: el visitante no quiere ir")


class RecalcularOut(BaseModel):
    """Lo que vuelve al modelo: compacto (el itinerario completo lo conserva el código, no viaja en cada vuelta)."""
    aplicado: bool
    dia: int
    quitado_id: str
    reemplazo_id: str | None = None
    reemplazo_nombre: str | None = None
    horas_dia: float | None = None
    costo_dia_usd: float | None = None
    costo_total_usd: float | None = None
    aviso: str


ESQUEMA = {"type": "function", "function": {
    "name": "recalcular",
    "description": "Reemplaza un atractivo de un día del itinerario por otro del catálogo verificado (misma provincia, "
                   "que quepa en el día y, con lluvia, bajo techo). Úsala cuando llueve, el atractivo está cerrado "
                   "o el visitante no quiere ir. El reemplazo lo elige el sistema, no tú.",
    "parameters": RecalcularIn.model_json_schema(),
}}


def _duracion(a: Atractivo) -> float:
    return a.duracion_h or parametros().itinerario.duracion_por_defecto_h


def recalcular(it: RespuestaItinerario, d: RecalcularIn, catalogo: dict[str, Atractivo],
               presupuesto_usd: float | None = None) -> tuple[RespuestaItinerario, RecalcularOut]:
    """(itinerario resultante, resultado para el modelo). Si no se aplica, devuelve el MISMO itinerario sin tocar."""
    def sin_cambio(aviso: str) -> tuple[RespuestaItinerario, RecalcularOut]:
        return it, RecalcularOut(aplicado=False, dia=d.dia, quitado_id=d.quitar_id, aviso=aviso)

    if it.estado != "ok":
        return sin_cambio("Solo se puede recalcular un itinerario generado.")
    dia = next((x for x in it.dias if x.numero == d.dia), None)
    if dia is None:
        return sin_cambio(f"El itinerario no tiene día {d.dia}.")
    pos = next((i for i, x in enumerate(dia.actividades) if x.atractivo_id == d.quitar_id), None)
    if pos is None:
        return sin_cambio(f"Ese atractivo no está en el día {d.dia}.")

    sale = dia.actividades[pos]
    p = parametros()
    usados = {x.atractivo_id for un_dia in it.dias for x in un_dia.actividades}
    horas_resto = sum(x.duracion_h for i, x in enumerate(dia.actividades) if i != pos)
    tope = sale.duracion_h + p.recalcular.holgura_h
    candidatos = [a for a in catalogo.values()
                  if a.id not in usados
                  and a.provincia == sale.provincia
                  and (d.motivo != "lluvia" or a.tipo != "natural")
                  and _duracion(a) <= tope
                  and horas_resto + _duracion(a) <= p.itinerario.jornada_max_h]
    if not candidatos:
        return sin_cambio(f"No hay un reemplazo para {sale.nombre} en {sale.provincia} que cumpla las reglas; "
                          "lo revisa un asesor turístico.")
    candidatos.sort(key=lambda a: (
        a.canton != sale.canton,
        d.motivo != "lluvia" and a.tipo != sale.tipo,
        ORDEN_CALIDAD.get(a.estado_verificacion, 3),
        a.costo_usd is None,
        a.costo_usd or 0,
        a.nombre,
    ))
    entra = candidatos[0]

    nuevo = it.model_copy(deep=True)
    nuevo_dia = next(x for x in nuevo.dias if x.numero == d.dia)
    nuevo_dia.actividades[pos] = actividad_desde(
        entra, sale.orden, f"Reemplaza a {sale.nombre} {MOTIVO_TEXTO[d.motivo]}.")
    nuevo_dia.alternativas = [x for x in nuevo_dia.alternativas if x.atractivo_id != entra.id]
    totalizar(nuevo, presupuesto_usd)
    aviso = (f"Día {d.dia}: sale {sale.nombre} {MOTIVO_TEXTO[d.motivo]}; "
             f"entra {entra.nombre} ({entra.canton or entra.provincia}).")
    nuevo.advertencias.append(aviso)
    return nuevo, RecalcularOut(
        aplicado=True, dia=d.dia, quitado_id=sale.atractivo_id, reemplazo_id=entra.id, reemplazo_nombre=entra.nombre,
        horas_dia=nuevo_dia.horas_total, costo_dia_usd=nuevo_dia.costo_parcial_usd,
        costo_total_usd=nuevo.costo_total_usd, aviso=aviso)
