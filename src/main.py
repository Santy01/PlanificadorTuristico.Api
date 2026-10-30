"""API del planificador turístico.

Ejecutar:  uvicorn src.main:app --reload     y abrir http://127.0.0.1:8000/docs
"""
import json
import logging
from contextlib import asynccontextmanager
from functools import lru_cache

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import StreamingResponse

from src.catalogo import RUTA_CATALOGO, RUTA_REDUCIDA, Atractivo, cargar_catalogo, con_ubicacion
from src.schemas import RespuestaItinerario, SolicitudItinerario
from src.services.clima import ClienteClima
from src.services.itinerario import generar_itinerario, stream_itinerario
from src.services.llm import ClienteLLM, ProveedorNoDisponible
from src.services.rag import ClienteRAG
from src.services.indice import cargar_config_rag

log = logging.getLogger("main")


@asynccontextmanager
async def ciclo_de_vida(app: FastAPI):
    """Carga el modelo de embeddings al arrancar (unos 10 s) para que la primera solicitud no la pague."""
    if obtener_rag not in app.dependency_overrides:
        rag = obtener_rag()
        if rag is not None and not rag.precalentar():
            log.warning("RAG no disponible al arrancar: los itinerarios saldrán sin citas")
    yield


app = FastAPI(title="Planificador Turístico Zona Centro", version="0.3.0", lifespan=ciclo_de_vida)


@lru_cache
def obtener_llm() -> ClienteLLM:
    return ClienteLLM()


@lru_cache
def obtener_clima() -> ClienteClima:
    return ClienteClima()


@lru_cache
def obtener_rag() -> ClienteRAG | None:
    """None si el RAG está apagado (RAG_ACTIVO=false) o si todavía no se ejecutó scripts/ingestar_rag.py:
    en ese caso la API funciona como antes, sin citas."""
    cfg = cargar_config_rag()
    if not cfg.activo or not cfg.ruta.exists():
        return None
    return ClienteRAG(cfg)


@lru_cache
def obtener_catalogo() -> dict[str, Atractivo]:
    """Catálogo que ve el modelo: el reducido y equilibrado si existe (menos tokens); si no, el completo.
    En ambos casos solo atractivos con ubicación."""
    return con_ubicacion(cargar_catalogo(RUTA_REDUCIDA if RUTA_REDUCIDA.exists() else RUTA_CATALOGO))


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/itinerario", response_model=RespuestaItinerario)
def itinerario(solicitud: SolicitudItinerario, llm: ClienteLLM = Depends(obtener_llm),
               catalogo: dict[str, Atractivo] = Depends(obtener_catalogo),
               clima: ClienteClima = Depends(obtener_clima), rag: ClienteRAG | None = Depends(obtener_rag)):
    try:
        return generar_itinerario(llm, solicitud, catalogo, clima, rag)
    except ProveedorNoDisponible as e:
        # Nunca se muestra el error crudo del proveedor: un mensaje claro y un 503.
        raise HTTPException(status_code=503, detail=e.mensaje_usuario)


def _sse(evento: str, dato) -> str:
    cuerpo = dato.model_dump(mode="json") if hasattr(dato, "model_dump") else dato
    return f"event: {evento}\ndata: {json.dumps(cuerpo, ensure_ascii=False)}\n\n"


@app.post("/itinerario/stream")
def itinerario_stream(solicitud: SolicitudItinerario, llm: ClienteLLM = Depends(obtener_llm),
                      catalogo: dict[str, Atractivo] = Depends(obtener_catalogo),
                      clima: ClienteClima = Depends(obtener_clima), rag: ClienteRAG | None = Depends(obtener_rag)):
    """Server-Sent Events: `texto` (trozos en vivo), luego `itinerario` (resultado validado) o `error`."""
    flujo = (_sse(e, d) for e, d in stream_itinerario(llm, solicitud, catalogo, clima, rag))
    return StreamingResponse(flujo, media_type="text/event-stream", headers={"Cache-Control": "no-cache"})
