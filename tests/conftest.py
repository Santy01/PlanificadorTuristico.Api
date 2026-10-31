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
