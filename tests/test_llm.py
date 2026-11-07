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


# ---------------------------------------------------------------- agente: herramientas
def respuesta_con_tools(*llamadas):
    tcs = [NS(id=f"c{i}", function=NS(name=n, arguments=a)) for i, (n, a) in enumerate(llamadas)]
    return NS(choices=[NS(message=NS(content=None, tool_calls=tcs), finish_reason="tool_calls")],
              usage=NS(prompt_tokens=10, completion_tokens=5))


class DobleTools(Doble):
    def _create(self, **kw):
        self.llamadas.append(kw)
        paso = self.guion.pop(0)
        if isinstance(paso, Exception):
            raise paso
        return paso


def test_pedir_herramientas_sin_texto_no_es_respuesta_vacia():
    d = DobleTools([respuesta_con_tools(("recalcular", '{"dia": 1}'))])
    r = cliente(d)[0].generar_con_herramientas([{"role": "user", "content": "x"}], [{"type": "function"}])
    assert r.intentos == 1 and r.datos.contenido is None
    assert [(x.id, x.nombre, x.argumentos) for x in r.datos.llamadas] == [("c0", "recalcular", '{"dia": 1}')]
    assert d.llamadas[0]["tools"] == [{"type": "function"}] and d.llamadas[0]["tool_choice"] == "auto"


def test_herramientas_reintenta_y_pasa_al_respaldo():
    a = DobleTools([error_http(openai.RateLimitError, 429)] * 3)
    b = DobleTools([respuesta(None), respuesta_con_tools(("consultar_clima", "{}"))])  # vacía: se reintenta
    r = cliente(a, b)[0].generar_con_herramientas([], [])
    assert r.proveedor == "b" and r.datos.llamadas[0].nombre == "consultar_clima"


def test_mensaje_assistant_con_tool_calls():
    from src.services.llm import LlamadaHerramienta, MensajeModelo
    m = MensajeModelo(None, [LlamadaHerramienta("c1", "recalcular", "{}")]).como_mensaje()
    assert m == {"role": "assistant", "content": "", "tool_calls": [
        {"id": "c1", "type": "function", "function": {"name": "recalcular", "arguments": "{}"}}]}


# ---------------------------------------------------------------- Gemini como respaldo (Semana 4)
from src.config import CATALOGO, ErrorConfiguracion, cargar_config, estado_proveedores  # noqa: E402
from src.services.llm import adaptar_esquema, formato_json, tools_para  # noqa: E402


def groq_y_gemini(a, b, razonamiento="low"):
    cfg = Config(principal=Proveedor("groq", "u", "k", "gpt-oss-20b", True, "estricto"),
                 respaldo=Proveedor("gemini", "u", "k", "gemini-flash", False, "gemini"),
                 timeout_s=5, max_tokens=100, reintentos=2, razonamiento=razonamiento)
    return ClienteLLM(cfg, clientes={"groq": a, "gemini": b}, dormir=lambda s: None)


def test_si_groq_agota_la_cuota_responde_gemini_con_su_dialecto():
    a = Doble([error_http(openai.RateLimitError, 429)] * 2)
    b = Doble([BUENA])
    r = groq_y_gemini(a, b).generar_json("sys", "peticion", ItinerarioModelo)
    assert r.proveedor == "gemini" and r.datos.dias[0].numero == 1
    esquema_groq = a.llamadas[0]["response_format"]["json_schema"]["schema"]
    esquema_gemini = b.llamadas[0]["response_format"]["json_schema"]["schema"]
    assert "$defs" in esquema_groq and "$defs" not in json.dumps(esquema_gemini)


def test_reasoning_effort_solo_a_quien_lo_admite():
    a = Doble([error_http(openai.AuthenticationError, 401)])   # clave mala: pasa directo al respaldo
    b = Doble([BUENA])
    groq_y_gemini(a, b).generar_json("sys", "p", ItinerarioModelo)
    assert a.llamadas[0]["reasoning_effort"] == "low" and "reasoning_effort" not in b.llamadas[0]
    assert len(a.llamadas) == 1                                  # error definitivo: sin reintentos


def test_agente_con_gemini_recibe_las_mismas_herramientas_adaptadas():
    from src.agente import ESQUEMAS
    a = DobleTools([error_http(openai.InternalServerError, 503)] * 2)
    b = DobleTools([respuesta_con_tools(("recalcular", '{"dia": 1}'))])
    r = groq_y_gemini(a, b).generar_con_herramientas([{"role": "user", "content": "x"}], ESQUEMAS)
    assert r.proveedor == "gemini" and r.datos.llamadas[0].nombre == "recalcular"
    enviados = b.llamadas[0]["tools"]
    assert [h["function"]["name"] for h in enviados] == [h["function"]["name"] for h in ESQUEMAS]
    assert "additionalProperties" not in json.dumps(enviados) and a.llamadas[0]["tools"] is ESQUEMAS


def test_los_dos_caidos_da_proveedor_no_disponible():
    a = Doble([error_http(openai.RateLimitError, 429)] * 2)
    b = Doble([error_http(openai.RateLimitError, 429)] * 2)
    with pytest.raises(ProveedorNoDisponible):
        groq_y_gemini(a, b).generar_json("sys", "p", ItinerarioModelo)


def test_adaptar_esquema_gemini_resuelve_referencias_y_nulos():
    e = adaptar_esquema(ItinerarioModelo.model_json_schema(), "gemini")
    texto = json.dumps(e)
    for clave in ("$ref", "$defs", "title", "additionalProperties", "anyOf"):
        assert clave not in texto
    assert e["properties"]["motivo_rechazo"] == {
        "type": "string", "nullable": True, "description": ItinerarioModelo.model_fields["motivo_rechazo"].description}
    atractivo = e["properties"]["dias"]["items"]["properties"]["atractivos"]["items"]
    assert set(atractivo["required"]) == {"id", "motivo"}
    assert adaptar_esquema({"a": 1}, "estricto") == {"a": 1}
    with pytest.raises(ValueError):
        adaptar_esquema({}, "otro")


def test_formato_y_tools_sin_cambios_para_groq():
    assert formato_json(ItinerarioModelo, "estricto")["response_format"]["json_schema"]["schema"] == \
        ItinerarioModelo.model_json_schema()
    h = [{"type": "function", "function": {"name": "x", "parameters": {"title": "T", "type": "object"}}}]
    assert tools_para(h, "estricto") is h and tools_para(h, "gemini")[0]["function"]["parameters"] == {"type": "object"}


def test_config_gemini_como_respaldo(monkeypatch):
    monkeypatch.setenv("LLM_PRINCIPAL", "groq")
    monkeypatch.setenv("GROQ_API_KEY", "gsk-prueba")
    monkeypatch.setenv("LLM_RESPALDO", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "")
    with pytest.raises(ErrorConfiguracion, match="GEMINI_API_KEY"):
        cargar_config()                                          # sin clave: se detiene al arrancar
    monkeypatch.setenv("GEMINI_API_KEY", "clave-de-prueba")
    monkeypatch.setenv("GEMINI_MODEL", "")
    c = cargar_config()
    assert c.respaldo.nombre == "gemini" and c.respaldo.modelo == CATALOGO["gemini"]["modelo"]
    assert c.respaldo.base_url.startswith("https://generativelanguage.googleapis.com")
    assert not c.respaldo.admite_razonamiento and c.respaldo.esquema == "gemini"


def test_estado_proveedores_nunca_muestra_la_clave(monkeypatch):
    monkeypatch.setenv("LLM_PRINCIPAL", "groq")
    monkeypatch.setenv("GROQ_API_KEY", "valor-ficticio")
    monkeypatch.setenv("LLM_RESPALDO", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "")
    e = estado_proveedores()
    assert e["principal"]["configurado"] and not e["respaldo"]["configurado"]
    assert "valor-ficticio" not in json.dumps(e)
    monkeypatch.setenv("LLM_RESPALDO", "")
    assert estado_proveedores()["respaldo"] is None
