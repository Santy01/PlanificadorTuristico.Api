"""Regla de alcance determinista (HU-09, RNF-07): se aplica ANTES de llamar al modelo.

Es la primera estación del patrón «regla → IA → persona»: lo que una regla reconoce no necesita al modelo (cero
tokens y siempre la misma respuesta). Lo que la regla no reconoce sigue al modelo, que tiene la misma instrucción en
el prompt como segunda barrera. Las reglas viven en config/alcance.yaml.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from src.parametros import ErrorParametros
from src.schemas import SolicitudItinerario

RUTA_ALCANCE = Path(__file__).resolve().parent.parent / "config" / "alcance.yaml"
log = logging.getLogger("alcance")


class _Regla(BaseModel):
    model_config = ConfigDict(extra="forbid")
    nombre: str
    patrones: list[str] = Field(min_length=1)
    mensaje: str = Field(min_length=10)


class _Archivo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reglas: list[_Regla] = Field(min_length=1)


@dataclass(frozen=True)
class Regla:
    nombre: str
    patrones: tuple[re.Pattern, ...]
    mensaje: str


@dataclass(frozen=True)
class Rechazo:
    regla: str
    mensaje: str


def normalizar(texto: str) -> str:
    return unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().lower()


def cargar_reglas(ruta: Path = RUTA_ALCANCE) -> tuple[Regla, ...]:
    try:
        datos = _Archivo.model_validate(yaml.safe_load(ruta.read_text(encoding="utf-8")) or {})
        return tuple(Regla(r.nombre, tuple(re.compile(p) for p in r.patrones), r.mensaje.strip()) for r in datos.reglas)
    except FileNotFoundError as e:
        raise ErrorParametros(f"No existe {ruta}: es obligatorio (reglas de alcance).") from e
    except (yaml.YAMLError, ValidationError, re.error) as e:
        raise ErrorParametros(f"{ruta} no es válido: {e}") from e


@lru_cache
def reglas() -> tuple[Regla, ...]:
    return cargar_reglas()


def revisar_alcance(s: SolicitudItinerario, reglas_: tuple[Regla, ...] | None = None) -> Rechazo | None:
    """El primer rechazo que aplique, o None si la solicitud puede seguir al modelo.
    Solo se revisan notas e intereses: el punto de partida puede estar fuera de la zona (se viaja desde ahí)."""
    texto = normalizar(" ".join([*s.intereses, s.notas or ""]))
    for r in reglas_ if reglas_ is not None else reglas():
        if any(p.search(texto) for p in r.patrones):
            log.info("alcance_rechazo regla=%s", r.nombre)  # sin el texto del visitante
            return Rechazo(r.nombre, r.mensaje)
    return None
