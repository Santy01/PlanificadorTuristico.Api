# Propuesta: Planificador Turístico Inteligente de la Zona Centro del Ecuador

**Versión:** 0.1 (Semana 1) · **Estado:** borrador para revisión 1

## 1. Problema

Tungurahua, Chimborazo, Cotopaxi y Bolívar concentran atractivos naturales (volcán Chimborazo, laguna de Quilotoa, cascadas de Baños), culturales (Mama Negra, Carnaval de Guaranda, ferias indígenas) y gastronómicos (llapingachos, chugchucaras, quesos de Salinas). Sin embargo, la información para planificar una visita está **fragmentada**:

- portales de los GAD provinciales, cantonales y parroquiales con formatos y niveles de actualización distintos;
- el catastro y los boletines del Ministerio de Turismo;
- operadores privados y redes sociales, con datos de costos y horarios no verificados.

Consecuencias para el visitante: dificultad para armar un itinerario coherente por varios días, desconocimiento de tiempos de traslado entre provincias, decisiones tomadas sin considerar el clima (alta montaña y páramo) y riesgo de usar información desactualizada o falsa.

> **Evidencia pendiente:** la magnitud del problema debe respaldarse con el levantamiento real (`docs/levantamiento.md`) y con datos oficiales de turismo (Ministerio de Turismo / INEC), que deben verificarse manualmente. Este documento no afirma cifras.

## 2. Usuarios

| Usuario | Descripción | Necesidad principal |
|---|---|---|
| Visitante nacional | Turista que viaja desde Quito, Guayaquil u otras ciudades, 1–5 días | Itinerario realista con presupuesto definido |
| Visitante extranjero | Turista con poco conocimiento local, posible barrera idioma | Información confiable y citada |
| Emprendedor local (usuario indirecto) | Operadores, restaurantes, guías | Visibilidad en un catálogo verificado |
| Administrador del catálogo | Responsable de curar datos | Mantener fuentes y atractivos actualizados |

## 3. Alcance

El sistema permitirá al visitante indicar **días disponibles, presupuesto, punto de partida e intereses** y recibir:

1. Un itinerario día por día construido **exclusivamente con atractivos del catálogo verificado**.
2. Visualización en un **mapa interactivo**.
3. Descripciones **con cita** a fuentes oficiales.
4. **Costos estimados** (con indicación de su fecha y fuente).
5. **Pronóstico del clima** obtenido de una API externa.
6. **Optimización del orden de visitas** y **recálculo** ante cambios (días, presupuesto, clima adverso).

Alcance técnico: RAG sobre documentos oficiales + agente con herramientas de alcance controlado (catálogo, clima, mapas, optimizador de ruta).

## 4. Alcance negativo (el sistema nunca hará)

1. **No reservar ni cobrar**: no procesa pagos, reservas ni contacto transaccional con operadores.
2. **No inventar atractivos** ni servicios fuera del catálogo verificado.
3. **No dar recomendaciones médicas** (p. ej., mal de altura, medicación) ni de **seguridad no verificadas**; solo redirigir a fuentes oficiales (p. ej., IGEPN, SNGRE, ECU 911).
4. No afirmar costos, horarios o estados de acceso sin fuente y fecha; si no se conoce, lo declara.
5. No almacenar datos personales identificables más allá de lo necesario ni compartirlos con terceros.
6. No ejecutar acciones fuera de las herramientas autorizadas (sin navegación web libre, sin código arbitrario).
7. No sustituir información oficial de cierre de vías, alertas volcánicas o meteorológicas.
8. Cobertura limitada a las cuatro provincias; fuera de ellas, responde que no tiene cobertura.

## 5. Riesgos

Escala: Probabilidad / Impacto = Baja, Media, Alta.

| # | Riesgo | Prob. | Impacto | Mitigación |
|---|---|---|---|---|
| R1 | Alucinación: el modelo inventa atractivos, costos o citas | Media | Alta | Agente restringido a herramientas; validación de que cada atractivo exista en el catálogo; verificación de citas contra fragmentos recuperados; pruebas con casos adversarios |
| R2 | Datos del catálogo desactualizados o erróneos (costos, coordenadas) | Alta | Alta | Campo `POR VERIFICAR`; fecha de verificación; revisión manual con fuentes oficiales; mostrar vigencia al usuario |
| R3 | Fuentes oficiales no disponibles, bloqueadas o con formatos difíciles (PDF escaneado) | Media | Media | Copia local en `data/raw/` con fecha de descarga; OCR si aplica; registro en `docs/04-fuentes.md` |
| R4 | Caída o límite de uso de la API de clima | Media | Media | Caché con TTL; degradación controlada (mensaje de "clima no disponible"); API alterna |
| R5 | Prompt injection mediante texto de documentos recuperados o del usuario | Media | Alta | Separar instrucciones y contexto; sanitizar; herramientas de solo lectura; lista de acciones permitidas |
| R6 | Latencia alta por múltiples llamadas a herramientas | Media | Media | Caché, paralelización, límite de pasos del agente, presupuesto de tiempo |
| R7 | Costo del modelo generativo excede el presupuesto académico | Media | Media | Límite de tokens por consulta, caché de respuestas, modelo más económico en tareas simples |
| R8 | Riesgo de seguridad física del visitante (clima extremo, actividad volcánica, vías cerradas) | Baja | Alta | Aviso obligatorio de consultar fuentes oficiales; no emitir recomendaciones de seguridad propias |
| R9 | Incumplimiento de protección de datos personales | Baja | Alta | Minimización de datos, sin cuentas en la primera versión, revisión frente a la Ley Orgánica de Protección de Datos Personales del Ecuador (verificar texto vigente) |
| R10 | Alcance excesivo para el plazo académico | Alta | Media | Entregas semanales acotadas; MVP con catálogo reducido; priorización MoSCoW |
| R11 | Licencias/términos de uso de fuentes o API de mapas | Media | Media | Revisar términos; preferir fuentes abiertas (OpenStreetMap) con atribución |

## 6. Modelo de lenguaje elegido

> **Decisión provisional (Semana 1).** Debe confirmarse con una prueba comparativa en las semanas siguientes. Los precios, límites y capacidades exactas **deben verificarse en la documentación vigente de cada proveedor**; este documento no cita cifras.

**Elegido (provisional): Claude Sonnet (familia Claude de Anthropic), vía API.**

### Justificación

- Buen desempeño en seguir instrucciones largas y respetar restricciones de sistema, clave para el alcance negativo.
- Soporte de **uso de herramientas** (tool use) con salida estructurada, necesario para el agente de alcance controlado.
- Calidad en español y manejo de contexto extenso para incluir fragmentos RAG con citas.
- Disponible como servicio gestionado, lo que evita operar infraestructura de GPU en un proyecto académico.

### Alternativas consideradas

| Criterio | Claude Sonnet (elegido) | Modelo GPT (OpenAI) | Modelo abierto autohospedado (Llama / Mistral) |
|---|---|---|---|
| Uso de herramientas | Nativo | Nativo | Depende del modelo y del servidor de inferencia |
| Español | Bueno | Bueno | Variable según modelo |
| Costo y operación | Pago por uso, sin infraestructura | Pago por uso, sin infraestructura | Sin costo por token, pero requiere GPU y mantenimiento |
| Privacidad | Datos enviados a un tercero (revisar política) | Ídem | Datos permanecen bajo control propio |
| Riesgo principal | Dependencia de proveedor | Dependencia de proveedor | Menor calidad/robustez y carga operativa |

**Por qué no las alternativas ahora:** el modelo abierto aumenta la carga operativa y de calidad para un plazo corto; el GPT es una alternativa viable y se mantiene como plan B. La arquitectura aislará el proveedor tras una interfaz (`src/llm/`) para poder cambiar de modelo.

### Criterios de validación (a ejecutar en semanas posteriores)

- Tasa de alucinación sobre un conjunto de prueba de preguntas.
- Cobertura de citas correctas.
- Latencia p95 y costo por consulta.

## 7. Entregables de la Semana 1

Ver `README.md` para la estructura. Esta fase no implementa RAG ni agente.
