"""Validación de los datos del catálogo y de su importación.

El 7 de noviembre de 2026 el catálogo se editó en Excel y volvió dos veces con daño de formato: separador «;»,
codificación de DOS, coordenadas sin punto (-1.3982 → -14047 o -13.982) y textos cortados en cada «;». La API no habría
arrancado, o el mapa habría puesto marcadores en lugares imposibles. Estas pruebas hacen que el CI lo detecte.
"""
import csv

import pytest

from scripts.importar_catalogo import combinar, en_la_zona, leer_filas, rearmar_coordenada
from src.catalogo import RUTA_CATALOGO, RUTA_REDUCIDA, cargar_catalogo

PROVINCIAS = {"Tungurahua", "Chimborazo", "Cotopaxi", "Bolívar"}
TIPOS = {"natural", "cultural", "gastronómico"}
ESTADOS = {"A", "A_parcial", "B", "C"}
PRECISIONES = {"verificada_fuente", "sitio_aprox", "localidad_aprox", "POR VERIFICAR"}


@pytest.mark.parametrize("ruta", [RUTA_CATALOGO, RUTA_REDUCIDA], ids=["completo", "reducido"])
def test_formato_del_archivo(ruta):
    crudo = ruta.read_bytes()
    texto = crudo.decode("utf-8-sig")                      # falla si quedó en la codificación de DOS
    encabezado = texto.splitlines()[0]
    assert encabezado.count(",") == 13 and ";" not in encabezado, "el separador debe ser la coma"
    for i, fila in enumerate(csv.reader(texto.splitlines()[1:]), start=2):
        assert len(fila) == 14, f"{ruta.name}, línea {i}: {len(fila)} columnas (deben ser 14)"


@pytest.mark.parametrize("ruta", [RUTA_CATALOGO, RUTA_REDUCIDA], ids=["completo", "reducido"])
def test_valores_validos(ruta):
    for a in cargar_catalogo(ruta).values():
        assert a.provincia in PROVINCIAS, a.id
        assert a.tipo in TIPOS, a.id
        assert a.estado_verificacion in ESTADOS, a.id
        assert (a.latitud is None) == (a.longitud is None), a.id
        if a.latitud is not None:
            assert en_la_zona(a.latitud, a.longitud), f"{a.id}: ({a.latitud}, {a.longitud}) fuera de la zona centro"
        if a.duracion_h is not None:
            assert 0 < a.duracion_h <= 12, a.id
        if a.costo_usd is not None:
            assert 0 <= a.costo_usd <= 200, a.id


def test_el_reducido_es_el_conjunto_verificado():
    """Las 60 filas del reducido son las mismas del completo (el agente y el RAG ven los mismos datos que el modelo)
    y están completas: ni costos ni duraciones por verificar."""
    completo, reducido = cargar_catalogo(), cargar_catalogo(RUTA_REDUCIDA)
    assert len(reducido) == 60
    for k, a in reducido.items():
        assert completo[k] == a, f"{k}: el reducido y el completo no coinciden"
        assert a.costo_usd is not None and a.duracion_h is not None and a.latitud is not None, k


# ---------------------------------------------------------------- reglas de la importación
@pytest.mark.parametrize("valor, enteros, esperado", [
    ("-13.982", 1, -1.3982), ("-14047", 1, -1.4047), ("-1.3982", 1, -1.3982), ("-0.8500", 1, -0.85),
    ("-784.186", 2, -78.4186), ("-782958", 2, -78.2958), ("-78.4186", 2, -78.4186),
    ("POR VERIFICAR", 1, None), ("", 1, None), ("abc", 2, None),
])
def test_rearmar_coordenada(valor, enteros, esperado):
    r = rearmar_coordenada(valor, enteros)
    assert r == esperado if esperado is None else abs(r - esperado) < 1e-9


COLUMNAS = ["nombre", "canton", "costo_estimado", "latitud", "longitud", "estado_verificacion", "notas"]
ANTERIOR = {"nombre": "X", "canton": "Baños", "costo_estimado": "POR VERIFICAR", "latitud": "-1.3982",
            "longitud": "-78.4186", "estado_verificacion": "B", "notas": "Tarifa USD 4.00; Fase II USD 6.00"}


def test_combinar_aplica_lo_verificado_y_no_el_dano():
    nueva = {**ANTERIOR, "costo_estimado": "4.00-6.00", "latitud": "-13.982", "longitud": "-784.186",
             "notas": "Tarifa USD 4.00", "estado_verificacion": ""}
    fila, notas = combinar(nueva, ANTERIOR, COLUMNAS)
    assert fila["costo_estimado"] == "4.00-6.00"                          # dato verificado nuevo
    assert (fila["latitud"], fila["longitud"]) == ("-1.3982", "-78.4186")  # mismas coordenadas, rearmadas
    assert fila["notas"] == ANTERIOR["notas"]                               # cortada en «;»: se conserva entera
    assert fila["estado_verificacion"] == "B"                               # vacío no borra
    assert any("vacío" in n for n in notas)


def test_combinar_rechaza_coordenadas_lejanas_o_fuera_de_la_zona():
    _, notas = combinar({**ANTERIOR, "latitud": "-2.5000", "longitud": "-78.4186"}, ANTERIOR, COLUMNAS)
    assert any("se alejan" in n for n in notas)
    fila, notas = combinar({**ANTERIOR, "latitud": "-0.1000", "longitud": "-78.4186"}, ANTERIOR, COLUMNAS)
    assert fila["latitud"] == "-1.3982" and any("fuera de la zona" in n for n in notas)


def test_leer_filas_detecta_el_separador():
    filas, sep = leer_filas("nombre;canton\nA;B\n")
    assert sep == ";" and filas == [{"nombre": "A", "canton": "B"}]
