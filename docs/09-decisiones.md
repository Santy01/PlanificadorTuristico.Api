# Decisiones de arquitectura (ADR)

*Grupo 4 · Planificador turístico de la zona centro del Ecuador · versión 0.5.0 · noviembre de 2026*

Cada decisión tiene su contexto, lo que se decidió, por qué y qué costó. La de la plataforma de despliegue está aparte
en [adr/0003-plataforma-despliegue.md](adr/0003-plataforma-despliegue.md).

| # | Decisión | Entrega | Dónde vive |
|---|---|---|---|
| 1 | Agente de alcance controlado: lista cerrada, tope y confirmación humana | 3 | `src/agente.py`, `src/tools/`, `config/parametros.yaml` |
| 2 | Proveedor de respaldo (Gemini) ante la caída o la cuota de Groq | 4 | `src/config.py`, `src/services/llm.py` |
| 3 | Límite de peticiones por IP con 429 | 4 | `src/limites.py`, `config/parametros.yaml` |
| 4 | Frontend y API en el mismo dominio, repartidos por ruta en Traefik | 4 | `docker-compose.yml`, `tests/test_despliegue.py` |
| 5 | Catálogo verificado por el equipo e importación segura desde Excel | 4 | `data/catalogo/`, `scripts/importar_catalogo.py`, `tests/test_catalogo_datos.py` |
| 6 | Versiones fijas, índice del RAG por volumen y un solo flujo de Gitleaks | 4 | `Dockerfile`, `requirements.txt`, `.github/workflows/ci-cd.yml` |

---

## ADR 1 · Agente de alcance controlado

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

---

## ADR 2 · Proveedor de respaldo (Gemini)

*Entrega 4 · Código: `src/config.py`, `src/services/llm.py` · Evidencia: [semana 4 §3](evidencias/semana-4/README.md)*

**Contexto.** El plan gratuito de Groq limita los tokens por minuto (8 000) y puede fallar. Una caída o un 429 sin
respaldo dejaba al visitante sin itinerario justo en la demostración (riesgo R1 de [riesgos.md](riesgos.md)).

**Decisión.** Un segundo proveedor, Gemini (`gemini-3.5-flash`), con el mismo cliente `ClienteLLM`. Un error definitivo
(401, 404, 400) pasa directo al respaldo sin reintentos; un error pasajero (429, 5xx, tiempo agotado) se reintenta con
espera creciente y respeta `Retry-After`, salvo que pida más de 20 s, caso en que también pasa al respaldo. Si fallan los
dos, la API responde **503 con un mensaje claro** y nunca el error crudo del proveedor. Cambiar de modelo es cambiar
`GEMINI_MODEL`, sin tocar el código.

**Por qué.** Se probó con proveedores reales y hallaron dos problemas que los dobles no veían: `gemini-2.5-flash` ya no
estaba disponible (404) y Gemini 3 exige devolver la `thought_signature` en la vuelta siguiente del agente; el respaldo
a mitad de una conversación se corrigió con una firma ficticia documentada por Google para historiales de otro origen.

**Consecuencias.** Con Groq inválido responde Gemini en unos 8 a 13 s (Groq, ~1 s), dentro del p95 de 20 s. El plan
gratuito de Gemini también se satura: con los dos agotados, el 503 es el comportamiento esperado. En el streaming, la
respuesta final todavía no indica qué proveedor respondió.

## ADR 3 · Límite de peticiones por IP

*Entrega 4 · Código: `src/limites.py`, `config/parametros.yaml` (`limites`) · Pruebas: `tests/test_limites.py`*

**Contexto.** Cada itinerario gasta ~6 000 tokens de la cuota gratuita: una sola persona o un script puede agotarla para
todos (OWASP LLM10, consumo sin límite).

**Decisión.** Ventana deslizante de 60 s por IP: 10 solicitudes de itinerario y 20 mensajes del agente por minuto; al
pasarse, **429 con `Retry-After`**. La IP real se toma de `X-Forwarded-For` según los proxies de confianza
(`proxies_confiables: 1`, Traefik): las entradas anteriores las puede escribir el propio cliente.

**Consecuencias.** Vive en memoria: vale con un solo proceso de uvicorn, como en `docker-compose.yml`; con varios
procesos habría que pasarlo a Redis. Está probado contra la URL con el caso del 429 de `tests/smoke.py`.

## ADR 4 · Frontend y API en el mismo dominio

*Entrega 4 · Código: `docker-compose.yml` · Pruebas: `tests/test_despliegue.py`*

**Contexto.** El frontend (Angular, repositorio `PlanificadorTuristico.Web`) y la API necesitan hablarse sin configurar
CORS ni exponer dos dominios.

**Decisión.** Un solo dominio, `planificador.bhsolutions.cloud`. Traefik da a la API solo sus rutas (`/itinerario`,
`/agente`, `/health`, `/docs`, `/openapi.json`, `/redoc`) con prioridad 100, y todo lo demás va al contenedor del
frontend (prioridad 1). La API no publica puertos: Traefik llega a ella por la red `traefik_proxy`.

**Consecuencias.** Si se agrega un endpoint hay que sumarlo a la regla de Traefik; `tests/test_despliegue.py` lo comprueba
y evita que quede sin ruta. Los dos despliegues son independientes: cada repositorio tiene su pipeline.

## ADR 5 · Catálogo verificado e importación segura desde Excel

*Entrega 4 · Código: `scripts/importar_catalogo.py`, `tests/test_catalogo_datos.py` · Reporte: [importación del 7 nov](evidencias/catalogo/importacion-reducido_verificado_2026-11-07.md)*

**Contexto.** El equipo verificó a mano 60 atractivos (costos, duraciones y fuentes). Excel dañó el archivo: cambió el
separador, la codificación (CP850) y las coordenadas.

**Decisión.** En vez de corregirlo a mano, un importador con reglas explícitas que rearma las coordenadas, no deja que un
vacío borre datos existentes y escribe un reporte de cada cambio (60 filas, 0 `POR VERIFICAR`). Las pruebas del CI
impiden que vuelva a pasar.

**Consecuencias.** El modelo del itinerario ve solo esos 60 (`atractivos_reducido.csv`); el agente usa los 139, y en los
79 restantes muchos costos siguen `POR VERIFICAR` (se excluyen del total y se avisa). Cambiar el catálogo obliga a
reconstruir el corpus y el índice (251 fragmentos) y a recalibrar el piso de similitud ([RAG §9](07-rag.md)): tras el
cambio se mantuvo 0.83 en vez de ajustarlo a una diferencia de 0.0004.

## ADR 6 · Versiones fijas, índice del RAG por volumen y un solo flujo de Gitleaks

*Entrega final · Código: `Dockerfile`, `requirements.txt`, `.github/workflows/ci-cd.yml`*

**Contexto.** Tres observaciones de la revisión: `torch` y las dependencias sin versión, la imagen base sin digest, dos
workflows que revisaban secretos, y un índice que el despliegue no actualizaba.

**Decisión.**
- **Versiones fijas:** `requirements.txt` con `==`, `torch` con versión exacta y `python:3.12-slim` con su digest, para
  que la imagen de hoy sea la misma dentro de seis meses y una dependencia nueva no rompa el despliegue sin aviso.
- **Un solo flujo de Gitleaks:** el job `secretos` de `ci-cd.yml` (historial completo); se eliminó `secretos.yml`, que
  hacía lo mismo.
- **Índice del RAG por volumen, a mano:** el corpus original (`data/raw`) no se versiona (son páginas descargadas), así
  que el índice no se puede reconstruir en el pipeline ni va en la imagen. Se construye en el equipo del que lo genera y se
  sube a `/opt/planificador/data/vectorstore`. Es el riesgo **R9**; lo mitigan `/health`, que informa cuántos fragmentos
  tiene el índice, y que sin índice la API siga funcionando, sin citas, avisándolo.

**Consecuencias.** Subir una dependencia es una decisión explícita (cambiar la versión y volver a pasar las pruebas).
Actualizar el corpus exige un paso manual, documentado en [08-despliegue-docker.md](08-despliegue-docker.md).
