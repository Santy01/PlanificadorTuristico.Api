"""Recuperación del RAG con modelo y Chroma simulados: sin descargar nada y sin índice en disco.
Lo más importante: si el RAG falla, `recuperar` NO lanza (el itinerario sigue con el catálogo completo)."""
from pathlib import Path

from src.schemas import SolicitudItinerario
from src.services.indice import ConfigRAG
from src.services.rag import ClienteRAG, consulta_desde
from tests.test_indice import CATALOGO, NARIZ, PAILON, QUILOTOA

CFG = ConfigRAG(ruta=Path("."), coleccion="t", modelo="intfloat/multilingual-e5-small", top_k=3, margen=0.05)


class Vector(list):
    def tolist(self):
        return list(self)


class ModeloFalso:
    def __init__(self):
        self.recibido: list[str] = []

    def encode(self, textos, **kw):
        self.recibido += textos
        return Vector([[0.0, 1.0] for _ in textos])


def md(a, clase="web"):
    return {"atractivo_id": a.id, "nombre": a.nombre, "provincia": a.provincia, "tipo": a.tipo, "clase": clase,
            "fuente": "GAD", "url": "https://ejemplo.gob.ec", "tipo_fuente": "oficial (GAD)",
            "estado_verificacion": "B"}


class ColeccionFalsa:
    """Devuelve (atractivo, similitud) en el orden dado; la distancia es 1 - similitud, como en Chroma."""
    def __init__(self, filas):
        self.filas = filas
        self.llamadas: list[dict] = []

    def query(self, query_embeddings, n_results, where=None):
        self.llamadas.append({"n_results": n_results, "where": where})
        return {"ids": [[f"f{i}" for i in range(len(self.filas))]],
                "documents": [[f"texto {i}" for i in range(len(self.filas))]],
                "metadatas": [[md(a, c) for a, _, c in self.filas]],
                "distances": [[1 - s for _, s, _ in self.filas]]}


def cliente(filas):
    col = ColeccionFalsa(filas)
    return ClienteRAG(CFG, modelo=ModeloFalso(), coleccion=col), col


def solicitud(**kw):
    base = dict(dias=2, presupuesto_usd=100, punto_partida="Ambato", intereses=["natural"], notas=None)
    return SolicitudItinerario(**{**base, **kw})


def test_consulta_usa_intereses_y_notas():
    s = solicitud(intereses=["natural", "cultural"], notas="  algo tranquilo con vistas a volcanes ")
    assert consulta_desde(s) == "natural, cultural. algo tranquilo con vistas a volcanes"
    assert consulta_desde(solicitud(notas="   ")) == "natural"


def test_agrupa_por_atractivo_y_deja_entrar_al_que_un_volcan_desplazaba():
    # tres fragmentos del mismo atractivo ocupan los primeros lugares; el segundo atractivo no debe perderse
    filas = [(PAILON, .878, "web"), (PAILON, .877, "web"), (PAILON, .875, "web"), (NARIZ, .866, "web")]
    c, _ = cliente(filas)
    res = c.recuperar(solicitud(), CATALOGO)
    assert res.disponible and res.atractivo_ids == [PAILON.id, NARIZ.id]


def test_maximo_dos_fragmentos_por_atractivo():
    filas = [(PAILON, .9 - i * .001, "web") for i in range(5)]
    c, _ = cliente(filas)
    assert len(c.recuperar(solicitud(), CATALOGO).fragmentos) == 2


def test_margen_descarta_los_muy_lejanos_al_mejor():
    filas = [(PAILON, .90, "web"), (NARIZ, .87, "web"), (QUILOTOA, .70, "web")]
    c, _ = cliente(filas)
    assert c.recuperar(solicitud(), CATALOGO).atractivo_ids == [PAILON.id, NARIZ.id]


def test_respeta_top_k():
    filas = [(PAILON, .90, "web"), (NARIZ, .899, "web"), (QUILOTOA, .898, "web")]
    c, _ = ClienteRAG(ConfigRAG(Path("."), "t", "m", top_k=2, margen=.5), ModeloFalso(), ColeccionFalsa(filas)), None
    assert len(c.recuperar(solicitud(), CATALOGO).atractivo_ids) == 2


def test_descarta_lo_que_no_esta_en_el_catalogo():
    c, _ = cliente([(PAILON, .90, "web"), (NARIZ, .89, "web")])
    sin_nariz = {k: v for k, v in CATALOGO.items() if k != NARIZ.id}
    assert c.recuperar(solicitud(), sin_nariz).atractivo_ids == [PAILON.id]


def test_filtra_por_tipo_en_chroma_y_pide_un_pool_amplio():
    c, col = cliente([(PAILON, .9, "web")])
    c.recuperar(solicitud(), CATALOGO, tipos={"natural", "cultural"})
    assert col.llamadas[0]["where"] == {"tipo": {"$in": ["cultural", "natural"]}}
    assert col.llamadas[0]["n_results"] == CFG.top_k * 4
    c.recuperar(solicitud(), CATALOGO)
    assert col.llamadas[1]["where"] is None


def test_la_consulta_lleva_el_prefijo_query_de_e5():
    c, _ = cliente([(PAILON, .9, "web")])
    c.recuperar(solicitud(notas="cascadas"), CATALOGO)
    assert c._modelo.recibido == ["query: natural. cascadas"]


def test_sin_resultados_no_es_una_falla():
    c, _ = cliente([])
    res = c.recuperar(solicitud(), CATALOGO)
    assert res.disponible and res.fragmentos == [] and res.atractivo_ids == []


def test_fallo_de_chroma_degrada_sin_lanzar():
    class Rota:
        def query(self, **kw):
            raise RuntimeError("índice corrupto")
    res = ClienteRAG(CFG, ModeloFalso(), Rota()).recuperar(solicitud(), CATALOGO)
    assert not res.disponible and "índice corrupto" in res.motivo and res.fragmentos == []


def test_indice_inexistente_degrada_sin_lanzar(tmp_path):
    cfg = ConfigRAG(ruta=tmp_path / "no-existe", coleccion="atractivos", modelo="m", top_k=3, margen=.05)
    c = ClienteRAG(cfg, modelo=ModeloFalso())   # la colección real no existe en tmp_path
    res = c.recuperar(solicitud(), CATALOGO)
    assert not res.disponible and res.motivo
    assert c.precalentar() is False
