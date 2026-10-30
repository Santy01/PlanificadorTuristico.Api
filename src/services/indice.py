"""Índice vectorial del RAG: fragmentación del corpus, asignación de cada fragmento a su atractivo,
embeddings y Chroma.

Regla de oro (la misma del catálogo): un fragmento solo se asocia a un atractivo si trata de él. En una página que
cita varios atractivos, un fragmento que no nombra a ninguno se DESCARTA, antes que citarlo donde no corresponde.

Los imports pesados (chromadb, sentence-transformers) son perezosos: fragmentar y asignar se prueban sin cargarlos.
"""
from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

from dotenv import load_dotenv

from src.catalogo import Atractivo

load_dotenv()

RAIZ = Path(__file__).resolve().parents[2]
MAX_CARACTERES = 1200   # ~300 tokens: cabe de sobra en el límite de 512 del modelo de embeddings
SOLAPE_CARACTERES = 150  # ~10-15 % de solape, como prevé docs/04-fuentes.md
MIN_FRAGMENTO = 80       # un fragmento más corto casi nunca contiene información útil
LOTE = 64

# Palabras que describen el TIPO de lugar y no lo identifican: «Cascada» no distingue a «Cascada Pailón del Diablo».
GENERICAS = {
    "de", "del", "la", "el", "los", "las", "y", "e", "en", "a", "al",
    "cascada", "cascadas", "parque", "nacional", "laguna", "volcan", "iglesia", "catedral", "museo", "mirador",
    "reserva", "ruta", "termas", "feria", "mercado", "plaza", "templo", "hacienda", "canton", "ciudad", "centro",
    "historico", "santuario", "casa", "cerro", "bosque", "rio", "puente", "tren", "estacion",
}


@dataclass(frozen=True)
class ConfigRAG:
    ruta: Path
    coleccion: str
    modelo: str
    top_k: int         # atractivos distintos que devuelve la recuperación
    margen: float      # se conservan los atractivos a menos de `margen` de similitud del mejor


def cargar_config_rag() -> ConfigRAG:
    ruta = Path(os.getenv("VECTOR_DB_PATH", "").strip() or "data/vectorstore")
    return ConfigRAG(
        ruta=ruta if ruta.is_absolute() else RAIZ / ruta,
        coleccion=os.getenv("VECTOR_DB_COLECCION", "").strip() or "atractivos",
        modelo=os.getenv("EMBEDDING_MODEL", "").strip() or "intfloat/multilingual-e5-small",
        top_k=int(os.getenv("RAG_TOP_K", "").strip() or 12),
        margen=float(os.getenv("RAG_MARGEN_SIMILITUD", "").strip() or 0.05),
    )


# ---------------------------------------------------------------- texto

def normalizar(texto: str) -> str:
    sin_tildes = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", sin_tildes.lower()).strip()


def _partir_largo(linea: str, maximo: int) -> list[str]:
    """Una línea más larga que el máximo se corta por oraciones y, si hace falta, por palabras."""
    piezas: list[str] = []
    actual = ""
    for oracion in re.split(r"(?<=[.!?])\s+", linea):
        while len(oracion) > maximo:
            corte = oracion.rfind(" ", 0, maximo)
            corte = corte if corte > 0 else maximo
            if actual:
                piezas.append(actual)
                actual = ""
            piezas.append(oracion[:corte].strip())
            oracion = oracion[corte:].strip()
        if actual and len(actual) + 1 + len(oracion) > maximo:
            piezas.append(actual)
            actual = ""
        actual = f"{actual} {oracion}".strip()
    if actual:
        piezas.append(actual)
    return piezas


def _cola(texto: str, solape: int) -> str:
    """Los últimos ~`solape` caracteres, empezando en una palabra completa."""
    if solape <= 0 or len(texto) <= solape:
        return texto if solape > 0 else ""
    cola = texto[-solape:]
    return cola[cola.find(" ") + 1:] if " " in cola else cola


def fragmentar(texto: str, maximo: int = MAX_CARACTERES, solape: int = SOLAPE_CARACTERES) -> list[str]:
    """Parte el texto en fragmentos de hasta `maximo` caracteres con `solape` entre vecinos.
    Junta líneas completas (no corta frases por la mitad salvo que una línea sola exceda el máximo)."""
    unidades: list[str] = []
    for linea in (l.strip() for l in texto.splitlines()):
        if linea:
            unidades += _partir_largo(linea, maximo) if len(linea) > maximo else [linea]
    fragmentos: list[str] = []
    actual = ""
    for unidad in unidades:
        if actual and len(actual) + 1 + len(unidad) > maximo:
            fragmentos.append(actual)
            actual = f"{_cola(actual, solape)} {unidad}".strip()
        else:
            actual = f"{actual}\n{unidad}".strip()
    if actual and (not fragmentos or len(actual) > solape):
        fragmentos.append(actual)
    return fragmentos


def nombra_a(fragmento_normalizado: str, atractivo: Atractivo) -> bool:
    """¿El fragmento nombra al atractivo? Deben aparecer TODAS las palabras distintivas de su nombre
    (sin tildes ni mayúsculas, sin las genéricas como «cascada» o «parque»)."""
    palabras = set(fragmento_normalizado.split())
    distintivas = [t for t in normalizar(atractivo.nombre).split() if t not in GENERICAS and len(t) > 2]
    return bool(distintivas) and all(t in palabras for t in distintivas)


def asignar(fragmento: str, candidatos: list[Atractivo]) -> list[Atractivo]:
    """Atractivos a los que pertenece el fragmento. Con un solo candidato la página es de ese atractivo; con
    varios, solo los que el fragmento nombra (puede ser ninguno: el fragmento se descarta)."""
    if len(candidatos) == 1:
        return candidatos
    norm = normalizar(fragmento)
    return [a for a in candidatos if nombra_a(norm, a)]


# ---------------------------------------------------------------- registros

@dataclass
class Registro:
    id: str
    documento: str            # el fragmento tal cual: es lo que se cita
    para_embedding: str       # el fragmento con el nombre del atractivo delante (contexto para el modelo)
    metadatos: dict = field(default_factory=dict)


@dataclass
class Estadisticas:
    fragmentos: int = 0
    por_clase: dict = field(default_factory=dict)
    descartados: int = 0                          # fragmentos de páginas multi-atractivo que no nombran a ninguno
    sin_texto: list = field(default_factory=list)  # documentos del manifiesto sin archivo que leer
    atractivos_con_web: set = field(default_factory=set)


def construir_registros(filas: Iterable[dict], catalogo: dict[str, Atractivo],
                        leer: Callable[[str], str]) -> tuple[list[Registro], Estadisticas]:
    """Del manifiesto a los registros que se indexan. `leer(ruta)` devuelve el texto del documento."""
    registros: list[Registro] = []
    est = Estadisticas()
    for fila in filas:
        if fila["estado"] != "ok" or not fila["archivo"]:
            continue
        ids = [i for i in fila["atractivo_ids"].split("|") if i in catalogo]
        if not ids:
            continue
        try:
            texto = leer(fila["archivo"])
        except OSError:
            est.sin_texto.append(fila["doc_id"])
            continue
        candidatos = [catalogo[i] for i in ids]
        trozos = [texto.strip()] if fila["clase"] == "ficha" else fragmentar(texto)
        for n, trozo in enumerate(trozos):
            if len(trozo) < MIN_FRAGMENTO and fila["clase"] != "ficha":
                continue
            duenos = asignar(trozo, candidatos)
            if not duenos:
                est.descartados += 1
                continue
            for a in duenos:
                registros.append(Registro(
                    id=f"{fila['doc_id']}:{n}:{a.id}",
                    documento=trozo,
                    para_embedding=f"{a.nombre} ({a.provincia}): {trozo}",
                    metadatos={
                        "atractivo_id": a.id, "nombre": a.nombre, "provincia": a.provincia, "tipo": a.tipo,
                        "doc_id": fila["doc_id"], "clase": fila["clase"], "fuente": fila["fuente"],
                        "url": fila["url"], "tipo_fuente": fila["tipo_fuente"],
                        "estado_verificacion": a.estado_verificacion if fila["clase"] == "ficha"
                        else fila["estado_verificacion"],
                        "fecha": fila["fecha_descarga"],
                    }))
                est.por_clase[fila["clase"]] = est.por_clase.get(fila["clase"], 0) + 1
                if fila["clase"] == "web":
                    est.atractivos_con_web.add(a.id)
    est.fragmentos = len(registros)
    return registros, est


# ---------------------------------------------------------------- embeddings y Chroma

def cargar_modelo(cfg: ConfigRAG):
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(cfg.modelo)


def vectorizar(modelo, cfg: ConfigRAG, textos: list[str], consulta: bool = False) -> list[list[float]]:
    """Los modelos E5 exigen el prefijo «passage: » (documentos) o «query: » (consultas); sin él rinden peor."""
    if "e5" in cfg.modelo.lower():
        prefijo = "query: " if consulta else "passage: "
        textos = [prefijo + t for t in textos]
    return modelo.encode(textos, batch_size=LOTE, normalize_embeddings=True, show_progress_bar=False).tolist()


def abrir_cliente(cfg: ConfigRAG):
    import chromadb
    cfg.ruta.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=str(cfg.ruta))


def reconstruir_coleccion(cfg: ConfigRAG, modelo, registros: list[Registro]) -> int:
    """Borra y vuelve a crear la colección: reejecutar la ingesta siempre da el mismo resultado, sin duplicados."""
    cliente = abrir_cliente(cfg)
    try:
        cliente.delete_collection(cfg.coleccion)
    except Exception:  # noqa: BLE001 — la primera vez no existe
        pass
    coleccion = cliente.create_collection(cfg.coleccion, metadata={"hnsw:space": "cosine", "modelo": cfg.modelo})
    for i in range(0, len(registros), LOTE):
        lote = registros[i:i + LOTE]
        coleccion.add(ids=[r.id for r in lote], documents=[r.documento for r in lote],
                      metadatas=[r.metadatos for r in lote],
                      embeddings=vectorizar(modelo, cfg, [r.para_embedding for r in lote]))
    return coleccion.count()
