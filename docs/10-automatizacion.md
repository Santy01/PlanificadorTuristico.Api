## ADR · Flujo automatizado con IA

*Taller de la Clase 4 · 29 de octubre de 2026 · Grupo 4 · Planificador turístico*
*Integrantes: Kleber Tepud, César Vasquez, Kleber Suñiga*

> Las secciones «Contexto» a «Consecuencias» son el ADR escrito en el taller (solo se corrigió la ortografía). La sección final,
> **«Estado en la Entrega 3»**, compara ese diseño con lo que se implementó y dice qué quedó pendiente.

### Contexto
En el producto se repite un proceso que hoy hace una persona a mano: solicitud de itinerario por sector y preferencias
(60 por día). Queremos automatizarlo sin que la IA tome decisiones exactas ni riesgosas.

### Decisión
- **Disparador:** mensaje (WhatsApp, Telegram)
- **Acción final:** envía itinerario
- **Flujo fijo y no agente porque:** los pasos son siempre los mismos; el volumen es alto y repetitivo; un error tiene
  consecuencias de dinero o legales. Siempre se solicita información de una lista de destinos, precios, días y tipo de
  actividades.

| Estación | Qué hace | Decide | Qué sale |
|---|---|---|---|
| Disparador | Llega: pedido de itinerario con destino, fechas, personas y presupuesto (WhatsApp) | Sistema | Evento en la cola |
| Clasificar | Decidir el tipo (itinerario, cambio o consulta) con un número de confianza | IA | JSON {tipo, confianza} |
| Umbral | Si la confianza es baja, desviar a revisión | Código | Sigue o va a revisión |
| Extraer | Sacar los campos: destino, fechas, personas, presupuesto | IA | Datos validados con Pydantic |
| Reglas | Sumar costos con las tarifas de config/ y verificar el presupuesto | Código | Resultado exacto con su fuente |
| Revisión | El viajero confirma antes de reservar | Persona | Aprobado o corregido |
| Actuar | Registrar la propuesta; la reserva espera la confirmación | Sistema | Registro con auditoría |

- **Umbral de confianza: 0.85** (en `config/parametros.yaml`). Con los 10 casos de práctica: 7 automáticos, 3 a revisión
  (30 %), 0 errores silenciosos. Motivo: no se requiere completamente de revisión humana; la mayoría se calcula desde config.
- **La persona que revisa recibe:** una solicitud de proforma personalizada; debe registrar y validar el pago anticipado.

### Seguridad
- Todo lo que entra por el disparador es texto no confiable.

### Consecuencias
- El umbral se recalibra con el conjunto dorado (eval/casos_flujo.jsonl) cada vez que cambian el prompt o el modelo.
- Todo documento termina en un estado: procesado, en revisión o rechazado con motivo. Nunca se descarta en silencio.
- Pendiente para la Entrega 3: implementar app/flujo.py, completar los casos reales del conjunto dorado y correr eval/evaluar.py.

---

## Estado en la Entrega 3 (noviembre de 2026)

El flujo se implementó en `src/services/itinerario.py` (no en un `app/flujo.py` aparte, que habría duplicado la lógica)
con un disparador web en lugar de mensajería. Estación por estación:

| Estación del taller | Implementado | Decide | Diferencia con el taller |
|---|---|---|---|
| Disparador | Formulario web → `POST /itinerario` o `/itinerario/stream` | Sistema | **No hay WhatsApp ni Telegram ni cola**: la solicitud es síncrona por HTTP |
| Clasificar | **Regla de alcance** (`src/alcance.py`, `config/alcance.yaml`): reservas y pagos, fuera de la zona, médico, inyección. Si no la detecta, el modelo marca `fuera_de_alcance` | **Código**, y la IA como segunda barrera | No hay clasificación por tipo con número de confianza: los campos llegan estructurados del formulario. La clasificación que importa es «dentro o fuera de alcance», y la hace una regla porque el modelo aceptó 4 de 4 fuera de alcance en la evaluación |
| Umbral | Dos umbrales en lugar de uno: el **piso de similitud** del RAG (0.83; bajo él no se usan fuentes) y la **validación del JSON** (si no cumple tras una corrección → `revision_humana`) | Código | No existe el umbral de confianza 0.85 del taller: el modelo de Groq no entrega una confianza calibrada |
| Extraer | Pydantic valida la entrada (`SolicitudItinerario`); la IA elige atractivos y motivos con esquema JSON estricto | Código / IA | Los campos no se extraen de texto libre: llegan del formulario |
| Reglas | `armar_itinerario` y `totalizar`: catálogo, jornada máxima, costos con su fuente, presupuesto, citas válidas; luego clima | Código | Igual al taller; los parámetros están en `config/parametros.yaml` |
| Revisión | `estado = revision_humana` cuando el modelo no produce un itinerario válido; confirmación del visitante antes de **enviar** el itinerario (agente) | Persona | **No hay reserva ni pago anticipado**: están fuera del alcance (HU-09). La persona confirma el envío, no una reserva |
| Actuar | Respuesta con el itinerario; envío simulado a la bandeja de salida (`logs/bandeja_salida.jsonl`) | Sistema | Auditoría en `logs/llm.jsonl` y `logs/agente.jsonl` |

**Estados finales:** toda solicitud termina en `ok`, `rechazado` (con motivo) o `revision_humana`. Ninguna se descarta en silencio.

**Conjunto dorado:** son las 15 solicitudes de `eval/solicitudes.jsonl`, escritas antes de correr, en lugar de un
`eval/casos_flujo.jsonl` aparte. Resultado: 14/15, y la decimoquinta pasa corrida aparte (falla por el límite de tokens
por minuto del plan gratuito). Las adversarias se rechazan 4/4. Detalle en
[evidencias/semana-3/evaluacion-entrega3.md](evidencias/semana-3/evaluacion-entrega3.md).

**Pendiente respecto del taller:**
- Disparador por mensajería (WhatsApp o Telegram) y cola de eventos.
- Un umbral de confianza calibrado: requeriría que el modelo entregue una confianza y medirla con más casos.
- Llevar el conjunto dorado a 20 casos.
