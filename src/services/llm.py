"""Servicio de IA: la ÚNICA parte del sistema que habla con el modelo.

Qué resuelve este módulo (lo que se pide para el viernes 23):
  1. Encapsula al proveedor: los endpoints llaman a ClienteLLM y no saben si detrás
     está Gemini o Groq.
  2. Pide la salida en JSON con un esquema y la VALIDA con Pydantic.
  3. Pone límites: tiempo de espera, máximo de tokens y número de intentos.
  4. Maneja los errores del proveedor: 429 (límite de solicitudes), tiempo agotado,
     caída del servicio y respuesta vacía, con reintentos y espera exponencial.
  5. Si el principal no responde, pasa al proveedor de respaldo.
  6. Deja un registro (log) por solicitud con tokens y tiempo de respuesta.

Idea fuerza: el modelo propone, el código dispone.
"""
from __future__ import annotations

import json
import logging
import random
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Generic, Iterator, TypeVar

import openai
from openai import OpenAI
from pydantic import BaseModel, ValidationError

from src.config import Config, Proveedor, cargar_config

T = TypeVar("T", bound=BaseModel)

# ---------------------------------------------------------------- registro (log)
Path("logs").mkdir(exist_ok=True)
log = logging.getLogger("llm")
if not log.handlers:
    log.setLevel(logging.INFO)
    _f = logging.FileHandler("logs/llm.jsonl", encoding="utf-8")
    _f.setFormatter(logging.Formatter("%(message)s"))
    log.addHandler(_f)
    _c = logging.StreamHandler()
    _c.setFormatter(logging.Formatter("  [llm] %(message)s"))
    log.addHandler(_c)


def _registrar(**datos) -> None:
    # Nunca se registra el texto del usuario: puede tener datos personales.
    log.info(json.dumps(datos, ensure_ascii=False))


# ---------------------------------------------------------------- errores propios
class ErrorLLM(Exception):
    """Error que el endpoint puede traducir a un mensaje claro para el usuario."""

    mensaje_usuario = "El asistente no pudo responder. Inténtalo de nuevo."


class ProveedorNoDisponible(ErrorLLM):
    mensaje_usuario = "El asistente no está disponible en este momento. Intenta de nuevo en unos minutos."


class SalidaInvalida(ErrorLLM):
    mensaje_usuario = "No pudimos procesar la respuesta automáticamente. Tu solicitud quedó para revisión humana."


class _FalloProveedor(Exception):
    """Interno: este proveedor se rindió; probar con el siguiente."""


# Errores que vale la pena reintentar: son pasajeros.
REINTENTABLES = (openai.RateLimitError, openai.APITimeoutError, openai.APIConnectionError, openai.InternalServerError)
# Errores que NO se arreglan reintentando con el mismo proveedor: clave mala, modelo
# inexistente, solicitud mal formada. Se pasa directo al respaldo.
DEFINITIVOS = (openai.AuthenticationError, openai.PermissionDeniedError, openai.NotFoundError, openai.BadRequestError)

def es_generacion_fallida(e: Exception) -> bool:
    """El modelo escribió un JSON que no cumple el esquema estricto (Groq: 400 json_validate_failed, o un
    APIError a mitad del stream con «failed_generation»). Es un fallo del MODELO, pasajero: reintentar sirve."""
    if isinstance(e, openai.APIError) and not isinstance(e, openai.APIStatusError):
        return "schema" in str(e).lower() or "failed_generation" in str(e).lower()  # error a mitad del stream
    return (isinstance(e, openai.BadRequestError)
            and (getattr(e, "code", None) == "json_validate_failed" or "failed_generation" in str(e).lower()))


def _detalle(e: Exception) -> str | None:
    """Fragmento de lo que escribió el modelo (sin datos del usuario) para diagnosticar; máx. 300 caracteres."""
    cuerpo = getattr(e, "body", None)
    falla = cuerpo.get("failed_generation") if isinstance(cuerpo, dict) else None
    return str(falla)[:300] if falla else None


ESPERA_MAXIMA_S = 20  # si el proveedor pide esperar más que esto, mejor ir al respaldo
ESPERA_MAXIMA_SIN_RESPALDO_S = 45  # sin respaldo no hay a dónde ir: se espera más antes de rendirse


@dataclass
class Resultado(Generic[T]):
    datos: T | str
    proveedor: str
    modelo: str
    tokens_entrada: int | None
    tokens_salida: int | None
    latencia_ms: int
    intentos: int


def espera_exponencial(intento: int, base: float = 1.0) -> float:
    """1 s, 2 s, 4 s… La mitad es fija y la otra mitad al azar ("jitter"),
    para que cien clientes que fallaron juntos no vuelvan a chocar juntos."""
    tope = base * 2 ** (intento - 1)
    return tope / 2 + random.uniform(0, tope / 2)


def _retry_after(error: Exception) -> float | None:
    """Segundos que el proveedor pide esperar (cabecera Retry-After), si los dice."""
    respuesta = getattr(error, "response", None)
    valor = respuesta.headers.get("retry-after") if respuesta is not None else None
    try:
        return float(valor) if valor is not None else None
    except ValueError:
        return None


def _limpiar_json(texto: str) -> str:
    """Algunos modelos envuelven el JSON en ```json … ```. Se lo quitamos."""
    texto = texto.strip()
    m = re.match(r"^```(?:json)?\s*(.*?)\s*```$", texto, re.S)
    return m.group(1) if m else texto


class ClienteLLM:
    def __init__(self, config: Config | None = None, clientes: dict | None = None,
                 dormir: Callable[[float], None] = time.sleep):
        self.config = config or cargar_config()
        self.proveedores: list[Proveedor] = [p for p in (self.config.principal, self.config.respaldo) if p]
        self.dormir = dormir  # en las pruebas se reemplaza para no esperar de verdad
        self._clientes = clientes or {
            p.nombre: OpenAI(api_key=p.api_key, base_url=p.base_url,
                             timeout=self.config.timeout_s, max_retries=0)  # los reintentos los hacemos nosotros
            for p in self.proveedores
        }

    # ------------------------------------------------------------ llamada con reintentos
    def _llamar(self, p: Proveedor, mensajes: list[dict], extra: dict) -> tuple[object, int, int]:
        cliente = self._clientes[p.nombre]
        opciones = {"max_tokens": self.config.max_tokens, **extra}
        if self.config.razonamiento and p.nombre != "simulado":
            opciones["reasoning_effort"] = self.config.razonamiento
        for intento in range(1, self.config.reintentos + 1):
            t0 = time.monotonic()
            try:
                r = cliente.chat.completions.create(model=p.modelo, messages=mensajes, **opciones)
                ms = int((time.monotonic() - t0) * 1000)
                contenido = (r.choices[0].message.content or "") if r.choices else ""
                if not contenido.strip():
                    raise _RespuestaVacia()
                uso = getattr(r, "usage", None)
                _registrar(evento="ok", proveedor=p.nombre, modelo=p.modelo, intento=intento, latencia_ms=ms,
                           tokens_entrada=getattr(uso, "prompt_tokens", None),
                           tokens_salida=getattr(uso, "completion_tokens", None),
                           fin=r.choices[0].finish_reason)
                return r, ms, intento
            except (*DEFINITIVOS, *REINTENTABLES, _RespuestaVacia) as e:
                if isinstance(e, DEFINITIVOS) and not es_generacion_fallida(e):
                    _registrar(evento="error_definitivo", proveedor=p.nombre, intento=intento, tipo=type(e).__name__,
                               estado_http=getattr(e, "status_code", None))
                    raise _FalloProveedor() from e
                pedida = _retry_after(e)
                # Si el proveedor dice cuánto esperar, se respeta y se suma un poco de azar
                espera = pedida + random.uniform(0, 0.5) if pedida is not None else espera_exponencial(intento)
                _registrar(evento="reintento" if intento < self.config.reintentos else "agotado",
                           proveedor=p.nombre, intento=intento, tipo=type(e).__name__,
                           estado_http=getattr(e, "status_code", None), espera_s=round(espera, 2),
                           detalle=_detalle(e) if es_generacion_fallida(e) else None)
                limite = ESPERA_MAXIMA_S if len(self.proveedores) > 1 else ESPERA_MAXIMA_SIN_RESPALDO_S
                if intento == self.config.reintentos or espera > limite:
                    raise _FalloProveedor() from e
                self.dormir(espera)
        raise _FalloProveedor()

    def _con_respaldo(self, mensajes: list[dict], extra: dict):
        for p in self.proveedores:
            try:
                r, ms, intentos = self._llamar(p, mensajes, extra)
                return p, r, ms, intentos
            except _FalloProveedor:
                continue
        _registrar(evento="sin_proveedor")
        raise ProveedorNoDisponible()

    # ------------------------------------------------------------ API pública
    def generar_texto(self, system: str, mensajes: list[dict]) -> Resultado[str]:
        """Respuesta de texto libre (por ejemplo, un chat). mensajes = historial."""
        p, r, ms, intentos = self._con_respaldo([{"role": "system", "content": system}, *mensajes], {})
        uso = getattr(r, "usage", None)
        return Resultado(r.choices[0].message.content, p.nombre, p.modelo,
                         getattr(uso, "prompt_tokens", None), getattr(uso, "completion_tokens", None), ms, intentos)

    def generar_json(self, system: str, usuario: str, esquema: type[T]) -> Resultado[T]:
        """Pide JSON con un esquema y lo valida. Si no cumple, pide UNA corrección."""
        formato = {"response_format": {"type": "json_schema", "json_schema": {
            "name": esquema.__name__, "strict": True, "schema": esquema.model_json_schema()}}}
        mensajes = [{"role": "system", "content": system}, {"role": "user", "content": usuario}]
        p, r, ms, intentos = self._con_respaldo(mensajes, formato)
        texto = r.choices[0].message.content
        try:
            datos = esquema.model_validate_json(_limpiar_json(texto))
        except ValidationError as e:
            _registrar(evento="salida_invalida", proveedor=p.nombre, errores=e.error_count())
            correccion = mensajes + [
                {"role": "assistant", "content": texto},
                {"role": "user", "content": "Tu respuesta no cumple el esquema. Errores:\n"
                    + "\n".join(f"- {'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors())
                    + "\nDevuelve SOLO el JSON corregido."},
            ]
            p, r, ms2, _ = self._con_respaldo(correccion, formato)
            ms += ms2
            try:
                datos = esquema.model_validate_json(_limpiar_json(r.choices[0].message.content))
            except ValidationError as e2:
                _registrar(evento="salida_invalida_final", proveedor=p.nombre, errores=e2.error_count())
                raise SalidaInvalida() from e2
        uso = getattr(r, "usage", None)
        return Resultado(datos, p.nombre, p.modelo, getattr(uso, "prompt_tokens", None),
                         getattr(uso, "completion_tokens", None), ms, intentos)

    def generar_stream(self, system: str, mensajes: list[dict],
                       esquema: type[BaseModel] | None = None) -> Iterator[str]:
        """Streaming: entrega el texto en trozos. Con `esquema`, el proveedor produce JSON que cumple
        ese esquema (el llamador lo valida al final). Solo se puede cambiar de proveedor ANTES del
        primer trozo: si falla a mitad del flujo no se mezclan dos respuestas."""
        completos = [{"role": "system", "content": system}, *mensajes]
        extra: dict = {}
        if esquema is not None:
            extra["response_format"] = {"type": "json_schema", "json_schema": {
                "name": esquema.__name__, "strict": True, "schema": esquema.model_json_schema()}}
        for p in self.proveedores:
            opciones = dict(extra)
            if self.config.razonamiento and p.nombre != "simulado":
                opciones["reasoning_effort"] = self.config.razonamiento
            enviados = 0
            t0 = time.monotonic()
            try:
                flujo = self._clientes[p.nombre].chat.completions.create(
                    model=p.modelo, messages=completos, stream=True, max_tokens=self.config.max_tokens, **opciones)
                for trozo in flujo:
                    if trozo.choices and trozo.choices[0].delta.content:
                        enviados += 1
                        yield trozo.choices[0].delta.content
                if not enviados:
                    raise _RespuestaVacia()
                _registrar(evento="stream_ok", proveedor=p.nombre, modelo=p.modelo, trozos=enviados,
                           latencia_ms=int((time.monotonic() - t0) * 1000))
                return
            except (openai.APIError, _RespuestaVacia) as e:
                # APIError (la clase base) es lo que lanza el cliente cuando el proveedor corta el flujo a mitad
                _registrar(evento="stream_fallo", proveedor=p.nombre, tipo=type(e).__name__, trozos=enviados,
                           estado_http=getattr(e, "status_code", None), detalle=_detalle(e))
                if enviados:  # ya se entregó texto parcial: no se puede cambiar de proveedor
                    break
                continue
        raise ProveedorNoDisponible()


class _RespuestaVacia(Exception):
    """El proveedor respondió 200 pero sin contenido."""


def cargar_prompt(nombre: str) -> str:
    """Los prompts viven en archivos versionados, no escondidos en el código."""
    return (Path(__file__).resolve().parent.parent / "prompts" / f"{nombre}.md").read_text(encoding="utf-8")
