"""Reglas del código sobre la propuesta del modelo + endpoint, con un doble del servicio de IA (sin gastar API)."""
import json

from fastapi.testclient import TestClient

from src.catalogo import cargar_catalogo, parsear_costo
from src.main import app, obtener_llm
from src.schemas import AtractivoElegido, DiaModelo, ItinerarioModelo, SolicitudItinerario
from src.services.itinerario import JORNADA_MAX_H, armar_itinerario
from src.services.llm import ProveedorNoDisponible, Resultado, SalidaInvalida

CATALOGO = cargar_catalogo()
SIN_DATOS = "paisaje-cultural-del-punay"  # costo y coordenadas POR VERIFICAR
SOLICITUD = {"dias": 2, "presupuesto_usd": 100, "punto_partida": "Ambato", "intereses": ["natural"]}


def propuesta(*dias, rechazo=None, supuestos=()):
    return ItinerarioModelo(
        fuera_de_alcance=rechazo is not None, motivo_rechazo=rechazo, supuestos=list(supuestos),
        dias=[DiaModelo(numero=i + 1, atractivos=[AtractivoElegido(id=x, motivo="m") for x in ids])
              for i, ids in enumerate(dias)])


def armar(p, **kw):
    return armar_itinerario(p, SolicitudItinerario(**{**SOLICITUD, **kw}), CATALOGO)


# ---------------------------------------------------------------- catálogo
def test_catalogo_carga_todo_el_catalogo_con_ids_unicos():
    assert len(CATALOGO) == 139 and "laguna-de-quilotoa" in CATALOGO
    assert CATALOGO[SIN_DATOS].costo_usd is None and CATALOGO[SIN_DATOS].latitud is None  # POR VERIFICAR no se inventa


def test_costos_en_texto_se_interpretan():
    assert parsear_costo("2.00-2.50")[:2] == (2.5, True)             # rango → el más alto, aproximado
    assert parsear_costo("desde 18.00")[:2] == (18.0, True)
    assert parsear_costo("0 (espacio público; inferido)")[:2] == (0.0, True)
    assert parsear_costo("3.00 (paseo en tarabita)")[:2] == (3.0, False)
    assert parsear_costo("POR VERIFICAR") == (None, False, None)


def test_catalogo_lee_archivo_con_bom(tmp_path):
    f = tmp_path / "c.csv"
    f.write_text("nombre,canton,provincia,tipo,costo_estimado,duracion_sugerida,latitud,longitud,fuente\n"
                 "Sitio Uno,X,Y,natural,1.5,2,-1.0,-78.0,F\n", encoding="utf-8-sig")
    assert cargar_catalogo(f)["sitio-uno"].costo_usd == 1.5


# ---------------------------------------------------------------- el código dispone
def test_atractivo_inventado_se_descarta_y_se_avisa():
    r = armar(propuesta(["laguna-de-quilotoa", "galapagos"], ["laguna-de-limpiopungo"]))
    nombres = [a.atractivo_id for d in r.dias for a in d.actividades]
    assert "galapagos" not in nombres and any("no pertenecen al catálogo" in w for w in r.advertencias)


def test_todo_inventado_va_a_revision_humana():
    assert armar(propuesta(["x"], ["y"])).estado == "revision_humana"


def test_repetidos_se_quitan():
    r = armar(propuesta(["laguna-de-quilotoa"], ["laguna-de-quilotoa", "laguna-de-limpiopungo"]))
    assert sum(len(d.actividades) for d in r.dias) == 2 and any("repetida" in w for w in r.advertencias)


def test_costos_por_verificar_dan_total_parcial():
    r = armar(propuesta([SIN_DATOS, "laguna-de-quilotoa"], []))
    assert r.costo_parcial is True and r.costo_total_usd == 2.0 and any("por verificar" in w for w in r.advertencias)


def test_excedente_de_jornada_se_redistribuye():
    # Chimborazo 4 h + Quilotoa 4 h + Cotopaxi 5 h no caben en un día de 8 h
    r = armar(propuesta(["volcan-chimborazo-reserva-de-produccion-de-fauna-chimborazo", "laguna-de-quilotoa",
                         "parque-nacional-cotopaxi"], []))
    assert all(d.horas_total <= JORNADA_MAX_H for d in r.dias) and r.dias[1].actividades
    assert any("redistribuyeron" in w for w in r.advertencias)


def test_siempre_devuelve_el_numero_de_dias_pedido():
    assert len(armar(propuesta(["laguna-de-quilotoa"]), dias=3).dias) == 3


def test_sin_coordenadas_no_hay_marcador():
    a = armar(propuesta([SIN_DATOS], [])).dias[0].actividades[0]
    assert a.latitud is None and a.longitud is None and a.precision_coord is None and a.fuente


def test_cita_la_fuente_del_catalogo():
    a = armar(propuesta(["laguna-de-quilotoa"], [])).dias[0].actividades[0]
    assert a.fuente != "" and a.url_fuente and a.estado_verificacion in ("A", "A_parcial", "B", "C")


def test_costo_aproximado_se_avisa():
    r = armar(propuesta(["cascada-pailon-del-diablo"], []))
    assert r.dias[0].actividades[0].costo_aproximado and any("aproximados" in w for w in r.advertencias)


# ---------------------------------------------------------------- endpoint
class LLMFalso:
    def __init__(self, datos=None, error=None):
        self.datos, self.error = datos, error

    def generar_json(self, system, usuario, esquema):
        assert "<catalogo" in usuario  # el modelo recibe el catálogo
        if self.error:
            raise self.error
        return Resultado(self.datos, "groq", "m", 10, 5, 100, 1)


def con(llm):
    app.dependency_overrides[obtener_llm] = lambda: llm
    return TestClient(app)


def test_health():
    assert con(LLMFalso()).get("/health").json() == {"status": "ok"}


def test_itinerario_ok():
    r = con(LLMFalso(propuesta(["laguna-de-quilotoa"], ["laguna-de-limpiopungo"]))).post("/itinerario", json=SOLICITUD)
    j = r.json()
    assert r.status_code == 200 and j["estado"] == "ok" and len(j["dias"]) == 2 and j["proveedor"] == "groq"


def test_fuera_de_alcance_se_rechaza_sin_itinerario():
    r = con(LLMFalso(propuesta(rechazo="No puedo reservar."))).post("/itinerario", json=SOLICITUD)
    assert r.json()["estado"] == "rechazado" and r.json()["dias"] == [] and "reservar" in r.json()["mensaje"]


def test_proveedor_caido_da_503_con_mensaje_claro():
    r = con(LLMFalso(error=ProveedorNoDisponible())).post("/itinerario", json=SOLICITUD)
    assert r.status_code == 503 and "no está disponible" in r.json()["detail"]


def test_salida_invalida_va_a_revision_humana():
    r = con(LLMFalso(error=SalidaInvalida())).post("/itinerario", json=SOLICITUD)
    assert r.json()["estado"] == "revision_humana"


def test_parametros_fuera_de_rango_se_rechazan_antes_del_modelo():
    for malo in ({"dias": 0}, {"dias": 30}, {"intereses": []}, {"notas": "x" * 5000}, {"presupuesto_usd": -5}):
        assert con(LLMFalso(propuesta([], []))).post("/itinerario", json={**SOLICITUD, **malo}).status_code == 422


# ---------------------------------------------------------------- stream (SSE)
def eventos(cuerpo: str):
    salida = []
    for bloque in cuerpo.strip().split("\n\n"):
        nombre, dato = bloque.split("\n", 1)
        salida.append((nombre.removeprefix("event: "), json.loads(dato.removeprefix("data: "))))
    return salida


class LLMStream:
    def __init__(self, trozos=(), error=None, json_fallback=None):
        self.trozos, self.error, self.json_fallback = list(trozos), error, json_fallback

    def generar_stream(self, system, mensajes, esquema=None):
        assert esquema is ItinerarioModelo and "<catalogo" in mensajes[0]["content"]
        yield from self.trozos
        if self.error:
            raise self.error

    def generar_json(self, system, usuario, esquema):
        if self.error:
            raise self.error
        return Resultado(self.json_fallback, "groq", "m", 1, 1, 1, 1)


def test_stream_emite_texto_y_luego_itinerario_validado():
    texto = propuesta(["laguna-de-quilotoa", "galapagos"], ["laguna-de-limpiopungo"]).model_dump_json()
    ev = eventos(con(LLMStream([texto[:30], texto[30:]])).post("/itinerario/stream", json=SOLICITUD).text)
    assert [e for e, _ in ev] == ["texto", "texto", "itinerario"]
    final = ev[-1][1]
    assert final["estado"] == "ok" and "galapagos" not in str(final["dias"])  # lo validado, no lo escrito en vivo


def test_stream_fuera_de_alcance():
    texto = propuesta(rechazo="No puedo reservar.").model_dump_json()
    ev = eventos(con(LLMStream([texto])).post("/itinerario/stream", json=SOLICITUD).text)
    assert ev[-1][0] == "itinerario" and ev[-1][1]["estado"] == "rechazado"


def test_stream_json_incompleto_recurre_a_la_via_con_correccion():
    ok = propuesta(["laguna-de-quilotoa"], [])
    ev = eventos(con(LLMStream(['{"dias": ['], json_fallback=ok)).post("/itinerario/stream", json=SOLICITUD).text)
    assert ev[-1][0] == "itinerario" and ev[-1][1]["estado"] == "ok"


def test_stream_proveedor_caido_emite_evento_error():
    ev = eventos(con(LLMStream(error=ProveedorNoDisponible())).post("/itinerario/stream", json=SOLICITUD).text)
    assert ev == [("error", "El asistente no está disponible en este momento. Intenta de nuevo en unos minutos.")]


def test_catalogo_del_servicio_es_reducido_equilibrado_y_con_ubicacion():
    from collections import Counter
    from src.main import obtener_catalogo
    util = obtener_catalogo()
    assert len(util) == 60 and SIN_DATOS not in util and util.keys() <= CATALOGO.keys()
    assert all(a.latitud is not None and a.longitud is not None for a in util.values())
    por_provincia = Counter(a.provincia for a in util.values())
    assert set(por_provincia) == {"Tungurahua", "Chimborazo", "Cotopaxi", "Bolívar"}
    assert set(por_provincia.values()) == {15}                       # cantidades iguales por provincia
    assert {t for t in ("natural", "cultural", "gastronómico")} <= {a.tipo for a in util.values()}
    for prov in por_provincia:                                       # mismas cantidades por provincia y categoría
        por_tipo = Counter(a.tipo for a in util.values() if a.provincia == prov)
        assert dict(por_tipo) == {"natural": 5, "cultural": 5, "gastronómico": 5}, (prov, por_tipo)


def test_curar_catalogo_es_determinista():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import curar_catalogo
    assert [a.id for a in curar_catalogo.curar(60)] == [a.id for a in curar_catalogo.curar(60)]


def test_atractivo_sin_ubicacion_que_inventa_el_modelo_se_descarta():
    util = {k: a for k, a in CATALOGO.items() if a.latitud is not None}
    r = armar_itinerario(propuesta([SIN_DATOS, "laguna-de-quilotoa"], []), SolicitudItinerario(**SOLICITUD), util)
    assert [a.atractivo_id for d in r.dias for a in d.actividades] == ["laguna-de-quilotoa"]
