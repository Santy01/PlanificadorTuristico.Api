"""Configuración leída del archivo .env.

Regla del seminario: lo que es secreto vive en variables de entorno, nunca en el código.
Si falta una clave, la aplicación se detiene con un mensaje claro (no con un error raro
a mitad de una demo).
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

# Groq habla el mismo "idioma" que OpenAI (API de Chat Completions), por eso se usa el
# cliente `openai` apuntando a su base_url. Cambiar de proveedor sería agregar una entrada aquí;
# los endpoints no se tocan.
CATALOGO = {
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "clave": "GROQ_API_KEY",
        "modelo_env": "GROQ_MODEL",
        "modelo": "openai/gpt-oss-20b",
    },
    # Servidor local que imita a un proveedor (scripts/servidor_simulado.py).
    # Sirve para practicar errores 429 sin gastar cuota.
    "simulado": {
        "base_url": "http://127.0.0.1:8099/v1",
        "clave": None,
        "modelo_env": None,
        "modelo": "simulado-1",
    },
}


class ErrorConfiguracion(RuntimeError):
    """Falta o está mal una variable del .env."""


@dataclass(frozen=True)
class Proveedor:
    nombre: str
    base_url: str
    api_key: str
    modelo: str


@dataclass(frozen=True)
class Config:
    principal: Proveedor
    respaldo: Proveedor | None
    timeout_s: float
    max_tokens: int
    reintentos: int
    razonamiento: str | None  # "low" | "medium" | "high" | None


def _proveedor(nombre: str) -> Proveedor:
    nombre = nombre.strip().lower()
    if nombre not in CATALOGO:
        raise ErrorConfiguracion(f"Proveedor desconocido: «{nombre}». Use groq o simulado.")
    c = CATALOGO[nombre]
    clave = "no-se-necesita"
    if c["clave"]:
        clave = os.getenv(c["clave"], "").strip()
        if not clave:
            raise ErrorConfiguracion(
                f"Falta {c['clave']} en el archivo .env. Copie .env.example como .env y pegue su clave."
            )
    modelo = os.getenv(c["modelo_env"], "").strip() if c["modelo_env"] else ""
    return Proveedor(nombre, c["base_url"], clave, modelo or c["modelo"])


def cargar_config() -> Config:
    principal = _proveedor(os.getenv("LLM_PRINCIPAL", "groq"))
    nombre_respaldo = os.getenv("LLM_RESPALDO", "").strip()
    respaldo = _proveedor(nombre_respaldo) if nombre_respaldo and nombre_respaldo != principal.nombre else None
    razonamiento = os.getenv("LLM_RAZONAMIENTO", "low").strip() or None
    if principal.nombre == "simulado":
        razonamiento = None
    return Config(
        principal=principal,
        respaldo=respaldo,
        timeout_s=float(os.getenv("LLM_TIMEOUT_S", "30")),
        max_tokens=int(os.getenv("LLM_MAX_TOKENS", "4096")),
        reintentos=int(os.getenv("LLM_REINTENTOS", "3")),
        razonamiento=razonamiento,
    )
