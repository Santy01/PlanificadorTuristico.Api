"""Importa al catálogo un CSV de atractivos verificado y editado en Excel, sin dejar entrar el daño de formato.

    python scripts/importar_catalogo.py data/catalogo/entrada/reducido_verificado_2026-11-07.csv
    python scripts/importar_catalogo.py ARCHIVO --simular        # solo el reporte, no escribe nada

Excel con la configuración regional de Ecuador guarda el CSV con «;», en la codificación de DOS (CP850) y con los
números «arreglados» (-1.3982 → -13.982). Si ese archivo reemplaza al catálogo, la API no arranca. Reglas:

  1. Lee el archivo con su codificación (UTF-8, CP850 o CP1252) y su separador reales.
  2. Coordenadas: rearma el número con sus dígitos (latitud: 1 dígito entero; longitud: 2) y exige que caiga en la
     zona centro. Si se aleja más de 0.01° (~1 km) del valor anterior, no lo aplica y lo reporta.
  3. Un texto cortado en un «;» (el valor nuevo es el comienzo del anterior) conserva el texto completo anterior.
  4. Un campo vacío nunca borra un dato que ya existía.
  5. Lo demás es un dato verificado por el equipo: se aplica, y si reemplaza un valor conocido queda en el reporte.

Escribe las filas en atractivos.csv (la fuente de verdad: también la usan el agente y el RAG) y reescribe
atractivos_reducido.csv con esas mismas filas en el formato correcto (UTF-8 y comas). Deja el reporte en
docs/evidencias/catalogo/. Después hay que reconstruir el corpus y el índice (ver docs/07-rag.md).
"""
from __future__ import annotations

import argparse
import csv
import io
import sys
from datetime import date
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.stdout.reconfigure(encoding="utf-8")

from src.catalogo import RUTA_CATALOGO, RUTA_REDUCIDA, _slug  # noqa: E402

ZONA_LAT = (-2.8, -0.2)      # zona centro del Ecuador, con margen
ZONA_LON = (-79.6, -77.8)
MAX_DESVIO_GRADOS = 0.01
ESTADOS = {"A", "A_parcial", "B", "C"}


# ---------------------------------------------------------------- lectura tolerante
def leer_texto(ruta: Path) -> tuple[str, str]:
    crudo = ruta.read_bytes()
    try:
        return crudo.decode("utf-8-sig"), "utf-8"
    except UnicodeDecodeError:
        pass
    # CP850 (lo que guarda Excel como «CSV (MS-DOS)») frente a CP1252: gana la que deja letras del español
    candidatos = []
    for enc in ("cp850", "cp1252"):
        texto = crudo.decode(enc, errors="replace")
        candidatos.append((sum(texto.count(c) for c in "ñáéíóúÑÁÉÍÓÚ") - 5 * texto.count("¤"), enc, texto))
    _, enc, texto = max(candidatos)
    return texto, enc


def leer_filas(texto: str) -> tuple[list[dict], str]:
    primera = texto.splitlines()[0]
    separador = ";" if primera.count(";") > primera.count(",") else ","
    return list(csv.DictReader(io.StringIO(texto), delimiter=separador)), separador


# ---------------------------------------------------------------- reglas
def rearmar_coordenada(valor: str, enteros: int) -> float | None:
    """'-13.982' / '-14047' / '-1.3982' → -1.3982 (con `enteros` dígitos antes del punto). None si no es un número."""
    v = valor.strip()
    if not v or "VERIFICAR" in v.upper():
        return None
    negativo = v.startswith("-")
    digitos = v.lstrip("-").replace(".", "").replace(",", "")
    if not digitos.isdigit() or len(digitos) <= enteros:
        return None
    x = float(digitos[:enteros] + "." + digitos[enteros:])
    return -x if negativo else x


def en_la_zona(lat: float, lon: float) -> bool:
    return ZONA_LAT[0] <= lat <= ZONA_LAT[1] and ZONA_LON[0] <= lon <= ZONA_LON[1]


def formato_coordenada(x: float, anterior: str) -> str:
    """Conserva la cantidad de decimales del valor anterior cuando el número es el mismo (diff limpio)."""
    try:
        if abs(float(anterior) - x) < 1e-9:
            return anterior
    except ValueError:
        pass
    return f"{x:.6f}".rstrip("0").rstrip(".")


def combinar(nueva: dict, anterior: dict, columnas: list[str]) -> tuple[dict, list[str]]:
    """(fila resultante, notas para el reporte)."""
    salida, notas = dict(anterior), []
    # Coordenadas (regla 2), en pareja
    lat_a, lon_a = anterior.get("latitud", ""), anterior.get("longitud", "")
    lat, lon = rearmar_coordenada(nueva.get("latitud", ""), 1), rearmar_coordenada(nueva.get("longitud", ""), 2)
    if lat is not None and lon is not None:
        if not en_la_zona(lat, lon):
            notas.append(f"coordenadas {lat}, {lon} fuera de la zona centro: se conservan las anteriores")
        else:
            try:
                desvio = max(abs(lat - float(lat_a)), abs(lon - float(lon_a)))
            except ValueError:
                desvio = 0.0  # antes no tenía coordenadas: se acepta el dato nuevo
            if desvio > MAX_DESVIO_GRADOS:
                notas.append(f"coordenadas {lat}, {lon} se alejan {desvio:.3f}° de las anteriores: no se aplican")
            else:
                salida["latitud"], salida["longitud"] = formato_coordenada(lat, lat_a), formato_coordenada(lon, lon_a)
                if desvio > 1e-9:
                    notas.append(f"coordenadas corregidas: ({lat_a}, {lon_a}) → ({salida['latitud']}, {salida['longitud']})")
    # El resto de las columnas (reglas 3, 4 y 5)
    for c in columnas:
        if c in ("latitud", "longitud", "nombre"):
            continue
        a, n = (anterior.get(c) or "").strip(), (nueva.get(c) or "").strip()
        if n == a:
            continue
        if not n:
            if a:
                notas.append(f"{c} vacío en el archivo: se conserva «{a[:60]}»")
            continue
        if ";" in a and a.startswith(n):
            continue  # cortado en el «;» por Excel: se conserva el texto completo
        if c == "estado_verificacion" and n not in ESTADOS:
            notas.append(f"estado_verificacion «{n}» no es válido: se conserva «{a}»")
            continue
        salida[c] = n
        if a and "VERIFICAR" not in a.upper():
            notas.append(f"{c}: «{a[:50]}» → «{n[:50]}»")
    return salida, notas


# ---------------------------------------------------------------- programa
def escribir(ruta: Path, columnas: list[str], filas: list[dict]) -> None:
    with open(ruta, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columnas)
        w.writeheader()
        w.writerows(filas)


def main(entrada: Path, simular: bool) -> int:
    texto, encoding = leer_texto(entrada)
    nuevas, separador = leer_filas(texto)
    with open(RUTA_CATALOGO, encoding="utf-8-sig", newline="") as f:
        lector = csv.DictReader(f)
        columnas = list(lector.fieldnames)
        catalogo = list(lector)
    if set(nuevas[0].keys()) != set(columnas):
        print(f"Las columnas no coinciden con el catálogo: {sorted(set(nuevas[0].keys()) ^ set(columnas))}")
        return 1
    indice = {_slug(r["nombre"]): i for i, r in enumerate(catalogo)}
    lineas = [f"# Importación de {entrada.name}", "",
              f"Fecha: {date.today().isoformat()} · codificación detectada: **{encoding}** · separador: «{separador}» · "
              f"{len(nuevas)} filas.", "", "Reglas: ver la cabecera de `scripts/importar_catalogo.py`.", ""]
    actualizadas, sin_coincidencia, reportes = [], [], []
    for r in nuevas:
        clave = _slug(r["nombre"])
        if clave not in indice:
            sin_coincidencia.append(r["nombre"])
            continue
        fila, notas = combinar(r, catalogo[indice[clave]], columnas)
        catalogo[indice[clave]] = fila
        actualizadas.append(fila)
        if notas:
            reportes.append((r["nombre"], notas))
    pendientes = lambda filas, c: sum("VERIFICAR" in (f[c] or "").upper() or not (f[c] or "").strip() for f in filas)
    lineas += ["## Resultado", "", "| Campo | Por verificar en estas filas |", "|---|---|"]
    lineas += [f"| {c} | {pendientes(actualizadas, c)} |" for c in ("costo_estimado", "duracion_sugerida", "canton", "latitud", "url_fuente")]
    lineas += ["", f"Filas aplicadas al catálogo: **{len(actualizadas)}**. Sin coincidencia por nombre: {sin_coincidencia or 'ninguna'}.", ""]
    lineas += ["## Decisiones y cambios de datos conocidos", ""]
    for nombre, notas in reportes:
        lineas.append(f"- **{nombre}**")
        lineas += [f"  - {n}" for n in notas]
    reporte = "\n".join(lineas) + "\n"
    print(reporte)
    if simular or sin_coincidencia:
        if sin_coincidencia:
            print("No se escribió nada: hay filas que no existen en el catálogo (¿cambió un nombre?).")
        return 0 if not sin_coincidencia else 1
    escribir(RUTA_CATALOGO, columnas, catalogo)
    escribir(RUTA_REDUCIDA, columnas, actualizadas)
    destino = RAIZ / "docs" / "evidencias" / "catalogo"
    destino.mkdir(parents=True, exist_ok=True)
    (destino / f"importacion-{entrada.stem}.md").write_text(reporte, encoding="utf-8")
    print(f"✓ {RUTA_CATALOGO.name} y {RUTA_REDUCIDA.name} actualizados; reporte en docs/evidencias/catalogo/")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("entrada", type=Path)
    ap.add_argument("--simular", action="store_true")
    a = ap.parse_args()
    sys.exit(main(a.entrada, a.simular))
