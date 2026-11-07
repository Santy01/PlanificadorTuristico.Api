"""config/parametros.yaml: se lee, se valida y un valor malo detiene la aplicación con un mensaje claro."""
import pytest

from src.parametros import ErrorParametros, cargar_parametros, parametros
from src.services import itinerario


def test_el_archivo_del_repositorio_es_valido_y_lo_usa_el_itinerario():
    p = cargar_parametros()
    assert p.itinerario.jornada_max_h == itinerario.JORNADA_MAX_H
    assert p.itinerario.duracion_por_defecto_h == itinerario.DURACION_POR_DEFECTO_H
    assert p.recalcular.holgura_h >= 0
    assert parametros() == p


def escribir(tmp_path, texto):
    f = tmp_path / "parametros.yaml"
    f.write_text(texto, encoding="utf-8")
    return f


def test_valores_desde_el_archivo(tmp_path):
    f = escribir(tmp_path, "itinerario: {jornada_max_h: 6, duracion_por_defecto_h: 1.5}\nrecalcular: {holgura_h: 0}\n")
    p = cargar_parametros(f)
    assert p.itinerario.jornada_max_h == 6 and p.recalcular.holgura_h == 0


@pytest.mark.parametrize("texto", [
    "itinerario: {jornada_max_h: -1, duracion_por_defecto_h: 2}\nrecalcular: {holgura_h: 0.5}\n",   # fuera de rango
    "itinerario: {jornada_max_h: 8, duracion_por_defecto_h: 2, extra: 1}\nrecalcular: {holgura_h: 0.5}\n",  # de más
    "itinerario: {jornada_max_h: 8}\nrecalcular: {holgura_h: 0.5}\n",                                  # falta uno
    "itinerario: [esto no es\n",                                                                       # YAML roto
])
def test_archivo_invalido_detiene_con_mensaje_claro(tmp_path, texto):
    with pytest.raises(ErrorParametros, match="no es válido"):
        cargar_parametros(escribir(tmp_path, texto))


def test_archivo_inexistente(tmp_path):
    with pytest.raises(ErrorParametros, match="No existe"):
        cargar_parametros(tmp_path / "no-esta.yaml")
