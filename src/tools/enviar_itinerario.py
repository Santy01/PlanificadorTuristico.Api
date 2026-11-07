"""Herramienta `enviar_itinerario` (CON CONFIRMACIÓN): envía el itinerario actual al correo del visitante.

Es la única acción que SALE del sistema, por eso está en REQUIEREN_OK: el bucle se detiene, la interfaz muestra
qué se enviará y a quién, y solo se ejecuta si el visitante aprueba (POST /agente/confirmar/{id}).

Modo simulado: el proyecto no tiene servidor de correo. El envío queda en una bandeja de salida
(logs/bandeja_salida.jsonl) con el correo ENMASCARADO (RNF-10: no se guardan datos personales identificables).
Conectar SMTP real sería reemplazar `_entregar`, sin tocar el agente ni la confirmación.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.schemas import RespuestaItinerario

BANDEJA = Path("logs") / "bandeja_salida.jsonl"
_CORREO = re.compile(r"^[^@\s<>]+@[^@\s<>]+\.[A-Za-z]{2,}$")


class EnviarItinerarioIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    correo: str = Field(max_length=254, description="Correo que el visitante escribió en la conversación")

    @field_validator("correo")
    @classmethod
    def correo_valido(cls, v: str) -> str:
        v = v.strip()
        if not _CORREO.match(v):
            raise ValueError("no es un correo válido")
        return v


class EnviarItinerarioOut(BaseModel):
    enviado: bool
    destino: str          # enmascarado
    modo: str = "simulado"
    aviso: str


ESQUEMA = {"type": "function", "function": {
    "name": "enviar_itinerario",
    "description": "Envía el itinerario actual al correo del visitante. Requiere que el visitante lo apruebe en "
                   "la interfaz: úsala solo si lo pidió y escribió su correo.",
    "parameters": EnviarItinerarioIn.model_json_schema(),
}}


def enmascarar(correo: str) -> str:
    usuario, _, dominio = correo.partition("@")
    return f"{usuario[:1]}***@{dominio}"


def describir(d: EnviarItinerarioIn, it: RespuestaItinerario) -> str:
    """Lo que la interfaz muestra ANTES de aprobar: qué se hará y a quién (los argumentos reales, no los del texto)."""
    acts = sum(len(x.actividades) for x in it.dias)
    costo = f", costo estimado USD {it.costo_total_usd:.2f}" if it.costo_total_usd is not None else ""
    return f"Enviar el itinerario de {len(it.dias)} día(s) ({acts} actividades{costo}) a {d.correo}."


def _entregar(registro: dict) -> None:
    BANDEJA.parent.mkdir(exist_ok=True)
    with BANDEJA.open("a", encoding="utf-8") as f:
        f.write(json.dumps(registro, ensure_ascii=False) + "\n")


def enviar_itinerario(d: EnviarItinerarioIn, it: RespuestaItinerario) -> EnviarItinerarioOut:
    destino = enmascarar(d.correo)
    _entregar({"fecha": datetime.now(timezone.utc).isoformat(timespec="seconds"), "destino": destino,
               "dias": len(it.dias), "actividades": [x.atractivo_id for dia in it.dias for x in dia.actividades],
               "costo_total_usd": it.costo_total_usd})
    return EnviarItinerarioOut(enviado=True, destino=destino,
                               aviso=f"Itinerario enviado a {destino} (modo simulado: queda en la bandeja de salida).")
