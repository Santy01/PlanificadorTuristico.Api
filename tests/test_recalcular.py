"""Herramienta recalcular: reglas deterministas sobre el catálogo verificado (sin modelo ni red)."""
from dataclasses import replace

import pytest
from pydantic import ValidationError

from src.catalogo import Atractivo, cargar_catalogo
from src.parametros import parametros
from src.schemas import AtractivoElegido, DiaModelo, ItinerarioModelo, RespuestaItinerario, SolicitudItinerario
from src.services.itinerario import AVISO_PRESUPUESTO, armar_itinerario
from src.tools.recalcular import ESQUEMA, RecalcularIn, recalcular

REAL = cargar_catalogo()
PAILON = "cascada-pailon-del-diablo"
NARIZ = "tren-ecuador-nariz-del-diablo"
QUILOTOA = "laguna-de-quilotoa"


def itinerario(catalogo, *dias, presupuesto=100) -> RespuestaItinerario:
    prop = ItinerarioModelo(
        fuera_de_alcance=False, motivo_rechazo=None, supuestos=[],
        dias=[DiaModelo(numero=i + 1, atractivos=[AtractivoElegido(id=x, motivo="m") for x in ids])
              for i, ids in enumerate(dias)])
    s = SolicitudItinerario(dias=len(dias), presupuesto_usd=presupuesto, punto_partida="Ambato", intereses=["natural"])
    return armar_itinerario(prop, s, catalogo)


def pedir(dia, quitar_id, motivo="lluvia"):
    return RecalcularIn(dia=dia, quitar_id=quitar_id, motivo=motivo)


# Catálogo mínimo para probar cada regla por separado
BASE = Atractivo(id="sale", nombre="Sale", canton="Baños", provincia="Tungurahua", tipo="natural", costo_usd=2.0,
                 costo_aproximado=False, costo_texto="2", duracion_h=2.0, latitud=-1.4, longitud=-78.4, fuente="F",
                 url_fuente=(), estado_verificacion="B", precision_coord=None, notas=None)


def at(id_, **kw) -> Atractivo:
    return replace(BASE, id=id_, nombre=id_.capitalize(), **kw)


# ---------------------------------------------------------------- caso real (el de la guía de la Entrega 3)
def test_pailon_con_lluvia_entra_uno_bajo_techo_de_tungurahua_que_no_estaba():
    it = itinerario(REAL, [PAILON, NARIZ], [QUILOTOA])
    nuevo, out = recalcular(it, pedir(1, PAILON), REAL)
    entra = REAL[out.reemplazo_id]
    assert out.aplicado and entra.provincia == "Tungurahua" and entra.tipo != "natural"
    assert out.reemplazo_id not in {PAILON, NARIZ, QUILOTOA}
    ids_dia1 = [a.atractivo_id for a in nuevo.dias[0].actividades]
    assert ids_dia1[0] == out.reemplazo_id and ids_dia1[1] == NARIZ        # mismo lugar en el orden de visita
    assert "Pailón" in nuevo.dias[0].actividades[0].motivo
    assert out.aviso in nuevo.advertencias


def test_no_modifica_el_itinerario_original():
    it = itinerario(REAL, [PAILON, NARIZ], [QUILOTOA])
    antes = it.model_dump()
    recalcular(it, pedir(1, PAILON), REAL)
    assert it.model_dump() == antes


def test_es_determinista():
    it = itinerario(REAL, [PAILON, NARIZ], [QUILOTOA])
    a = recalcular(it, pedir(1, PAILON, "cerrado"), REAL)[1]
    b = recalcular(it, pedir(1, PAILON, "cerrado"), REAL)[1]
    assert a == b


def test_horas_y_costos_se_reponen_igual_que_al_armar():
    it = itinerario(REAL, [PAILON, NARIZ], [QUILOTOA])
    nuevo, out = recalcular(it, pedir(1, PAILON), REAL)
    d1 = nuevo.dias[0]
    assert d1.horas_total == sum(a.duracion_h for a in d1.actividades) == out.horas_dia
    assert d1.costo_parcial_usd == sum(a.costo_usd or 0 for a in d1.actividades) == out.costo_dia_usd
    assert nuevo.costo_total_usd == sum(d.costo_parcial_usd for d in nuevo.dias) == out.costo_total_usd


# ---------------------------------------------------------------- cuando no se aplica
def test_atractivo_de_otro_dia_devuelve_aviso_y_el_mismo_itinerario():
    it = itinerario(REAL, [PAILON, NARIZ], [QUILOTOA])
    nuevo, out = recalcular(it, pedir(2, PAILON), REAL)
    assert not out.aplicado and "no está en el día 2" in out.aviso and nuevo is it


def test_dia_inexistente():
    it = itinerario(REAL, [PAILON])
    _, out = recalcular(it, pedir(3, PAILON), REAL)
    assert not out.aplicado and "no tiene día 3" in out.aviso


def test_itinerario_no_generado_no_se_recalcula():
    it = RespuestaItinerario(estado="rechazado", mensaje="fuera de alcance")
    _, out = recalcular(it, pedir(1, PAILON), REAL)
    assert not out.aplicado


def test_sin_candidatos_lo_revisa_un_asesor():
    cat = {"sale": BASE, "otra-natural": at("otra-natural")}       # con lluvia, la única opción es al aire libre
    _, out = recalcular(itinerario(cat, ["sale"]), pedir(1, "sale"), cat)
    assert not out.aplicado and "asesor" in out.aviso


# ---------------------------------------------------------------- cada regla
def test_regla_misma_provincia():
    cat = {"sale": BASE, "lejos": at("lejos", tipo="cultural", provincia="Cotopaxi")}
    assert not recalcular(itinerario(cat, ["sale"]), pedir(1, "sale"), cat)[1].aplicado


def test_regla_no_repite_lo_que_ya_esta_en_el_viaje():
    cat = {"sale": BASE, "museo": at("museo", tipo="cultural")}
    it = itinerario(cat, ["sale"], ["museo"])
    assert not recalcular(it, pedir(1, "sale"), cat)[1].aplicado


def test_regla_cabe_en_el_hueco():
    holgura = parametros().recalcular.holgura_h
    cat = {"sale": BASE, "largo": at("largo", tipo="cultural", duracion_h=BASE.duracion_h + holgura + 0.5),
           "justo": at("justo", tipo="cultural", duracion_h=BASE.duracion_h + holgura)}
    assert recalcular(itinerario(cat, ["sale"]), pedir(1, "sale"), cat)[1].reemplazo_id == "justo"


def test_regla_no_supera_la_jornada():
    jornada = parametros().itinerario.jornada_max_h
    cat = {"sale": BASE, "relleno": at("relleno", tipo="cultural", duracion_h=jornada - BASE.duracion_h),
           "mas-largo": at("mas-largo", tipo="cultural", duracion_h=BASE.duracion_h + 0.5)}
    _, out = recalcular(itinerario(cat, ["sale", "relleno"]), pedir(1, "sale"), cat)
    assert not out.aplicado          # cabría en el hueco (holgura), pero el día pasaría de la jornada


def test_sin_lluvia_un_natural_si_sirve():
    cat = {"sale": BASE, "otra-natural": at("otra-natural")}
    assert recalcular(itinerario(cat, ["sale"]), pedir(1, "sale", "cerrado"), cat)[1].reemplazo_id == "otra-natural"


def test_prefiere_mismo_canton_y_mismo_tipo_y_mejor_verificado():
    cat = {"sale": BASE,
           "otro-canton": at("otro-canton", canton="Pelileo", estado_verificacion="A"),
           "otro-tipo": at("otro-tipo", tipo="cultural", estado_verificacion="A"),
           "mismo-c": at("mismo-c", estado_verificacion="C"),
           "mismo-a": at("mismo-a", estado_verificacion="A")}
    assert recalcular(itinerario(cat, ["sale"]), pedir(1, "sale", "preferencia"), cat)[1].reemplazo_id == "mismo-a"


def test_quita_el_reemplazo_de_las_alternativas_de_lluvia():
    from src.schemas import Alternativa
    cat = {"sale": BASE, "museo": at("museo", tipo="cultural")}
    it = itinerario(cat, ["sale"])
    it.dias[0].alternativas = [Alternativa(atractivo_id="museo", nombre="Museo", canton="Baños", provincia="Tungurahua",
                                           tipo="cultural", estado_verificacion="B", motivo="m")]
    nuevo, _ = recalcular(it, pedir(1, "sale"), cat)
    assert nuevo.dias[0].alternativas == []


def test_presupuesto_excedido_se_actualiza_sin_duplicar_el_aviso():
    cat = {"sale": BASE, "caro": at("caro", tipo="cultural", costo_usd=50.0)}
    it = itinerario(cat, ["sale"], presupuesto=10)
    nuevo, _ = recalcular(it, pedir(1, "sale"), cat, presupuesto_usd=10)
    assert nuevo.presupuesto_excedido and nuevo.advertencias.count(AVISO_PRESUPUESTO) == 1


# ---------------------------------------------------------------- esquema
@pytest.mark.parametrize("datos", [
    {"dia": 0, "quitar_id": "x", "motivo": "lluvia"},
    {"dia": 1, "quitar_id": "x", "motivo": "terremoto"},
    {"dia": 1, "quitar_id": "", "motivo": "lluvia"},
    {"dia": 1, "quitar_id": "x", "motivo": "lluvia", "pagar": True},
])
def test_entrada_invalida_se_rechaza_antes_de_ejecutar(datos):
    with pytest.raises(ValidationError):
        RecalcularIn(**datos)


def test_esquema_para_la_api():
    f = ESQUEMA["function"]
    assert ESQUEMA["type"] == "function" and f["name"] == "recalcular"
    assert set(f["parameters"]["required"]) == {"dia", "quitar_id", "motivo"}
    assert f["parameters"]["additionalProperties"] is False
    assert f["parameters"]["properties"]["motivo"]["enum"] == ["lluvia", "cerrado", "preferencia"]
