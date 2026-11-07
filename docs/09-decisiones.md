## ADR · Agente de alcance controlado

*Entrega 3 · Grupo 4 · Planificador turístico de la zona centro del Ecuador · noviembre de 2026*
*Código: `src/agente.py`, `src/tools/`, `config/parametros.yaml`*

### Contexto

El itinerario se genera con un flujo fijo: una llamada al modelo, y después el código valida, calcula y arma la
respuesta. Pero, una vez generado, el visitante necesita cambiarlo o preguntar sobre él, y ese camino no se puede
escribir de antemano: «va a llover el día 1», «el museo está cerrado», «¿cuánto cuesta la entrada?», «envíamelo». Para
eso se usa un agente: el modelo dentro de un bucle que **pide** herramientas, mientras el código decide si las ejecuta.

### Decisión: las seis decisiones del agente

| Decisión | Valor | Dónde vive |
|---|---|---|
| 1 · Meta | Ajustar un itinerario ya generado ante cambios (lluvia, cierre, preferencia) y responder dudas sobre sus atractivos con fuente | Prompt `src/prompts/agente_v1.md` |
| 2 · Herramientas libres | `recalcular(dia, quitar_id, motivo)` · `buscar_fragmentos(pregunta)` · `consultar_clima(dia)` | `PERMITIDAS` en `src/agente.py` |
| 3 · Con confirmación | `enviar_itinerario(correo)`: es lo único que sale del sistema | `REQUIEREN_OK` en `src/agente.py` |
| 4 · Fuera de la lista | `reservar_hotel`, `cobrar_tarjeta`, comprar entradas: el planificador no reserva ni cobra (HU-09). No existen como función, así que el modelo no puede pedirlas | No están en `PERMITIDAS` |
| 5 · Tope | `max_iter: 6` vueltas por solicitud; al llegar: «No pude completar el ajuste del itinerario; un asesor turístico lo revisará» | `config/parametros.yaml` |
| 6 · En `config/` | Jornada máxima (8 h), duración por defecto (2 h), holgura del reemplazo (0.5 h), tope del agente, vencimiento de la confirmación (15 min), turnos de historial (6), pisos de similitud del RAG | `config/parametros.yaml`, `.env` |

Las tres primeras decisiones están **en código, no en el prompt**: ningún texto, ni del visitante ni de un documento,
puede cambiarlas.

### Por qué cada herramienta está en su nivel

| Herramienta | Nivel | Razón |
|---|---|---|
| `buscar_fragmentos` | Libre | Solo lee. Usa el piso de similitud para preguntas (0.86): si nada se parece, devuelve vacío y el modelo debe decir que no tiene el dato |
| `consultar_clima` | Libre | Solo lee. El lugar y la fecha los toma del itinerario, no del modelo |
| `recalcular` | Libre | Cambia el itinerario **del visitante**, dentro del sistema y con reglas fijas: misma provincia, no repetido, cabe en el día y, con lluvia, bajo techo. El modelo no elige el reemplazo, solo indica qué sale y por qué. Se ve en `cambios` y no tiene efecto fuera de la pantalla |
| `enviar_itinerario` | Con confirmación | Sale del sistema y no se puede deshacer. La interfaz muestra el destino y el contenido reales; se ejecuta solo con `POST /agente/confirmar/{id}`, una sola vez, antes de que venza |

### Controles además de las tres constantes

- **Validación antes de ejecutar:** los argumentos pasan por el modelo Pydantic de cada herramienta (por ejemplo,
  `dia` de 1 a 7, `motivo` solo lluvia, cerrado o preferencia). Si fallan, el modelo recibe el error y nada se ejecuta.
- **Regla de negocio (`prevalidar`):** el correo de `enviar_itinerario` tiene que aparecer en lo que escribió el visitante.
  En la evaluación con Groq, el modelo inventó un correo cuando el visitante no lo dio.
- **Verificación de la respuesta:** cada hora y cada monto en USD de la respuesta final debe aparecer en lo que el modelo
  recibió. Si no aparece, el código pide una corrección; si insiste, la respuesta sale con una advertencia visible.
  En la prueba con Groq, el modelo había inventado un horario «según la ficha oficial».
- **Lo que ve el modelo:** el itinerario se le envía armado con datos del catálogo, no con el texto que manda el cliente,
  para que un nombre o un motivo alterado no sirvan como vía de inyección.
- **Auditoría:** `logs/agente.jsonl` registra cada vuelta, las herramientas pedidas, los rechazos, las pausas y las
  decisiones del visitante, sin el texto del visitante.
- **Una herramienta que falla** devuelve un error al modelo; el bucle no se rompe.

### Seguridad (OWASP Top 10 para aplicaciones agénticas 2026)

| Riesgo | Mitigación |
|---|---|
| ASI01 · Secuestro del objetivo (instrucción escondida en un documento o en el mensaje) | Los permisos son las tres constantes del código; los fragmentos se limpian (sin `<` ni `>`) y se declaran datos. Probado en `test_B_inyeccion_en_un_fragmento_no_da_permisos` y en los casos B1 y B2 de la evaluación |
| ASI02 · Mal uso de herramientas | Lista cerrada, validación de argumentos, reemplazos decididos por código, correo verificado y confirmación humana |
| ASI04 · Cadena de suministro | No se instalan conectores ni skills de terceros; las herramientas son funciones del propio repositorio |

### Consecuencias

- Una conversación cuesta entre 1 y 3 vueltas (media de 1.6 en la evaluación), unos 2 400 tokens por caso. El tope de 6
  vueltas limita el peor caso.
- La API no guarda la conversación: el cliente reenvía el itinerario y el historial. Las acciones pendientes viven en
  memoria, así que sirven con **un** proceso de uvicorn (como en `docker-compose.yml`); con varios procesos hace falta
  un almacén compartido.
- El envío por correo es **simulado**: queda en `logs/bandeja_salida.jsonl` con el correo enmascarado. Conectar SMTP sería
  reemplazar `_entregar` en `src/tools/enviar_itinerario.py`, sin tocar el agente.
- Evidencia: `tests/test_agente.py` cubre los escenarios A, B, C y D sin red, y la evaluación con Groq da 10/10
  ([evidencias/semana-3/evaluacion-entrega3.md](evidencias/semana-3/evaluacion-entrega3.md)).

### Alternativas descartadas

- **Que el agente genere el itinerario completo:** más vueltas y más tokens por solicitud, sin ganar nada, porque los
  pasos son siempre los mismos. Se mantuvo el flujo fijo ([10-automatizacion.md](10-automatizacion.md)).
- **Que el modelo proponga el reemplazo por nombre:** podría elegir algo fuera del catálogo o que no cabe en el día.
  `recalcular` decide con reglas deterministas.
- **Confirmación también para `recalcular`:** el cambio es visible, reversible (se puede volver a pedir) y no sale del
  sistema. Una confirmación por cada cambio haría la conversación más lenta sin reducir riesgo.
