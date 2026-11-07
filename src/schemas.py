"""Esquemas (Pydantic) de lo que ENTRA al sistema, de lo que el MODELO debe devolver
y de lo que SALE hacia el cliente.

Reglas para que el esquema funcione con el modo estricto de Groq:
  - extra="forbid" en cada modelo del modelo (no se aceptan campos inventados).
  - Todos los campos son obligatorios; si algo puede faltar, use `tipo | None`.
  - Nada de límites raros en el esquema (minLength, pattern…): esas reglas van en
    validadores de Python. El esquema GUÍA al modelo; la validación la hace el código.
"""
from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Estricto(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------- ENTRADA (HU-01)
class SolicitudItinerario(BaseModel):
    """Lo que envía el visitante. Los límites de tamaño defienden contra consumo excesivo (OWASP LLM10)."""
    dias: int = Field(ge=1, le=7, description="Número de días del viaje (1 a 7)")
    presupuesto_usd: float = Field(ge=0, le=100_000, description="Presupuesto total en dólares")
    punto_partida: str = Field(min_length=2, max_length=100, description="Ciudad o lugar de partida")
    intereses: list[str] = Field(min_length=1, max_length=5, description="Ej.: natural, cultural, gastronómico")
    notas: str | None = Field(default=None, max_length=500, description="Comentarios libres del visitante")
    fecha_inicio: date | None = Field(default=None, description="Primer día del viaje (AAAA-MM-DD); necesaria para el pronóstico")

    @field_validator("fecha_inicio")
    @classmethod
    def no_en_el_pasado(cls, v: date | None) -> date | None:
        if v is not None and v < date.today():
            raise ValueError("la fecha de inicio no puede estar en el pasado")
        return v


# ---------------------------------------------------------------- SALIDA DEL MODELO
class AtractivoElegido(Estricto):
    id: str = Field(description="id EXACTO de un atractivo del catálogo recibido")
    motivo: str = Field(description="Por qué encaja con los intereses del visitante, en una oración")


class DiaModelo(Estricto):
    numero: int
    atractivos: list[AtractivoElegido] = Field(description="En el orden de visita")


class ItinerarioModelo(Estricto):
    """Lo que el MODELO debe devolver: solo ids y motivos; los datos los pone el código."""
    fuera_de_alcance: bool = Field(description="true si pide reservar, pagar, consejo médico/seguridad o algo ajeno al turismo")
    motivo_rechazo: str | None = Field(description="Explicación breve si fuera_de_alcance es true; si no, null")
    dias: list[DiaModelo]
    supuestos: list[str] = Field(description="Lo que se asumió y el visitante debe confirmar")


class AtractivoCitado(AtractivoElegido):
    citas: list[str] = Field(description="Ids de los fragmentos (p. ej. «f2») que respaldan el motivo; [] si ninguno aplica")


class DiaConCitas(Estricto):
    numero: int
    atractivos: list[AtractivoCitado] = Field(description="En el orden de visita")


class ItinerarioConCitas(ItinerarioModelo):
    """Igual que ItinerarioModelo, pero cada atractivo puede citar fragmentos del RAG. Es un esquema aparte porque
    el modo estricto exige todos los campos: así el flujo sin RAG sigue pidiendo exactamente lo mismo que antes."""
    dias: list[DiaConCitas]


# ---------------------------------------------------------------- SALIDA AL CLIENTE
class Cita(BaseModel):
    """Fragmento de una fuente que respalda una actividad. Lo arma el CÓDIGO con el fragmento recuperado:
    el modelo solo elige el id, nunca escribe el texto, la fuente ni la URL."""
    fragmento_id: str
    texto: str
    fuente: str
    url: str
    tipo_fuente: str  # oficial (GAD), prensa, no oficial…
    estado_verificacion: str


class Actividad(BaseModel):
    orden: int
    atractivo_id: str
    nombre: str
    canton: str | None
    provincia: str
    tipo: str
    motivo: str
    duracion_h: float
    duracion_verificada: bool
    costo_usd: float | None  # None = POR VERIFICAR; con rangos, el valor más alto
    costo_aproximado: bool  # rango, «desde» o inferido
    costo_texto: str | None  # texto original del catálogo (p. ej. «2.00-2.50»)
    fuente: str
    url_fuente: list[str]
    estado_verificacion: str  # A, A_parcial, B o C (C = sin fuente)
    precision_coord: str | None  # None = sin coordenadas
    nota: str | None
    latitud: float | None  # None = sin marcador en el mapa (HU-03)
    longitud: float | None
    citas: list[Cita] = []  # fragmentos del RAG que respaldan el motivo (puede venir vacía)


class Clima(BaseModel):
    """Pronóstico del día. `disponible=False` NO es un error: el itinerario sigue siendo válido."""
    disponible: bool
    motivo_no_disponible: str | None = None
    fecha: date | None = None
    lugar_referencia: str | None = None  # atractivo cuyas coordenadas se usaron
    resumen: str | None = None
    temp_min_c: float | None = None
    temp_max_c: float | None = None
    prob_lluvia_pct: float | None = None
    precipitacion_mm: float | None = None
    lluvia_intensa: bool = False
    fuente: str | None = None


class Alternativa(BaseModel):
    """Atractivo del catálogo sugerido cuando se pronostica lluvia intensa (HU-06)."""
    atractivo_id: str
    nombre: str
    canton: str | None
    provincia: str
    tipo: str
    estado_verificacion: str
    motivo: str


class DiaItinerario(BaseModel):
    numero: int
    fecha: date | None = None
    actividades: list[Actividad]
    horas_total: float
    costo_parcial_usd: float
    clima: Clima | None = None
    alternativas: list[Alternativa] = []


class RespuestaItinerario(BaseModel):
    estado: Literal["ok", "rechazado", "revision_humana"]
    mensaje: str
    dias: list[DiaItinerario] = []
    costo_total_usd: float | None = None
    costo_parcial: bool = False  # true si hubo costos POR VERIFICAR excluidos del total
    presupuesto_excedido: bool = False
    supuestos: list[str] = []
    advertencias: list[str] = []
    proveedor: str | None = None


# ---------------------------------------------------------------- AGENTE (HU-08)
MAX_ACTIVIDADES_POR_DIA = 15


class MensajeChat(BaseModel):
    """Un turno previo de la conversación (solo texto: lo que se reenvía al modelo como historial)."""
    rol: Literal["visitante", "asistente"]
    texto: str = Field(min_length=1, max_length=1000)


class SolicitudAgente(BaseModel):
    """Lo que envía la interfaz para conversar sobre un itinerario ya generado. La API no guarda la conversación:
    el cliente reenvía el itinerario actual y, si quiere, los turnos anteriores."""
    mensaje: str = Field(min_length=1, max_length=500, description="Lo que escribe el visitante")
    itinerario: RespuestaItinerario = Field(description="El itinerario actual (tal como lo devolvió la API)")
    solicitud: SolicitudItinerario | None = Field(
        default=None, description="Los parámetros originales: el presupuesto se usa al recalcular costos")
    historial: list[MensajeChat] = Field(default_factory=list, max_length=20)

    @field_validator("itinerario")
    @classmethod
    def tamano_razonable(cls, v: RespuestaItinerario) -> RespuestaItinerario:
        # Límites de tamaño (OWASP LLM10): el itinerario viaja al prompt en cada vuelta.
        if len(v.dias) > 7 or any(len(d.actividades) > MAX_ACTIVIDADES_POR_DIA for d in v.dias):
            raise ValueError(f"máximo 7 días y {MAX_ACTIVIDADES_POR_DIA} actividades por día")
        return v


class DecisionAgente(BaseModel):
    aprobar: bool


class Confirmacion(BaseModel):
    """Acción detenida a la espera del visitante. `argumentos` son los REALES que se ejecutarán al aprobar."""
    id: str
    accion: str
    argumentos: dict
    descripcion: str
    expira_en_s: int


class RespuestaAgente(BaseModel):
    estado: Literal["respondido", "requiere_confirmacion", "tope_alcanzado"]
    respuesta: str | None
    itinerario: RespuestaItinerario  # el actual, con los cambios aplicados en esta solicitud
    cambios: list[str] = []          # lo que hizo `recalcular` (para resaltarlo en la interfaz)
    fuentes: list[Cita] = []         # fragmentos que devolvió buscar_fragmentos (armados por el código)
    confirmacion: Confirmacion | None = None
    advertencias: list[str] = []     # p. ej. datos de la respuesta que el código no encontró en ninguna fuente
    vueltas: int
