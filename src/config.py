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

# Groq y Gemini hablan el mismo "idioma" que OpenAI (API de Chat Completions), por eso se usa el
# cliente `openai` apuntando a su base_url. Cambiar de proveedor es agregar una entrada aquí;
# los endpoints no se tocan.
#   razonamiento: si acepta el parámetro `reasoning_effort` (LLM_RAZONAMIENTO).
#   esquema: dialecto de JSON Schema que acepta en response_format y en tools (ver adaptar_esquema en llm.py).
CATALOGO = {
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "clave": "GROQ_API_KEY",
        "modelo_env": "GROQ_MODEL",
        "modelo": "openai/gpt-oss-20b",
        "razonamiento": True,
        "esquema": "estricto",
    },
    # Respaldo (Semana 4): endpoint de Google compatible con OpenAI. Tiene su propia cuota, así que un 429 de
    # Groq el día de la demo no deja al sistema sin modelo. El modelo se fija con GEMINI_MODEL.
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "clave": "GEMINI_API_KEY",
        "modelo_env": "GEMINI_MODEL",
        "modelo": "gemini-2.5-flash",
        "razonamiento": False,
        "esquema": "gemini",
    },
    # Servidor local que imita a un proveedor (scripts/servidor_simulado.py).
    # Sirve para practicar errores 429 sin gastar cuota.
    "simulado": {
        "base_url": "http://127.0.0.1:8099/v1",
        "clave": None,
        "modelo_env": None,
        "modelo": "simulado-1",
        "razonamiento": False,
        "esquema": "estricto",
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
    admite_razonamiento: bool = True
    esquema: str = "estricto"


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
        raise ErrorConfiguracion(f"Proveedor desconocido: «{nombre}». Use uno de: {', '.join(CATALOGO)}.")
    c = CATALOGO[nombre]
    clave = "no-se-necesita"
    if c["clave"]:
        clave = os.getenv(c["clave"], "").strip()
        if not clave:
            raise ErrorConfiguracion(
                f"Falta {c['clave']} en el archivo .env. Copie .env.example como .env y pegue su clave."
            )
    modelo = os.getenv(c["modelo_env"], "").strip() if c["modelo_env"] else ""
    return Proveedor(nombre, c["base_url"], clave, modelo or c["modelo"], c["razonamiento"], c["esquema"])


def cargar_config() -> Config:
    principal = _proveedor(os.getenv("LLM_PRINCIPAL", "groq"))
    nombre_respaldo = os.getenv("LLM_RESPALDO", "").strip()
    respaldo = _proveedor(nombre_respaldo) if nombre_respaldo and nombre_respaldo != principal.nombre else None
    razonamiento = os.getenv("LLM_RAZONAMIENTO", "low").strip() or None  # solo se envía a quien lo admite
    return Config(
        principal=principal,
        respaldo=respaldo,
        timeout_s=float(os.getenv("LLM_TIMEOUT_S", "30")),
        max_tokens=int(os.getenv("LLM_MAX_TOKENS", "4096")),
        reintentos=int(os.getenv("LLM_REINTENTOS", "3")),
        razonamiento=razonamiento,
    )


def estado_proveedores() -> dict:
    """Para /health: qué proveedores están configurados y si tienen clave. Nunca lanza ni muestra una clave."""
    def uno(nombre: str) -> dict | None:
        nombre = nombre.strip().lower()
        if not nombre:
            return None
        c = CATALOGO.get(nombre)
        if c is None:
            return {"nombre": nombre, "configurado": False}
        con_clave = c["clave"] is None or bool(os.getenv(c["clave"], "").strip())
        modelo = (os.getenv(c["modelo_env"], "").strip() if c["modelo_env"] else "") or c["modelo"]
        return {"nombre": nombre, "modelo": modelo, "configurado": con_clave}
    return {"principal": uno(os.getenv("LLM_PRINCIPAL", "groq")), "respaldo": uno(os.getenv("LLM_RESPALDO", ""))}
