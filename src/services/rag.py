"""Recuperación del RAG: de la solicitud del visitante a los atractivos y fragmentos más pertinentes.

Misma regla de oro que el clima: el RAG es un EXTRA. Si el índice no existe, el modelo no carga o Chroma falla,
`recuperar` NO lanza: devuelve una recuperación no disponible y el itinerario sigue con el catálogo completo.

Cómo se elige (búsqueda híbrida):
  1. Filtro duro por metadatos (tipo de atractivo) en Chroma y descarte de todo lo que no esté en el catálogo.
  2. Similitud semántica entre la consulta y los fragmentos.
  3. Se agrupa por ATRACTIVO: un atractivo con muchos fragmentos parecidos no puede ocupar todos los lugares
     (con E5 las similitudes salen muy juntas y sin esto un volcán desplazaba al tren de la Nariz del Diablo).
  4. Se conservan los atractivos a menos de `margen` de similitud del mejor, hasta `top_k`.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from src.catalogo import Atractivo
from src.schemas import SolicitudItinerario
from src.services.indice import ConfigRAG, abrir_cliente, cargar_config_rag, cargar_modelo, vectorizar

log = logging.getLogger("rag")

POOL = 4                         # se piden top_k × POOL fragmentos para poder agrupar por atractivo
MAX_FRAGMENTOS_POR_ATRACTIVO = 2  # los mejores de cada atractivo: bastan para citar y no inflan el prompt


@dataclass(frozen=True)
class FragmentoRecuperado:
    id: str
    texto: str
    atractivo_id: str
    nombre: str
    puntaje: float            # similitud coseno (1 = idéntico)
    clase: str                # ficha | web
    fuente: str
    url: str
    tipo_fuente: str
    estado_verificacion: str


@dataclass
class Recuperacion:
    fragmentos: list[FragmentoRecuperado] = field(default_factory=list)
    disponible: bool = True
    motivo: str | None = None   # por qué no está disponible

    @property
    def atractivo_ids(self) -> list[str]:
        """Ids de los atractivos recuperados, del más al menos pertinente y sin repetir."""
        return list(dict.fromkeys(f.atractivo_id for f in self.fragmentos))


def no_disponible(motivo: str) -> Recuperacion:
    return Recuperacion(fragmentos=[], disponible=False, motivo=motivo)


def consulta_desde(s: SolicitudItinerario) -> str:
    """Los intereses y las notas del visitante. El punto de partida y el presupuesto no describen QUÉ quiere ver."""
    partes = [", ".join(s.intereses)]
    if s.notas and s.notas.strip():
        partes.append(s.notas.strip())
    return ". ".join(partes)


class ClienteRAG:
    """Carga el modelo y abre la colección la primera vez que se usa (no al importar ni al crear el cliente).
    `modelo` y `coleccion` se pueden inyectar: así las pruebas no necesitan ni el modelo real ni Chroma."""

    def __init__(self, cfg: ConfigRAG | None = None, modelo=None, coleccion=None) -> None:
        self.cfg = cfg or cargar_config_rag()
        self._modelo = modelo
        self._coleccion = coleccion

    def _preparar(self) -> None:
        if self._modelo is None:
            self._modelo = cargar_modelo(self.cfg)
        if self._coleccion is None:
            self._coleccion = abrir_cliente(self.cfg).get_collection(self.cfg.coleccion)

    def precalentar(self) -> bool:
        """Carga todo de antemano (al arrancar la API) para que la primera solicitud no pague la carga."""
        try:
            self._preparar()
            return True
        except Exception as e:  # noqa: BLE001
            log.warning("rag_precalentar_fallo", exc_info=True)
            return False

    def buscar(self, consulta: str, catalogo: dict[str, Atractivo],
               tipos: set[str] | None = None) -> Recuperacion:
        self._preparar()
        k = self.cfg.top_k
        filtro = {"tipo": {"$in": sorted(tipos)}} if tipos else None
        emb = vectorizar(self._modelo, self.cfg, [consulta], consulta=True)
        r = self._coleccion.query(query_embeddings=emb, n_results=k * POOL, where=filtro)

        por_atractivo: dict[str, list[FragmentoRecuperado]] = {}
        for id_, doc, md, dist in zip(r["ids"][0], r["documents"][0], r["metadatas"][0], r["distances"][0]):
            if md["atractivo_id"] not in catalogo:        # RNF-06: nada fuera del catálogo verificado
                continue
            por_atractivo.setdefault(md["atractivo_id"], []).append(FragmentoRecuperado(
                id=id_, texto=doc, atractivo_id=md["atractivo_id"], nombre=md["nombre"], puntaje=1.0 - dist,
                clase=md["clase"], fuente=md["fuente"], url=md["url"], tipo_fuente=md["tipo_fuente"],
                estado_verificacion=md["estado_verificacion"]))
        if not por_atractivo:
            return Recuperacion()

        # Chroma devuelve los resultados ordenados; cada lista ya queda de mejor a peor fragmento.
        ordenados = sorted(por_atractivo.values(), key=lambda fs: -fs[0].puntaje)
        mejor = ordenados[0][0].puntaje
        elegidos = [fs for fs in ordenados if fs[0].puntaje >= mejor - self.cfg.margen][:k]
        return Recuperacion(fragmentos=[f for fs in elegidos for f in fs[:MAX_FRAGMENTOS_POR_ATRACTIVO]])

    def recuperar(self, s: SolicitudItinerario, catalogo: dict[str, Atractivo],
                  tipos: set[str] | None = None) -> Recuperacion:
        """Nunca lanza: ante cualquier falla devuelve una recuperación no disponible."""
        inicio = time.perf_counter()
        try:
            res = self.buscar(consulta_desde(s), catalogo, tipos)
        except Exception as e:  # noqa: BLE001 — respaldo final: el RAG jamás debe hacer fallar la solicitud
            log.warning("rag_fallo", exc_info=True)
            return no_disponible(f"{type(e).__name__}: {e}")
        log.info("rag_ok atractivos=%d fragmentos=%d ms=%.0f", len(res.atractivo_ids), len(res.fragmentos),
                 (time.perf_counter() - inicio) * 1000)
        return res
