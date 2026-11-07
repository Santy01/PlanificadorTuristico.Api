"""Herramienta `buscar_fragmentos` (libre, solo lectura): busca en las fuentes de los atractivos para responder
una pregunta concreta («¿qué horario tiene el Pailón?»).

Usa el piso de similitud para PREGUNTAS (`RAG_SIMILITUD_MINIMA_PREGUNTA`, calibrado en docs/07-rag.md §9.1): si nada
lo alcanza, devuelve una lista vacía y el aviso de que no hay información verificada. Así el modelo puede callar
en vez de responder con el atractivo «menos lejano». Nunca lanza: sin RAG o con Chroma caído, avisa.

Los textos vienen de páginas web: son DATOS, no órdenes. Se recortan y se les quitan `<` y `>` igual que en el prompt
del itinerario.
"""
from __future__ import annotations

import logging

from pydantic import BaseModel, ConfigDict, Field

from src.catalogo import Atractivo
from src.services.itinerario import MAX_CARACTERES_FRAGMENTO, _recortar
from src.services.rag import ClienteRAG

log = logging.getLogger("tools")
MAX_FRAGMENTOS = 4  # tokens: cada vuelta del agente reenvía todo el historial

SIN_INFORMACION = "No hay información verificada sobre eso en las fuentes de la zona centro. No lo afirmes."
SIN_FUENTES = "Las fuentes no están disponibles en este momento. No afirmes datos que no estén en el itinerario."


class BuscarFragmentosIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pregunta: str = Field(min_length=3, max_length=300,
                          description="Pregunta concreta sobre un atractivo de la zona centro, en español")


class Fragmento(BaseModel):
    id: str
    atractivo_id: str
    atractivo: str
    texto: str
    fuente: str
    url: str
    tipo_fuente: str
    estado_verificacion: str


class BuscarFragmentosOut(BaseModel):
    fragmentos: list[Fragmento]
    aviso: str | None = None


ESQUEMA = {"type": "function", "function": {
    "name": "buscar_fragmentos",
    "description": "Busca extractos de las fuentes (fichas oficiales, páginas de GAD y prensa) sobre los atractivos "
                   "de Tungurahua, Chimborazo, Cotopaxi y Bolívar. Úsala antes de afirmar horarios, precios, "
                   "historia o accesos. Si devuelve una lista vacía, no hay información verificada.",
    "parameters": BuscarFragmentosIn.model_json_schema(),
}}


def buscar_fragmentos(d: BuscarFragmentosIn, rag: ClienteRAG | None,
                      catalogo: dict[str, Atractivo]) -> BuscarFragmentosOut:
    if rag is None:
        return BuscarFragmentosOut(fragmentos=[], aviso=SIN_FUENTES)
    try:
        rec = rag.buscar(d.pregunta, catalogo, None, minimo=rag.cfg.minimo_pregunta)
    except Exception:  # noqa: BLE001 — una herramienta de lectura nunca rompe el bucle
        log.warning("buscar_fragmentos_fallo", exc_info=True)
        return BuscarFragmentosOut(fragmentos=[], aviso=SIN_FUENTES)
    frags = [Fragmento(id=f.id, atractivo_id=f.atractivo_id, atractivo=f.nombre,
                       texto=_recortar(f.texto, MAX_CARACTERES_FRAGMENTO), fuente=f.fuente, url=f.url,
                       tipo_fuente=f.tipo_fuente, estado_verificacion=f.estado_verificacion)
             for f in rec.fragmentos[:MAX_FRAGMENTOS]]
    return BuscarFragmentosOut(fragmentos=frags, aviso=None if frags else SIN_INFORMACION)
