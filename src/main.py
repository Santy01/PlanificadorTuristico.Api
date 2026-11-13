"""API del planificador turístico.

Ejecutar:  uvicorn src.main:app --reload     y abrir http://127.0.0.1:8000/docs
"""
import json
import logging
from contextlib import asynccontextmanager
from functools import lru_cache

from fastapi import Depends, FastAPI, HTTPException, Path, Request
from fastapi.responses import StreamingResponse

from src.agente import AlmacenPendientes, confirmar, conversar
from src.config import estado_proveedores
from src.limites import LimitadorPorIP, ip_cliente
from src.catalogo import RUTA_CATALOGO, RUTA_REDUCIDA, Atractivo, cargar_catalogo, con_ubicacion
from src.parametros import parametros
from src.schemas import DecisionAgente, RespuestaAgente, RespuestaItinerario, SolicitudAgente, SolicitudItinerario
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


app = FastAPI(title="Planificador Turístico Zona Centro", version="0.5.0", lifespan=ciclo_de_vida)


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


@lru_cache
def obtener_catalogo_agente() -> dict[str, Atractivo]:
    """Catálogo COMPLETO con ubicación para el agente. El reducido existe para ahorrar tokens en el prompt del
    itinerario; las herramientas del agente nunca envían el catálogo al modelo, así que no hay razón para recortarlo.
    Con el reducido, «¿qué horario tiene el Pailón?» no encontraba nada (el Pailón no está en él) y recalcular tenía
    la mitad de candidatos (hallazgo de la evaluación de la Entrega 3)."""
    return con_ubicacion(cargar_catalogo(RUTA_CATALOGO))


@app.get("/health")
def health(rag: ClienteRAG | None = Depends(obtener_rag)) -> dict:
    """Responde rápido y SIN llamar al modelo: si el proveedor está caído, la app sigue viva y lo puede decir.
    Informa qué está listo (índice, proveedores configurados), nunca el valor de una clave."""
    return {
        "status": "ok",
        "version": app.version,
        "rag": {"activo": rag is not None, "fragmentos": rag.fragmentos_indexados() if rag is not None else None},
        "modelo": estado_proveedores(),
    }


@lru_cache
def obtener_limitadores() -> dict[str, LimitadorPorIP]:
    lim = parametros().limites
    return {"itinerario": LimitadorPorIP(lim.itinerario, lim.ventana_s),
            "agente": LimitadorPorIP(lim.agente, lim.ventana_s)}


def limitar(grupo: str):
    """Dependencia: 429 con Retry-After si la IP pasó su cupo en la ventana (config/parametros.yaml → limites)."""
    def dependencia(request: Request, limitadores: dict[str, LimitadorPorIP] = Depends(obtener_limitadores)) -> None:
        ip = ip_cliente(request.headers.get("x-forwarded-for"), request.client.host if request.client else None,
                        parametros().limites.proxies_confiables)
        permitido, espera = limitadores[grupo].permitir(ip)
        if not permitido:
            raise HTTPException(status_code=429, headers={"Retry-After": str(espera)},
                                detail=f"Demasiadas solicitudes seguidas. Intenta de nuevo en {espera} segundos.")
    return dependencia


@app.post("/itinerario", response_model=RespuestaItinerario, dependencies=[Depends(limitar("itinerario"))])
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


@lru_cache
def obtener_pendientes() -> AlmacenPendientes:
    return AlmacenPendientes(ttl_s=parametros().agente.confirmacion_ttl_min * 60)


@app.post("/agente", response_model=RespuestaAgente, dependencies=[Depends(limitar("agente"))])
def agente(sol: SolicitudAgente, llm: ClienteLLM = Depends(obtener_llm),
           catalogo: dict[str, Atractivo] = Depends(obtener_catalogo_agente),
           clima: ClienteClima = Depends(obtener_clima), rag: ClienteRAG | None = Depends(obtener_rag),
           pendientes: AlmacenPendientes = Depends(obtener_pendientes)):
    """Conversa sobre un itinerario ya generado: lo ajusta (recalcular), consulta clima y fuentes. Si el agente
    quiere enviar el itinerario, responde `requiere_confirmacion` y NO lo envía hasta /agente/confirmar/{id}."""
    try:
        return conversar(llm, sol, catalogo, rag, clima, pendientes)
    except ProveedorNoDisponible as e:
        raise HTTPException(status_code=503, detail=e.mensaje_usuario)


@app.post("/agente/confirmar/{id_accion}", response_model=RespuestaAgente, dependencies=[Depends(limitar("agente"))])
def agente_confirmar(decision: DecisionAgente, id_accion: str = Path(max_length=64),
                     llm: ClienteLLM = Depends(obtener_llm),
                     pendientes: AlmacenPendientes = Depends(obtener_pendientes)):
    """El visitante aprueba o rechaza la acción pendiente. Recién aquí se ejecuta; cada id se decide una sola vez."""
    r = confirmar(llm, id_accion, decision.aprobar, pendientes)
    if r is None:
        raise HTTPException(status_code=404, detail="No hay una acción pendiente con ese id (ya se decidió o venció).")
    return r


@app.post("/itinerario/stream", dependencies=[Depends(limitar("itinerario"))])
def itinerario_stream(solicitud: SolicitudItinerario, llm: ClienteLLM = Depends(obtener_llm),
                      catalogo: dict[str, Atractivo] = Depends(obtener_catalogo),
                      clima: ClienteClima = Depends(obtener_clima), rag: ClienteRAG | None = Depends(obtener_rag)):
    """Server-Sent Events: `texto` (trozos en vivo), luego `itinerario` (resultado validado) o `error`."""
    flujo = (_sse(e, d) for e, d in stream_itinerario(llm, solicitud, catalogo, clima, rag))
    return StreamingResponse(flujo, media_type="text/event-stream", headers={"Cache-Control": "no-cache"})
