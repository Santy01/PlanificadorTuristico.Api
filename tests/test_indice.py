"""Fragmentación, asignación de fragmentos a atractivos y construcción de registros del RAG.
Sin modelo de embeddings ni Chroma: solo la lógica propia, rápida y determinista."""
from src.catalogo import Atractivo
from src.services.indice import (
    MAX_CARACTERES, asignar, cargar_config_rag, construir_registros, fragmentar, nombra_a, normalizar,
)


def atractivo(nombre: str, id_: str | None = None, provincia: str = "Tungurahua") -> Atractivo:
    return Atractivo(id=id_ or normalizar(nombre).replace(" ", "-"), nombre=nombre, canton=None, provincia=provincia,
                     tipo="natural", costo_usd=None, costo_aproximado=False, costo_texto=None, duracion_h=None,
                     latitud=None, longitud=None, fuente="Fuente de prueba", url_fuente=(),
                     estado_verificacion="B", precision_coord=None, notas=None)


PAILON = atractivo("Cascada Pailón del Diablo")
NARIZ = atractivo("Nariz del Diablo", provincia="Chimborazo")
QUILOTOA = atractivo("Laguna de Quilotoa", provincia="Cotopaxi")
CATALOGO = {a.id: a for a in (PAILON, NARIZ, QUILOTOA)}


def test_fragmentar_respeta_el_maximo_y_no_pierde_texto():
    texto = "\n".join(f"Línea número {i} con un poco de texto para rellenar el fragmento." for i in range(80))
    trozos = fragmentar(texto, maximo=300, solape=60)
    assert len(trozos) > 3
    assert all(len(t) <= 300 + 60 for t in trozos)
    todo = " ".join(trozos)
    assert "número 0 " in todo and "número 79 " in todo


def test_fragmentar_solapa_fragmentos_vecinos():
    texto = "\n".join(f"Oración única {i:03d} que se repite poco." for i in range(40))
    trozos = fragmentar(texto, maximo=200, solape=60)
    final_del_primero = trozos[0].split()[-3:]
    assert all(palabra in trozos[1] for palabra in final_del_primero)


def test_fragmentar_parte_una_linea_gigante():
    linea = " ".join(["palabra"] * 600)  # ~4800 caracteres en una sola línea
    trozos = fragmentar(linea)
    assert len(trozos) >= 4
    assert all(len(t) <= MAX_CARACTERES + 200 for t in trozos)


def test_fragmentar_texto_vacio():
    assert fragmentar("") == []
    assert fragmentar("  \n \n") == []


def test_nombra_a_ignora_tildes_mayusculas_y_palabras_genericas():
    assert nombra_a(normalizar("El PAILON del diablo es famoso"), PAILON)
    assert nombra_a(normalizar("la laguna Quilotoa en Cotopaxi"), QUILOTOA)
    # «cascada» sola no identifica a nadie
    assert not nombra_a(normalizar("una cascada muy bonita"), PAILON)


def test_nombra_a_exige_todas_las_palabras_distintivas():
    # «Diablo» aparece en dos atractivos; «Nariz del Diablo» necesita también «nariz»
    assert not nombra_a(normalizar("el Pailón del Diablo en Baños"), NARIZ)
    assert nombra_a(normalizar("el tren a la Nariz del Diablo"), NARIZ)


def test_asignar_con_un_solo_candidato_no_filtra():
    assert asignar("texto que ni menciona el nombre", [PAILON]) == [PAILON]


def test_asignar_con_varios_candidatos_solo_el_que_mas_se_nombra():
    texto = "El Pailón del Diablo es famoso. El Pailón del Diablo tiene un mirador. También hay una laguna Quilotoa."
    assert asignar(texto, [PAILON, NARIZ, QUILOTOA]) == [PAILON]


def test_asignar_descarta_el_fragmento_si_dos_atractivos_empatan():
    assert asignar("Visite el Pailón del Diablo y la laguna de Quilotoa.", [PAILON, NARIZ, QUILOTOA]) == []
    assert asignar("Un párrafo general sobre turismo.", [PAILON, NARIZ, QUILOTOA]) == []


def fila(doc_id, clase, ids, estado="ok", archivo="x.txt"):
    return {"doc_id": doc_id, "clase": clase, "archivo": archivo, "atractivo_ids": "|".join(ids), "fuente": "GAD",
            "url": "https://ejemplo.gob.ec/a", "tipo_fuente": "oficial (GAD)", "estado_verificacion": "B",
            "fecha_descarga": "2026-10-27", "estado": estado, "caracteres": 100}


def test_construir_registros_descarta_fragmentos_que_no_nombran_a_nadie():
    relleno = "Texto general de turismo sin ningún nombre propio de atractivo. " * 3
    texto = f"{relleno}\nEl Pailón del Diablo recibe visitantes todo el año y es muy visitado por turistas.\n"
    registros, est = construir_registros([fila("web-1", "web", [PAILON.id, NARIZ.id])], CATALOGO,
                                         lambda ruta: texto, )
    assert registros and all(r.metadatos["atractivo_id"] == PAILON.id for r in registros)
    assert all(r.metadatos["url"] == "https://ejemplo.gob.ec/a" for r in registros)


def test_construir_registros_ficha_va_completa_y_con_metadatos_para_citar():
    registros, est = construir_registros([fila("ficha-q", "ficha", [QUILOTOA.id])], CATALOGO,
                                         lambda ruta: "Laguna de Quilotoa: cráter volcánico con laguna.")
    assert len(registros) == 1
    r = registros[0]
    assert r.metadatos["provincia"] == "Cotopaxi" and r.metadatos["clase"] == "ficha"
    assert r.para_embedding.startswith("Laguna de Quilotoa (Cotopaxi):")
    assert r.documento == "Laguna de Quilotoa: cráter volcánico con laguna."


def test_construir_registros_omite_documentos_no_ok_o_sin_archivo():
    filas = [fila("w1", "web", [PAILON.id], estado="http_404", archivo=""),
             fila("w2", "web", [PAILON.id], estado="omitida_comercial", archivo="")]
    registros, _ = construir_registros(filas, CATALOGO, lambda ruta: "x" * 500)
    assert registros == []


def test_construir_registros_archivo_inexistente_no_aborta():
    def leer(ruta):
        raise FileNotFoundError(ruta)
    registros, est = construir_registros([fila("w3", "web", [PAILON.id])], CATALOGO, leer)
    assert registros == [] and est.sin_texto == ["w3"]


def test_config_rag_valores_por_defecto(monkeypatch):
    for var in ("VECTOR_DB_PATH", "VECTOR_DB_COLECCION", "EMBEDDING_MODEL", "RAG_TOP_K", "RAG_MARGEN_SIMILITUD"):
        monkeypatch.setenv(var, "")
    cfg = cargar_config_rag()
    assert cfg.coleccion == "atractivos" and cfg.top_k == 12 and cfg.margen == 0.05
    assert cfg.modelo == "intfloat/multilingual-e5-small"
    assert cfg.ruta.name == "vectorstore" and cfg.ruta.is_absolute()
