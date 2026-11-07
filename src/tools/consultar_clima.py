"""Herramienta `consultar_clima` (libre, solo lectura): pronóstico de un día del itinerario.

El lugar y la fecha los pone el CÓDIGO (la primera actividad del día con coordenadas y la fecha del día), no el
modelo: así no puede pedir el clima de un sitio fuera del viaje. Además dice qué actividades del día son al aire
libre, para que el agente proponga `recalcular` si se pronostica lluvia intensa. Nunca lanza (ClienteClima tampoco).
"""
from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from src.schemas import RespuestaItinerario
from src.services.clima import ClienteClima


class ConsultarClimaIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dia: int = Field(ge=1, le=7, description="Número del día del itinerario")


class ConsultarClimaOut(BaseModel):
    dia: int
    disponible: bool
    motivo_no_disponible: str | None = None
    fecha: date | None = None
    lugar_referencia: str | None = None
    resumen: str | None = None
    temp_min_c: float | None = None
    temp_max_c: float | None = None
    prob_lluvia_pct: float | None = None
    lluvia_intensa: bool = False
    al_aire_libre: list[str] = Field(default_factory=list)  # ids de actividades naturales del día


ESQUEMA = {"type": "function", "function": {
    "name": "consultar_clima",
    "description": "Pronóstico del clima para un día del itinerario (lugar y fecha los toma del itinerario). "
                   "Indica si hay lluvia intensa y qué actividades del día son al aire libre.",
    "parameters": ConsultarClimaIn.model_json_schema(),
}}


def consultar_clima(d: ConsultarClimaIn, it: RespuestaItinerario, clima: ClienteClima | None) -> ConsultarClimaOut:
    dia = next((x for x in it.dias if x.numero == d.dia), None)
    if dia is None:
        return ConsultarClimaOut(dia=d.dia, disponible=False, motivo_no_disponible=f"El itinerario no tiene día {d.dia}.")
    al_aire_libre = [x.atractivo_id for x in dia.actividades if x.tipo == "natural"]
    if clima is None:
        return ConsultarClimaOut(dia=d.dia, disponible=False, motivo_no_disponible="El servicio de clima no está configurado.",
                                 al_aire_libre=al_aire_libre)
    ref = next((x for x in dia.actividades if x.latitud is not None and x.longitud is not None), None)
    c = clima.pronostico(ref.latitud if ref else None, ref.longitud if ref else None, dia.fecha)
    return ConsultarClimaOut(
        dia=d.dia, disponible=c.disponible, motivo_no_disponible=c.motivo_no_disponible, fecha=c.fecha or dia.fecha,
        lugar_referencia=ref.nombre if ref and c.disponible else None, resumen=c.resumen, temp_min_c=c.temp_min_c,
        temp_max_c=c.temp_max_c, prob_lluvia_pct=c.prob_lluvia_pct, lluvia_intensa=c.lluvia_intensa,
        al_aire_libre=al_aire_libre)
