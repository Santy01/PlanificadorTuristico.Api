"""Límite de peticiones por IP (LLM10) y /health avanzado."""
import json

from fastapi.testclient import TestClient

from src.limites import LimitadorPorIP, ip_cliente
from src.main import app, obtener_limitadores, obtener_llm, obtener_rag
from src.services.llm import ProveedorNoDisponible

SOLICITUD = {"dias": 1, "presupuesto_usd": 50, "punto_partida": "Ambato", "intereses": ["natural"]}


def test_ventana_deslizante():
    reloj = [0.0]
    lim = LimitadorPorIP(2, 60, reloj=lambda: reloj[0])
    assert lim.permitir("a") == (True, 0) and lim.permitir("a") == (True, 0)
    permitido, espera = lim.permitir("a")
    assert not permitido and espera == 60
    assert lim.permitir("b")[0]                                   # otra IP tiene su propio cupo
    reloj[0] = 30
    assert lim.permitir("a") == (False, 30)                       # el rechazo no consume cupo
    reloj[0] = 60.5
    assert lim.permitir("a")[0]                                   # la primera marca ya salió de la ventana


def test_ip_real_detras_de_traefik():
    assert ip_cliente("203.0.113.7", "172.18.0.2", 1) == "203.0.113.7"
    # el cliente escribe una IP falsa delante; Traefik agrega la real al final
    assert ip_cliente("1.2.3.4, 203.0.113.7", "172.18.0.2", 1) == "203.0.113.7"
    assert ip_cliente(None, "172.18.0.2", 1) == "172.18.0.2"
    assert ip_cliente("1.2.3.4", "10.0.0.1", 0) == "10.0.0.1"     # sin proxy de confianza no se cree la cabecera
    assert ip_cliente(None, None, 1) == "desconocida"


class LLMCaido:
    def generar_json(self, *a, **k):
        raise ProveedorNoDisponible()


def cliente_con_limite(maximo):
    lim = {"itinerario": LimitadorPorIP(maximo, 60), "agente": LimitadorPorIP(maximo, 60)}
    app.dependency_overrides.update({obtener_limitadores: lambda: lim, obtener_llm: lambda: LLMCaido(),
                                     obtener_rag: lambda: None})
    return TestClient(app)


def test_endpoint_responde_429_con_retry_after():
    try:
        c = cliente_con_limite(2)
        h = {"X-Forwarded-For": "198.51.100.9"}
        assert [c.post("/itinerario", json=SOLICITUD, headers=h).status_code for _ in range(2)] == [503, 503]
        r = c.post("/itinerario", json=SOLICITUD, headers=h)
        assert r.status_code == 429 and int(r.headers["retry-after"]) > 0
        assert "Demasiadas solicitudes" in r.json()["detail"]
        assert c.post("/itinerario/stream", json=SOLICITUD, headers=h).status_code == 429   # comparten contador
        assert c.post("/itinerario", json=SOLICITUD, headers={"X-Forwarded-For": "198.51.100.10"}).status_code == 503
        assert c.get("/health", headers=h).status_code == 200                                # la salud no se limita
    finally:
        for dep in (obtener_limitadores, obtener_llm):
            app.dependency_overrides.pop(dep, None)


def test_health_avanzado_sin_claves(monkeypatch):
    monkeypatch.setenv("LLM_PRINCIPAL", "groq")
    monkeypatch.setenv("GROQ_API_KEY", "gsk-no-debe-aparecer")
    monkeypatch.setenv("LLM_RESPALDO", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "")

    class RAG:
        def fragmentos_indexados(self):
            return 241
    app.dependency_overrides[obtener_rag] = lambda: RAG()
    try:
        r = TestClient(app).get("/health")
    finally:
        app.dependency_overrides[obtener_rag] = lambda: None
    datos = r.json()
    assert r.status_code == 200 and datos["status"] == "ok" and datos["version"] == app.version
    assert datos["rag"] == {"activo": True, "fragmentos": 241}
    assert datos["modelo"]["principal"]["configurado"] and not datos["modelo"]["respaldo"]["configurado"]
    assert "gsk-no-debe-aparecer" not in json.dumps(datos)
