"""Clima (Open-Meteo) con transporte simulado: sin internet y sin gastar nada.
Lo más importante: si el clima falla, el itinerario SIGUE saliendo bien."""
import json
from datetime import date, timedelta

import httpx
from fastapi.testclient import TestClient

from src.catalogo import cargar_catalogo
from src.main import app, obtener_catalogo, obtener_clima, obtener_llm
from src.schemas import AtractivoElegido, DiaModelo, ItinerarioModelo, SolicitudItinerario
from src.services.clima import ClienteClima
from src.services.itinerario import agregar_clima, armar_itinerario
from src.services.llm import Resultado

CATALOGO = cargar_catalogo()
IDS_SERVICIO = list(obtener_catalogo())   # ids del catálogo que ve la API (reducido y con ubicación)
HOY = date(2026, 10, 24)
MANANA = HOY + timedelta(days=1)


def pronostico_json(codigo=3, mm=0.0, prob=20):
    return {"daily": {"weather_code": [codigo], "temperature_2m_max": [18.5], "temperature_2m_min": [7.0],
                      "precipitation_sum": [mm], "precipitation_probability_max": [prob]}}


def clima_con(manejador, **kw):
    return ClienteClima(base_url="https://x.test/v1", timeout_s=1, transport=httpx.MockTransport(manejador),
                        hoy=lambda: HOY, **kw)


def siempre(cuerpo=None, estado=200):
    llamadas = []

    def manejador(req: httpx.Request):
        llamadas.append(req)
        return httpx.Response(estado, json=cuerpo if cuerpo is not None else pronostico_json())
    return manejador, llamadas


def se_cae(req):
    raise httpx.ConnectError("sin internet")


# ---------------------------------------------------------------- el cliente
def test_pronostico_ok_en_espanol():
    m, llamadas = siempre(pronostico_json(codigo=63, mm=4.0, prob=80))
    c = clima_con(m).pronostico(-1.39, -78.4, MANANA)
    assert c.disponible and c.resumen == "Lluvia moderada" and c.temp_max_c == 18.5 and c.fuente == "Open-Meteo"
    assert c.lluvia_intensa is False
    q = llamadas[0].url.params
    assert q["start_date"] == MANANA.isoformat() and q["timezone"] == "America/Guayaquil"


def test_lluvia_intensa_por_milimetros_o_codigo():
    assert clima_con(siempre(pronostico_json(codigo=3, mm=12.0))[0]).pronostico(-1.3, -78.4, MANANA).lluvia_intensa
    assert clima_con(siempre(pronostico_json(codigo=95, mm=1.0))[0]).pronostico(-1.3, -78.4, MANANA).lluvia_intensa


def test_api_caida_no_lanza_y_marca_no_disponible():
    c = clima_con(se_cae).pronostico(-1.39, -78.4, MANANA)
    assert c.disponible is False and "no respondió" in c.motivo_no_disponible


def test_error_500_timeout_y_json_raro_no_lanzan():
    assert not clima_con(siempre({"error": True}, 500)[0]).pronostico(-1.3, -78.4, MANANA).disponible

    def lento(req):
        raise httpx.ReadTimeout("tiempo agotado")
    assert not clima_con(lento).pronostico(-1.3, -78.4, MANANA).disponible
    assert not clima_con(siempre({"otra": "cosa"})[0]).pronostico(-1.3, -78.4, MANANA).disponible
    assert not clima_con(lambda r: httpx.Response(200, text="<html>no json</html>")).pronostico(-1.3, -78.4, MANANA).disponible


def test_reintenta_una_vez_y_se_recupera():
    intentos = []

    def inestable(req):
        intentos.append(1)
        return httpx.Response(503) if len(intentos) == 1 else httpx.Response(200, json=pronostico_json())
    assert clima_con(inestable).pronostico(-1.3, -78.4, MANANA).disponible and len(intentos) == 2


def test_sin_fecha_sin_coordenadas_o_fuera_de_rango_no_llama_a_la_api():
    m, llamadas = siempre()
    c = clima_con(m)
    assert "fecha de inicio" in c.pronostico(-1.3, -78.4, None).motivo_no_disponible
    assert "ubicación" in c.pronostico(None, None, MANANA).motivo_no_disponible
    assert "próximos" in c.pronostico(-1.3, -78.4, HOY + timedelta(days=60)).motivo_no_disponible
    assert "pasó" in c.pronostico(-1.3, -78.4, HOY - timedelta(days=1)).motivo_no_disponible
    assert llamadas == []


def test_cache_evita_repetir_la_misma_consulta():
    m, llamadas = siempre()
    c = clima_con(m)
    c.pronostico(-1.391, -78.401, MANANA)
    c.pronostico(-1.392, -78.399, MANANA)   # mismo lugar a 2 decimales
    assert len(llamadas) == 1


# ---------------------------------------------------------------- integración con el itinerario
def propuesta(*dias):
    return ItinerarioModelo(fuera_de_alcance=False, motivo_rechazo=None, supuestos=[],
                            dias=[DiaModelo(numero=i + 1, atractivos=[AtractivoElegido(id=x, motivo="m") for x in ids])
                                  for i, ids in enumerate(dias)])


def solicitud(**kw):
    return SolicitudItinerario(**{"dias": 2, "presupuesto_usd": 100, "punto_partida": "Ambato",
                                  "intereses": ["natural"], "fecha_inicio": date.today() + timedelta(days=1), **kw})


def test_cada_dia_trae_fecha_y_clima():
    s = solicitud()
    r = armar_itinerario(propuesta(["cascada-pailon-del-diablo"], ["laguna-de-quilotoa"]), s, CATALOGO)
    agregar_clima(r, CATALOGO, ClienteClima(
        base_url="https://x.test/v1", transport=httpx.MockTransport(siempre()[0]), hoy=date.today))
    assert [d.fecha for d in r.dias] == [s.fecha_inicio, s.fecha_inicio + timedelta(days=1)]
    assert all(d.clima.disponible for d in r.dias) and r.dias[0].clima.lugar_referencia == "Cascada Pailón del Diablo"


def test_lluvia_intensa_sugiere_alternativas_del_catalogo():
    s = solicitud(dias=1)
    r = armar_itinerario(propuesta(["cascada-pailon-del-diablo"]), s, CATALOGO)
    clima = ClienteClima(base_url="https://x.test/v1", hoy=date.today,
                         transport=httpx.MockTransport(siempre(pronostico_json(codigo=65, mm=30.0))[0]))
    agregar_clima(r, CATALOGO, clima)
    alt = r.dias[0].alternativas
    assert alt and len(alt) <= 3 and all(a.atractivo_id in CATALOGO and a.tipo != "natural" for a in alt)
    assert all(a.provincia == "Tungurahua" for a in alt) and any("lluvia intensa" in w for w in r.advertencias)


def test_si_el_codigo_del_clima_revienta_igual_se_entrega_el_itinerario():
    class Roto:
        def pronostico(self, *a):
            raise RuntimeError("bug inesperado")
    r = armar_itinerario(propuesta(["cascada-pailon-del-diablo"], []), solicitud(), CATALOGO)
    agregar_clima(r, CATALOGO, Roto())
    assert r.estado == "ok" and r.dias[0].actividades and r.dias[0].clima.disponible is False


# ---------------------------------------------------------------- endpoints de punta a punta
class LLMFalso:
    def __init__(self, datos):
        self.datos = datos

    def generar_json(self, system, usuario, esquema):
        return Resultado(self.datos, "groq", "m", 1, 1, 1, 1)

    def generar_stream(self, system, mensajes, esquema=None):
        yield self.datos.model_dump_json()


def cliente_http(clima):
    app.dependency_overrides[obtener_llm] = lambda: LLMFalso(propuesta([IDS_SERVICIO[0]], [IDS_SERVICIO[1]]))
    app.dependency_overrides[obtener_clima] = lambda: clima
    return TestClient(app)


BODY = {"dias": 2, "presupuesto_usd": 100, "punto_partida": "Ambato", "intereses": ["natural"],
        "fecha_inicio": (date.today() + timedelta(days=1)).isoformat()}


def clima_caido():
    return ClienteClima(base_url="https://x.test/v1", transport=httpx.MockTransport(se_cae), hoy=date.today)


def test_endpoint_con_open_meteo_caido_sigue_devolviendo_el_itinerario():
    r = cliente_http(clima_caido()).post("/itinerario", json=BODY)
    j = r.json()
    assert r.status_code == 200 and j["estado"] == "ok" and len(j["dias"]) == 2
    assert all(d["clima"]["disponible"] is False for d in j["dias"]) and any("pronóstico" in w for w in j["advertencias"])


def test_stream_con_open_meteo_caido_sigue_entregando_el_itinerario():
    cuerpo = cliente_http(clima_caido()).post("/itinerario/stream", json=BODY).text
    nombre, dato = cuerpo.strip().split("\n\n")[-1].split("\n", 1)
    j = json.loads(dato.removeprefix("data: "))
    assert nombre == "event: itinerario" and j["estado"] == "ok" and j["dias"][0]["clima"]["disponible"] is False


def test_endpoint_con_clima_funcionando():
    clima = ClienteClima(base_url="https://x.test/v1", transport=httpx.MockTransport(siempre()[0]), hoy=date.today)
    j = cliente_http(clima).post("/itinerario", json=BODY).json()
    assert j["dias"][0]["clima"]["resumen"] == "Nublado" and j["dias"][1]["fecha"] is not None


def test_sin_fecha_inicio_el_clima_dice_que_falta_la_fecha():
    sin_fecha = {k: v for k, v in BODY.items() if k != "fecha_inicio"}
    j = cliente_http(clima_caido()).post("/itinerario", json=sin_fecha).json()
    assert j["estado"] == "ok" and "fecha de inicio" in j["dias"][0]["clima"]["motivo_no_disponible"]


def test_fecha_en_el_pasado_se_rechaza_con_422():
    r = cliente_http(clima_caido()).post("/itinerario", json={**BODY, "fecha_inicio": "2020-01-01"})
    assert r.status_code == 422
