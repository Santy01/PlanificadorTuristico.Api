"""Catálogo verificado de atractivos: la fuente de verdad del sistema.

El modelo solo puede elegir atractivos de aquí, y solo por su `id`. Los costos, las
duraciones y las coordenadas que digan `POR VERIFICAR` NO se inventan: se tratan como
desconocidos y el código lo informa.
"""
from __future__ import annotations

import csv
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

RUTA_CATALOGO = Path(__file__).resolve().parent.parent / "data" / "catalogo" / "atractivos.csv"
RUTA_REDUCIDA = RUTA_CATALOGO.with_name("atractivos_reducido.csv")  # subconjunto equilibrado (scripts/curar_catalogo.py)
POR_VERIFICAR = "POR VERIFICAR"


def _numero(valor: str) -> float | None:
    try:
        return float(valor.replace(",", "."))
    except ValueError:
        return None  # «POR VERIFICAR» u otro texto


def parsear_costo(texto: str) -> tuple[float | None, bool, str | None]:
    """«2.00-2.50», «desde 18.00», «0 (inferido)» → (valor, aproximado, texto original).
    Con varios números se toma el MAYOR (estimación conservadora para el presupuesto).
    Es aproximado si es rango, «desde», inferido o el propio texto dice que falta verificar."""
    texto = texto.strip()
    numeros = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", texto)]
    if not numeros:
        return None, False, None  # «POR VERIFICAR» o vacío: no se inventa
    bajo = texto.lower()
    aproximado = len(numeros) > 1 or any(k in bajo for k in ("desde", "inferido", "verificar", "aprox"))
    return max(numeros), aproximado, texto


def _slug(texto: str) -> str:
    sin_tildes = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", sin_tildes.lower()).strip("-")[:60]


@dataclass(frozen=True)
class Atractivo:
    id: str
    nombre: str
    canton: str | None
    provincia: str
    tipo: str
    costo_usd: float | None
    costo_aproximado: bool
    costo_texto: str | None
    duracion_h: float | None
    latitud: float | None
    longitud: float | None
    fuente: str
    url_fuente: tuple[str, ...]
    estado_verificacion: str  # A, A_parcial, B, C
    precision_coord: str | None  # verificada_fuente, sitio_aprox, localidad_aprox
    notas: str | None


def cargar_catalogo(ruta: Path = RUTA_CATALOGO) -> dict[str, Atractivo]:
    catalogo: dict[str, Atractivo] = {}
    with open(ruta, encoding="utf-8-sig", newline="") as f:
        for fila in csv.DictReader(f):
            canton = fila["canton"].strip()
            costo, aprox, costo_texto = parsear_costo(fila["costo_estimado"])
            precision = fila.get("precision_coord", "").strip()
            urls = tuple(u.strip() for u in fila.get("url_fuente", "").split("|")
                         if u.strip().startswith("http"))
            a = Atractivo(
                id=_slug(fila["nombre"]),
                nombre=fila["nombre"].strip(),
                canton=None if canton == POR_VERIFICAR else canton,
                provincia=fila["provincia"].strip(),
                tipo=fila["tipo"].strip(),
                costo_usd=costo,
                costo_aproximado=aprox,
                costo_texto=costo_texto,
                duracion_h=_numero(fila["duracion_sugerida"]),
                latitud=_numero(fila["latitud"]),
                longitud=_numero(fila["longitud"]),
                fuente=fila["fuente"].strip(),
                url_fuente=urls,
                estado_verificacion=fila.get("estado_verificacion", "").strip() or "C",
                precision_coord=None if precision in ("", POR_VERIFICAR) else precision,
                notas=fila.get("notas", "").strip() or None,
            )
            if a.id in catalogo:
                raise ValueError(f"Catálogo: id repetido «{a.id}» (revise los nombres duplicados)")
            catalogo[a.id] = a
    return catalogo


def con_ubicacion(catalogo: dict[str, Atractivo]) -> dict[str, Atractivo]:
    """Deja solo los atractivos con latitud y longitud. Sin ubicación no hay marcador en el mapa, ni ruta,
    ni clima, y cada fila de más cuesta tokens al enviarla al modelo. El CSV no se modifica."""
    return {k: a for k, a in catalogo.items() if a.latitud is not None and a.longitud is not None}
