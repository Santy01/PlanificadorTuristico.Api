"""Parámetros de negocio leídos de config/parametros.yaml.

Regla del seminario: lo que cambia con el negocio (jornada, holguras, topes) no vive en el código ni en el prompt.
El archivo se valida con Pydantic: si falta, tiene un campo de más o un valor fuera de rango, la aplicación se detiene
con un mensaje claro en lugar de planificar con un valor equivocado.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

RUTA_PARAMETROS = Path(__file__).resolve().parent.parent / "config" / "parametros.yaml"


class _Seccion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ParamsItinerario(_Seccion):
    jornada_max_h: float = Field(gt=0, le=24)
    duracion_por_defecto_h: float = Field(gt=0, le=24)


class ParamsRecalcular(_Seccion):
    holgura_h: float = Field(ge=0, le=8)


class ParamsAgente(_Seccion):
    max_iter: int = Field(ge=1, le=12)
    confirmacion_ttl_min: float = Field(gt=0, le=24 * 60)
    max_historial: int = Field(ge=0, le=20)


class Parametros(_Seccion):
    itinerario: ParamsItinerario
    recalcular: ParamsRecalcular
    agente: ParamsAgente


class ErrorParametros(RuntimeError):
    """config/parametros.yaml falta o tiene un valor inválido."""


def cargar_parametros(ruta: Path = RUTA_PARAMETROS) -> Parametros:
    try:
        datos = yaml.safe_load(ruta.read_text(encoding="utf-8")) or {}
        return Parametros.model_validate(datos)
    except FileNotFoundError as e:
        raise ErrorParametros(f"No existe {ruta}: es obligatorio (parámetros de negocio).") from e
    except (yaml.YAMLError, ValidationError) as e:
        raise ErrorParametros(f"{ruta} no es válido: {e}") from e


@lru_cache
def parametros() -> Parametros:
    return cargar_parametros()
