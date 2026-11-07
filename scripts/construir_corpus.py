"""Construye el corpus de documentos que alimentará el RAG (fase 1).

    python scripts/construir_corpus.py              # fichas + descarga de las URL del catálogo
    python scripts/construir_corpus.py --sin-red    # solo las fichas (no descarga nada)

Genera:
  data/raw/fichas/<id>.md     una ficha por atractivo, con lo que el catálogo SÍ sabe (no versionado)
  data/raw/web/<hash>.txt     texto limpio de cada página fuente descargada (no versionado)
  data/corpus/manifiesto.csv  una fila por documento: fuente, URL, fecha de descarga, atractivos y estado
                              (SÍ se versiona: es la trazabilidad que pide docs/04-fuentes.md)

Reglas:
  - Los datos «POR VERIFICAR» no entran a las fichas: no se indexa lo que no se sabe.
  - Las páginas comerciales (agencias de viaje, reservas) no se descargan: no son fuente verificable.
  - Una página que no se pueda descargar o que casi no tenga texto se registra con su estado, sin abortar.
El catálogo NO se modifica.
"""
import argparse
import csv
import hashlib
import io
import re
import sys
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

import httpx
from pypdf import PdfReader

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from src.catalogo import RUTA_CATALOGO, _slug, cargar_catalogo  # noqa: E402

DIR_FICHAS = RAIZ / "data" / "raw" / "fichas"
DIR_WEB = RAIZ / "data" / "raw" / "web"
MANIFIESTO = RAIZ / "data" / "corpus" / "manifiesto.csv"
CAMPOS = ["doc_id", "clase", "archivo", "atractivo_ids", "fuente", "url", "tipo_fuente",
          "estado_verificacion", "fecha_descarga", "estado", "caracteres"]

COMERCIALES = ("travelocity.com", "expedia.com", "civitatis.com", "journeylatinamerica.com",
               "quantocustaviajar.com", "tripadvisor", "booking.com", "viator.com", "getyourguide")
# Revisadas a mano: la página no trata del atractivo (la nota que la cita lo menciona de paso).
IRRELEVANTES = ("ministerio-ambiente-denuncia-extorsion-chimborazo",)
MIN_CARACTERES = 400
NL = chr(10)
TIMEOUT_S = 20
NAVEGADOR = {"User-Agent": "Mozilla/5.0 (compatible; PlanificadorTuristicoEdu/0.1; proyecto academico)"}


class ExtractorTexto(HTMLParser):
    """HTML -> texto plano con la biblioteca estándar (sin dependencias nuevas)."""
    IGNORAR = {"script", "style", "noscript", "nav", "header", "footer", "aside", "form", "svg", "iframe"}
    BLOQUES = {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "section", "article"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.partes: list[str] = []
        self._ignorando = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.IGNORAR:
            self._ignorando += 1
        elif tag in self.BLOQUES:
            self.partes.append("\n")

    def handle_endtag(self, tag):
        if tag in self.IGNORAR and self._ignorando:
            self._ignorando -= 1
        elif tag in self.BLOQUES:
            self.partes.append("\n")

    def handle_data(self, data):
        if not self._ignorando:
            self.partes.append(data)

    def texto(self) -> str:
        crudo = "".join(self.partes)
        lineas = [re.sub(r"[ \t ]+", " ", l).strip() for l in crudo.splitlines()]
        # una línea muy corta suele ser menú o botón; los párrafos reales son más largos
        utiles = [l for l in lineas if len(l) >= 40]
        return "\n\n".join(utiles)


def ficha(a) -> str:
    """Solo lo que el catálogo sabe. Nada de «POR VERIFICAR»."""
    lineas = [f"# {a.nombre}", "",
              f"{a.nombre} es un atractivo de tipo {a.tipo} ubicado en "
              + (f"el cantón {a.canton}, " if a.canton else "") + f"provincia de {a.provincia}, Ecuador."]
    if a.duracion_h is not None:
        lineas.append(f"Duración sugerida de la visita: {a.duracion_h:g} horas.")
    if a.costo_texto:
        lineas.append(f"Costo de ingreso reportado: USD {a.costo_texto}"
                      + (" (aproximado; confirmar tarifa vigente)." if a.costo_aproximado else "."))
    if a.notas:
        lineas += ["", a.notas.rstrip(".") + "."]
    lineas += ["", f"Fuente: {a.fuente}. Estado de verificación: {a.estado_verificacion}."]
    return "\n".join(lineas) + "\n"


def leer_tipos_fuente() -> dict[str, str]:
    with open(RUTA_CATALOGO, encoding="utf-8-sig", newline="") as f:
        return {_slug(fila["nombre"]): fila.get("tipo_fuente", "").strip() for fila in csv.DictReader(f)}


def texto_pdf(contenido: bytes) -> str:
    """Texto de un PDF con capa de texto. Un PDF escaneado (solo imagen) sale vacío y queda como
    «sin_texto_suficiente» en el manifiesto: haría falta OCR, que no se aplica."""
    try:
        paginas = [(p.extract_text() or "") for p in PdfReader(io.BytesIO(contenido)).pages]
    except Exception:  # noqa: BLE001 — un PDF dañado no debe abortar la construcción del corpus
        return ""
    lineas = [re.sub(r"[ \t\u00a0]+", " ", l).strip() for l in NL.join(paginas).splitlines()]
    return NL.join(l for l in lineas if l)


def descargar(cliente: httpx.Client, url: str) -> tuple[str | None, str]:
    """(texto, estado). El estado queda en el manifiesto."""
    try:
        r = cliente.get(url)
    except httpx.HTTPError as e:
        return None, f"error_red:{type(e).__name__}"
    if r.status_code != 200:
        return None, f"http_{r.status_code}"
    tipo = r.headers.get("content-type", "")
    if "pdf" in tipo or r.content[:5] == b"%PDF-":
        texto = texto_pdf(r.content)
    elif "html" in tipo or "text" in tipo:
        extractor = ExtractorTexto()
        extractor.feed(r.text)
        texto = extractor.texto()
    else:
        return None, "formato_no_soportado"
    return (texto, "ok") if len(texto) >= MIN_CARACTERES else (texto or None, "sin_texto_suficiente")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sin-red", action="store_true", help="solo genera las fichas")
    args = ap.parse_args()

    catalogo = cargar_catalogo()
    tipos = leer_tipos_fuente()
    hoy = date.today().isoformat()
    filas: list[dict] = []

    DIR_FICHAS.mkdir(parents=True, exist_ok=True)
    for a in catalogo.values():
        ruta = DIR_FICHAS / f"{a.id}.md"
        texto = ficha(a)
        ruta.write_text(texto, encoding="utf-8")
        filas.append({"doc_id": f"ficha-{a.id}", "clase": "ficha", "archivo": ruta.relative_to(RAIZ).as_posix(),
                      "atractivo_ids": a.id, "fuente": a.fuente, "url": "", "tipo_fuente": tipos.get(a.id, ""),
                      "estado_verificacion": a.estado_verificacion, "fecha_descarga": hoy, "estado": "ok",
                      "caracteres": len(texto)})
    print(f"Fichas generadas: {len(catalogo)}")

    if not args.sin_red:
        por_url: dict[str, list] = {}
        for a in catalogo.values():
            for u in a.url_fuente:
                por_url.setdefault(u, []).append(a)
        DIR_WEB.mkdir(parents=True, exist_ok=True)
        resumen: dict[str, int] = {}
        with httpx.Client(headers=NAVEGADOR, timeout=TIMEOUT_S, follow_redirects=True) as cliente:
            for url, atractivos in sorted(por_url.items()):
                dominio = urlparse(url).netloc.lower()
                if any(c in dominio for c in COMERCIALES):
                    texto, estado = None, "omitida_comercial"
                elif any(i in url for i in IRRELEVANTES):
                    texto, estado = None, "excluida_irrelevante"
                else:
                    texto, estado = descargar(cliente, url)
                digest = hashlib.sha1(url.encode()).hexdigest()[:12]
                archivo = ""
                if texto and estado == "ok":
                    ruta = DIR_WEB / f"{digest}.txt"
                    ruta.write_text(texto, encoding="utf-8")
                    archivo = ruta.relative_to(RAIZ).as_posix()
                resumen[estado] = resumen.get(estado, 0) + 1
                # una página puede respaldar varios atractivos: se conserva la peor calidad (la más prudente)
                peor = max((x.estado_verificacion for x in atractivos), key=lambda e: {"A": 0, "A_parcial": 1, "B": 2, "C": 3}.get(e, 3))
                filas.append({"doc_id": f"web-{digest}", "clase": "web", "archivo": archivo,
                              "atractivo_ids": "|".join(x.id for x in atractivos),
                              "fuente": atractivos[0].fuente, "url": url,
                              "tipo_fuente": tipos.get(atractivos[0].id, ""), "estado_verificacion": peor,
                              "fecha_descarga": hoy, "estado": estado, "caracteres": len(texto or "")})
                print(f"  [{estado}] {url}")
        print("Páginas:", resumen)

    MANIFIESTO.parent.mkdir(parents=True, exist_ok=True)
    with open(MANIFIESTO, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CAMPOS)
        w.writeheader()
        w.writerows(filas)
    print(f"Manifiesto: {MANIFIESTO.relative_to(RAIZ)} ({len(filas)} documentos)")


if __name__ == "__main__":
    main()
