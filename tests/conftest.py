import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest


@pytest.fixture(autouse=True)
def sin_rag_real():
    """Las pruebas de la API no cargan el modelo de embeddings ni leen el índice real, salvo que pidan un RAG propio."""
    from src.main import app, obtener_rag
    puesto = obtener_rag not in app.dependency_overrides
    if puesto:
        app.dependency_overrides[obtener_rag] = lambda: None
    yield
    if puesto:
        app.dependency_overrides.pop(obtener_rag, None)


@pytest.fixture(autouse=True)
def sin_limite_de_peticiones():
    """Las pruebas hacen muchas solicitudes desde la misma IP: se usa un límite holgado, salvo en
    tests/test_limites.py, que pone el suyo."""
    from src.limites import LimitadorPorIP
    from src.main import app, obtener_limitadores
    puesto = obtener_limitadores not in app.dependency_overrides
    if puesto:
        holgados = {"itinerario": LimitadorPorIP(10_000, 60), "agente": LimitadorPorIP(10_000, 60)}
        app.dependency_overrides[obtener_limitadores] = lambda: holgados
    yield
    if puesto:
        app.dependency_overrides.pop(obtener_limitadores, None)
