"""Prueba de punta a punta contra el proveedor simulado (HTTP real, sin internet)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import servidor_simulado  # noqa: E402

from src.config import Config, _proveedor  # noqa: E402
from src.schemas import ItinerarioModelo  # noqa: E402
from src.services.llm import ClienteLLM  # noqa: E402


def test_json_por_http_con_429_real():
    srv = servidor_simulado.iniciar(puerto=8099, limite=1, ventana=1)
    try:
        cfg = Config(principal=_proveedor("simulado"), respaldo=None, timeout_s=5, max_tokens=100, reintentos=4, razonamiento=None)
        llm = ClienteLLM(cfg)
        a = llm.generar_json("sys", "plan de 2 días", ItinerarioModelo)
        b = llm.generar_json("sys", "plan de 2 días", ItinerarioModelo)   # choca con el límite → espera y reintenta
        assert isinstance(a.datos, ItinerarioModelo) and b.intentos >= 2
    finally:
        srv.shutdown()
        srv.server_close()
