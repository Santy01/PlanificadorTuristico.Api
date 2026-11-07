"""Las revisiones de eval/evaluar.py: si una revisión está mal, los números de la evaluación no valen nada."""
from eval.evaluar import itinerario_base, leer, revisar_agente, revisar_pregunta, revisar_solicitud
from src.catalogo import cargar_catalogo
from src.schemas import (
    AtractivoElegido, Cita, Confirmacion, DiaModelo, ItinerarioModelo, RespuestaAgente, RespuestaItinerario,
    SolicitudItinerario,
)
from src.services.itinerario import armar_itinerario
from src.tools.buscar_fragmentos import BuscarFragmentosOut, Fragmento

CAT = cargar_catalogo()


def frag(atractivo_id):
    return Fragmento(id="f", atractivo_id=atractivo_id, atractivo="x", texto="t", fuente="F", url="", tipo_fuente="o",
                     estado_verificacion="B")


def test_pregunta_con_fuente_y_silencio():
    assert revisar_pregunta(BuscarFragmentosOut(fragmentos=[frag("a"), frag("b")]), ["b"]) == []
    assert revisar_pregunta(BuscarFragmentosOut(fragmentos=[frag("a")]), ["b"])
    assert revisar_pregunta(BuscarFragmentosOut(fragmentos=[]), None) == []
    assert revisar_pregunta(BuscarFragmentosOut(fragmentos=[frag("a")]), None)


def itinerario(*dias, presupuesto=100, intereses=("natural",)):
    s = SolicitudItinerario(dias=len(dias), presupuesto_usd=presupuesto, punto_partida="Ambato", intereses=list(intereses))
    prop = ItinerarioModelo(fuera_de_alcance=False, motivo_rechazo=None, supuestos=[], dias=[
        DiaModelo(numero=i + 1, atractivos=[AtractivoElegido(id=x, motivo="m") for x in ids]) for i, ids in enumerate(dias)])
    return armar_itinerario(prop, s, CAT), s


def test_solicitud_que_cumple():
    r, s = itinerario(["laguna-de-quilotoa"], ["parque-nacional-cotopaxi"])
    espera = {"estado": "ok", "incluye_provincia": "Cotopaxi", "incluye": ["laguna-de-quilotoa"], "fraccion_tipo": 0.6}
    assert revisar_solicitud(r, s, espera, CAT) == []


def test_solicitud_detecta_cada_falla():
    r, s = itinerario(["hornado-de-riobamba"], [], presupuesto=0, intereses=("natural",))
    r.presupuesto_excedido = True
    espera = {"estado": "ok", "incluye_provincia": "Cotopaxi", "incluye": ["laguna-de-quilotoa"], "min_actividades": 2,
              "dentro_presupuesto": True, "fraccion_tipo": 0.6, "min_citas": 1}
    fallas = " | ".join(revisar_solicitud(r, s, espera, CAT))
    for texto in ("ninguna actividad en Cotopaxi", "no incluye", "mínimo 2", "excede el presupuesto", "tipo pedido",
                  "cita(s)"):
        assert texto in fallas


def test_solicitud_estado_distinto_no_sigue_revisando():
    r = RespuestaItinerario(estado="rechazado", mensaje="m")
    s = SolicitudItinerario(dias=1, presupuesto_usd=1, punto_partida="Ambato", intereses=["natural"])
    assert revisar_solicitud(r, s, {"estado": "rechazado"}, CAT) == []
    assert revisar_solicitud(r, s, {"estado": "ok", "incluye": ["x"]}, CAT) == ["estado rechazado (esperaba ok)"]


def respuesta_agente(**kw):
    base, _ = itinerario_base(CAT)
    return RespuestaAgente(**{"estado": "respondido", "respuesta": "r", "itinerario": base, "vueltas": 1, **kw})


def test_agente_que_cumple_y_que_no():
    espera = {"estado": "respondido", "usa": ["recalcular"], "min_cambios": 1, "sale": "termas-de-la-virgen"}
    assert revisar_agente(respuesta_agente(), ["recalcular"], espera) == ["0 cambio(s)",
                                                                          "termas-de-la-virgen sigue en el itinerario"]
    assert "no usó" in revisar_agente(respuesta_agente(), [], {"estado": "respondido", "usa": ["recalcular"]})[0]


def test_agente_confirmacion_y_fuentes():
    conf = Confirmacion(id="1", accion="enviar_itinerario", argumentos={"correo": "a@b.com"}, descripcion="d",
                        expira_en_s=60)
    r = respuesta_agente(estado="requiere_confirmacion", respuesta=None, confirmacion=conf)
    assert revisar_agente(r, [], {"estado": "requiere_confirmacion", "accion": "enviar_itinerario",
                                  "correo": "a@b.com"}) == []
    assert "no es el que escribió" in revisar_agente(r, [], {"estado": "requiere_confirmacion", "correo": "x@y.com"})[0]
    assert "pidió confirmar" in revisar_agente(r, [], {"estado": "requiere_confirmacion", "sin_confirmacion": True})[0]
    cita = Cita(fragmento_id="f", texto="t", fuente="F", url="", tipo_fuente="o", estado_verificacion="B")
    assert revisar_agente(respuesta_agente(fuentes=[cita]), [], {"estado": "respondido", "max_fuentes": 0})


def test_los_casos_de_evaluacion_son_validos():
    """Los .jsonl se pueden leer y cada solicitud pasa la validación de la API (si no, el caso no mide nada)."""
    sols = leer("solicitudes.jsonl")
    assert len(sols) == 15 and len({c["id"] for c in sols}) == 15
    for c in sols:
        SolicitudItinerario(**c["solicitud"])
    pregs = leer("preguntas.jsonl")
    assert len(pregs) == 15 and sum(p["fuente_esperada"] is None for p in pregs) == 4
    assert all(i in CAT for p in pregs for i in (p["fuente_esperada"] or []))
    casos = leer("agente_casos.jsonl")
    assert {c["escenario"] for c in casos} == {"A", "B", "D"}
    assert all(c["espera"]["estado"] in ("respondido", "requiere_confirmacion") for c in casos)
