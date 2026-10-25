"""Pruebas del servicio de IA con un DOBLE del modelo: no gastan API y corren en un segundo.

    pytest -q
"""
import json
from types import SimpleNamespace as NS

import httpx
import openai
import pytest

from src.config import Config, Proveedor
from src.schemas import ItinerarioModelo
from src.services.llm import ClienteLLM, ProveedorNoDisponible, SalidaInvalida

BUENA = json.dumps({"fuera_de_alcance": False, "motivo_rechazo": None, "supuestos": [],
                    "dias": [{"numero": 1, "atractivos": [{"id": "laguna-de-quilotoa", "motivo": "Natural."}]}]})


def respuesta(texto):
    return NS(choices=[NS(message=NS(content=texto), finish_reason="stop")], usage=NS(prompt_tokens=10, completion_tokens=5))


def error_http(clase, codigo, cabeceras=None):
    req = httpx.Request("POST", "https://proveedor.test/v1/chat/completions")
    return clase("simulado", response=httpx.Response(codigo, headers=cabeceras or {}, request=req), body=None)


class Doble:
    """Imita a client.chat.completions.create: devuelve (o lanza) lo que le digamos, en orden."""

    def __init__(self, guion):
        self.guion, self.llamadas = list(guion), []
        self.chat = NS(completions=NS(create=self._create))

    def _create(self, **kw):
        self.llamadas.append(kw)
        paso = self.guion.pop(0)
        if isinstance(paso, Exception):
            raise paso
        return respuesta(paso)


def cliente(principal, respaldo=None, reintentos=3):
    cfg = Config(principal=Proveedor("a", "u", "k", "modelo-a"),
                 respaldo=Proveedor("b", "u", "k", "modelo-b") if respaldo is not None else None,
                 timeout_s=5, max_tokens=100, reintentos=reintentos, razonamiento=None)
    esperas = []
    c = ClienteLLM(cfg, clientes={"a": principal, **({"b": respaldo} if respaldo else {})}, dormir=esperas.append)
    return c, esperas


def test_json_valido():
    c, _ = cliente(Doble([BUENA]))
    r = c.generar_json("sys", "peticion", ItinerarioModelo)
    assert r.datos.dias[0].numero == 1 and r.proveedor == "a" and r.intentos == 1


def test_pide_el_esquema_al_proveedor():
    d = Doble([BUENA])
    cliente(d)[0].generar_json("sys", "peticion", ItinerarioModelo)
    rf = d.llamadas[0]["response_format"]
    assert rf["type"] == "json_schema" and rf["json_schema"]["strict"] is True


def test_json_invalido_se_corrige_una_vez():
    d = Doble(['{"dias": "x"}', BUENA])
    r = cliente(d)[0].generar_json("sys", "peticion", ItinerarioModelo)
    assert r.datos.fuera_de_alcance is False
    assert "no cumple el esquema" in d.llamadas[1]["messages"][-1]["content"]


def test_json_invalido_dos_veces_va_a_revision_humana():
    c, _ = cliente(Doble(["no es json", "tampoco"]))
    with pytest.raises(SalidaInvalida):
        c.generar_json("sys", "peticion", ItinerarioModelo)


def test_429_respeta_retry_after_y_reintenta():
    c, esperas = cliente(Doble([error_http(openai.RateLimitError, 429, {"retry-after": "2"}), BUENA]))
    r = c.generar_json("sys", "peticion", ItinerarioModelo)
    assert 2.0 <= esperas[0] <= 2.5 and r.intentos == 2  # lo pedido + un poco de azar


def test_espera_exponencial_sin_retry_after():
    c, esperas = cliente(Doble([error_http(openai.InternalServerError, 503), error_http(openai.InternalServerError, 503), BUENA]))
    c.generar_json("sys", "peticion", ItinerarioModelo)
    assert 0.5 <= esperas[0] <= 1 and 1 <= esperas[1] <= 2  # 1 s y 2 s, con azar


def test_respuesta_vacia_se_reintenta():
    c, _ = cliente(Doble(["", BUENA]))
    assert c.generar_json("sys", "peticion", ItinerarioModelo).intentos == 2


def test_principal_caido_pasa_al_respaldo():
    tiempo = openai.APITimeoutError(request=httpx.Request("POST", "https://x"))
    c, _ = cliente(Doble([tiempo, tiempo, tiempo]), Doble([BUENA]))
    assert c.generar_json("sys", "peticion", ItinerarioModelo).proveedor == "b"


def test_clave_invalida_no_se_reintenta():
    principal = Doble([error_http(openai.AuthenticationError, 401)])
    c, esperas = cliente(principal, Doble([BUENA]))
    assert c.generar_json("sys", "peticion", ItinerarioModelo).proveedor == "b"
    assert len(principal.llamadas) == 1 and esperas == []


def test_todos_caidos_da_error_claro():
    caida = lambda: error_http(openai.RateLimitError, 429, {"retry-after": "1"})  # noqa: E731
    c, _ = cliente(Doble([caida() for _ in range(3)]), Doble([caida() for _ in range(3)]))
    with pytest.raises(ProveedorNoDisponible) as e:
        c.generar_json("sys", "peticion", ItinerarioModelo)
    assert "no está disponible" in e.value.mensaje_usuario


def test_retry_after_muy_largo_va_directo_al_respaldo():
    c, esperas = cliente(Doble([error_http(openai.RateLimitError, 429, {"retry-after": "3600"})]), Doble([BUENA]))
    assert c.generar_json("sys", "peticion", ItinerarioModelo).proveedor == "b" and esperas == []


# ---------------------------------------------------------------- JSON roto del modelo (Groq: failed_generation)
def generacion_fallida():
    req = httpx.Request("POST", "https://proveedor.test/v1/chat/completions")
    return openai.BadRequestError("json_validate_failed", response=httpx.Response(400, request=req),
                                  body={"code": "json_validate_failed", "failed_generation": "{rota"})


def test_400_json_validate_failed_se_reintenta_y_se_recupera():
    c, esperas = cliente(Doble([generacion_fallida(), BUENA]))
    r = c.generar_json("sys", "peticion", ItinerarioModelo)
    assert r.intentos == 2 and r.datos.fuera_de_alcance is False and len(esperas) == 1


def test_400_de_solicitud_mal_formada_sigue_siendo_definitivo():
    principal = Doble([error_http(openai.BadRequestError, 400)])
    c, esperas = cliente(principal, Doble([BUENA]))
    assert c.generar_json("sys", "peticion", ItinerarioModelo).proveedor == "b" and len(principal.llamadas) == 1


class FlujoQueSeCorta:
    """Cliente cuyo stream falla A MITAD con openai.APIError (la clase base), como hizo Groq."""

    def __init__(self, trozos_antes=0, normal=BUENA):
        self.normal, self.trozos_antes = normal, trozos_antes
        self.chat = NS(completions=NS(create=self._create))

    def _create(self, **kw):
        if not kw.get("stream"):
            return respuesta(self.normal)

        def flujo():
            for _ in range(self.trozos_antes):
                yield NS(choices=[NS(delta=NS(content="{"))])
            raise openai.APIError("Generated JSON does not match the expected schema (failed_generation)",
                                  request=httpx.Request("POST", "https://x"), body={"failed_generation": "{}"})
        return flujo()


def test_stream_cortado_por_apierror_no_revienta_se_convierte_en_proveedor_no_disponible():
    c, _ = cliente(FlujoQueSeCorta())
    with pytest.raises(ProveedorNoDisponible):
        list(c.generar_stream("sys", [{"role": "user", "content": "x"}], ItinerarioModelo))


def test_itinerario_en_stream_se_recupera_por_la_via_normal_cuando_el_flujo_falla():
    from src.catalogo import cargar_catalogo
    from src.schemas import SolicitudItinerario
    from src.services.itinerario import stream_itinerario
    s = SolicitudItinerario(dias=1, presupuesto_usd=50, punto_partida="Ambato", intereses=["natural"])
    for antes in (0, 2):   # falla antes del primer trozo y con texto ya enviado
        c, _ = cliente(FlujoQueSeCorta(trozos_antes=antes))
        eventos = list(stream_itinerario(c, s, cargar_catalogo()))
        assert eventos[-1][0] == "itinerario" and eventos[-1][1].estado == "ok", eventos


def test_stream_con_error_inesperado_emite_evento_error_y_no_excepcion():
    from src.catalogo import cargar_catalogo
    from src.schemas import SolicitudItinerario
    from src.services.itinerario import stream_itinerario

    class Roto:
        def generar_stream(self, *a, **k):
            raise RuntimeError("bug inesperado")
            yield
    s = SolicitudItinerario(dias=1, presupuesto_usd=50, punto_partida="Ambato", intereses=["natural"])
    ev = list(stream_itinerario(Roto(), s, cargar_catalogo()))
    assert ev[-1][0] == "error" and "Ocurrió un problema" in ev[-1][1]


def test_sin_respaldo_espera_mas_antes_de_rendirse():
    c, esperas = cliente(Doble([error_http(openai.RateLimitError, 429, {"retry-after": "30"}), BUENA]))
    assert c.generar_json("sys", "peticion", ItinerarioModelo).intentos == 2 and 30 <= esperas[0] <= 30.5
