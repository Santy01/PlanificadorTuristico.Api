# Planificador Turístico Inteligente de la Zona Centro del Ecuador · Entrega final

Proyecto académico: constructor de itinerarios con mapa que usa **RAG** y un **agente de alcance controlado** sobre un
catálogo verificado de atractivos de **Tungurahua, Chimborazo, Cotopaxi y Bolívar**, con pronóstico del clima de una
API externa. Backend en FastAPI (este repositorio); frontend en Angular (`PlanificadorTuristico.Web`).

**URL pública:** <https://planificador.bhsolutions.cloud> (API y frontend en el mismo dominio; documentación interactiva
en `/docs`, estado en `/health`).

## Qué problema resuelve y para quién

Quien visita la zona centro del Ecuador (turistas nacionales y extranjeros, o personas de la zona que reciben visitas)
tiene que armar su viaje juntando páginas oficiales, de prensa y mapas: no sabe qué atractivos caben en un día, cuánto
cuestan, qué pasa si llueve ni cuánto le queda del presupuesto. El planificador recibe los días, el presupuesto, el
punto de partida y los intereses, y devuelve un itinerario con mapa, costos, clima por día y **citas a las fuentes** que
respaldan cada actividad. Un agente permite ajustarlo conversando («va a llover el día 1») sin inventar datos: si no
hay evidencia, lo dice. Reservas, pagos, consejo médico y destinos fuera de la zona quedan fuera de alcance a propósito.

## Estado de la entrega final (versión 0.5.0)

| Punto | Estado | Dónde está |
|---|---|---|
| Conocimiento especializado | Hecho | 139 fichas de atractivos y páginas oficiales y de prensa, con manifiesto trazable: `data/corpus/manifiesto.csv`, `scripts/construir_corpus.py`. Catálogo verificado de 60 atractivos para el itinerario; índice de 251 fragmentos |
| RAG con citas y silencio | Hecho | `src/services/rag.py`: Chroma + E5, agrupado por atractivo, margen y **piso de similitud** calibrado (`.env`, [docs/07-rag.md](docs/07-rag.md)). Las citas las valida el código |
| Agente de alcance controlado | Hecho | `src/agente.py`: `PERMITIDAS` (4 herramientas), `max_iter` en `config/parametros.yaml`, `REQUIEREN_OK` (envío con confirmación). `POST /agente` y `POST /agente/confirmar/{id}`. Decisiones en [docs/09-decisiones.md](docs/09-decisiones.md) |
| Herramientas deterministas | Hecho | `src/tools/`: esquema Pydantic, función determinista y prueba por herramienta; parámetros en `config/` |
| Flujo automatizado | Hecho (disparador web) | Regla de alcance en código → RAG → modelo → reglas del código → persona. [docs/10-automatizacion.md](docs/10-automatizacion.md) |
| Integración estable con la IA | Hecho | `src/services/llm.py`: tiempo límite, reintentos con espera creciente, respaldo (Gemini), mensaje claro si fallan ambos; límite por IP con 429 en `src/limites.py` |
| Calidad del software | Hecho | `pytest -q`: **234 pruebas**, cobertura del 95 % (el build falla por debajo del 85 %). Plan en [docs/11-plan-de-calidad.md](docs/11-plan-de-calidad.md) |
| Pruebas funcionales contra la URL | Hecho | `tests/smoke.py`: 23 casos con el modelo real (salud, tareas, fuera de dominio, inyección, entrada inválida, agente y 429). Detalle y resultado en [docs/08-pruebas.md](docs/08-pruebas.md) |
| Evaluación | Hecho | `eval/`: 15 preguntas, 15 solicitudes y 10 casos del agente, escritos antes de correr. `python eval/evaluar.py` (modos `rag`, `solicitudes` y `agente`; con `--url` contra producción). Semana 3: [evaluacion-entrega3.md](docs/evidencias/semana-3/evaluacion-entrega3.md). Contra producción y comparada: [evaluacion-produccion.md](docs/evidencias/semana-4/evaluacion-produccion.md) |
| Despliegue y CI/CD | Hecho | Docker + Traefik en VPS; CD solo desde `master`. `.github/workflows/ci-cd.yml`: Gitleaks, pruebas, imagen y despliegue. [docs/08-despliegue-docker.md](docs/08-despliegue-docker.md) |
| Protección de credenciales | Hecho | `.env` fuera de git y de la imagen; claves en el servidor y en GitHub Secrets; Gitleaks sobre todo el historial. [docs/evidencias/semana-4/README.md](docs/evidencias/semana-4/README.md) |
| Uso de IA y aportes | Hecho | [docs/12-declaracion-uso-ia.md](docs/12-declaracion-uso-ia.md) |

### Lo que NO hace todavía

- **No optimiza la ruta** (HU-07): el modelo agrupa por cantón y el orden se muestra tal cual. No hay geocodificación
  del punto de partida.
- **No envía correos de verdad:** `enviar_itinerario` es simulado (queda en `logs/bandeja_salida.jsonl` con el correo
  enmascarado).
- **No hay disparador por mensajería** (WhatsApp o Telegram) como planteó el taller de automatización: el disparador es
  el formulario web.
- **El frontend todavía no usa el agente:** el contrato está listo ([docs/06-guia-frontend.md §7](docs/06-guia-frontend.md)),
  pero falta el panel de conversación y el botón de confirmación.
- **Una sola corrida por caso de evaluación:** la variación del modelo no está medida.
- **La regla de alcance es una lista de patrones** (`config/alcance.yaml`, en español): un destino fuera de la zona o una
  inyección en otro idioma que no coincida con un patrón pasa al modelo, que es la segunda barrera. En las pruebas, el
  modelo ignoró una inyección en inglés, pero esa barrera depende del modelo y no es una garantía.
- **Las acciones pendientes del agente y el límite por IP viven en memoria:** sirven con un solo proceso de uvicorn.
- **El índice del RAG no se actualiza con el despliegue:** va en un volumen del servidor y se sube a mano cuando cambia
  el corpus (procedimiento en [docs/08-despliegue-docker.md](docs/08-despliegue-docker.md)).
- **El catálogo no distingue eventos con fecha** (p. ej. la Fiesta de las Flores y de las Frutas, en febrero): `recalcular`
  puede proponer uno fuera de temporada.
- **Catálogo:** los 60 atractivos que ve el modelo del itinerario están verificados (costos, duraciones y fuentes completos, 7 nov 2026). De los otros 79, que solo usa el agente, muchos costos siguen `POR VERIFICAR`: se excluyen del total y se avisa.

## Estructura

```
.
├── config/
│   ├── parametros.yaml       # jornada, holgura del reemplazo, tope del agente, límites por IP
│   └── alcance.yaml          # reglas de alcance (reservas, fuera de la zona, médico, inyección)
├── data/
│   ├── catalogo/             # atractivos.csv (139), atractivos_reducido.csv (60, para el prompt)
│   ├── corpus/manifiesto.csv # trazabilidad de cada documento del RAG
│   ├── raw/                  # fichas y páginas descargadas (no versionado)
│   └── vectorstore/          # índice Chroma de 251 fragmentos (no versionado)
├── docs/                     # propuesta, requisitos, arquitectura, RAG, despliegue, pruebas, ADR, calidad y evidencias
├── eval/                     # conjuntos de evaluación, evaluar.py, línea base y resultados
├── scripts/                  # corpus, ingesta, importación del catálogo, comparación de prompts, servidor simulado
├── src/
│   ├── main.py               # FastAPI: /health, /itinerario, /itinerario/stream, /agente, /agente/confirmar/{id}
│   ├── agente.py             # agente de alcance controlado: lista cerrada, tope y confirmación
│   ├── alcance.py            # regla de alcance en código, antes del modelo
│   ├── limites.py            # límite de peticiones por IP (429 con Retry-After)
│   ├── catalogo.py           # carga el catálogo verificado
│   ├── config.py             # lee .env (Groq, Gemini de respaldo, simulado)
│   ├── parametros.py         # lee y valida config/parametros.yaml
│   ├── schemas.py            # entradas, salida del modelo y respuestas de la API
│   ├── prompts/              # system_v1…v4.md (itinerario) y agente_v1.md
│   ├── services/
│   │   ├── clima.py          # Open-Meteo con degradación controlada
│   │   ├── indice.py         # fragmentación, embeddings y configuración del RAG
│   │   ├── itinerario.py     # el modelo propone, el código dispone
│   │   ├── llm.py            # ClienteLLM: reintentos, 429, timeout, respaldo, JSON validado, tools, log
│   │   └── rag.py            # recuperación con margen y piso de similitud
│   └── tools/
│       ├── recalcular.py         # reemplaza un atractivo (lluvia, cerrado, preferencia) con reglas fijas
│       ├── buscar_fragmentos.py  # busca en las fuentes con el piso de similitud para preguntas
│       ├── consultar_clima.py    # pronóstico de un día del itinerario
│       └── enviar_itinerario.py  # requiere confirmación del visitante (envío simulado)
├── tests/                    # 234 pruebas sin red ni clave (dobles del modelo, del RAG y del clima) y smoke.py (contra la URL)
├── Dockerfile, docker-compose.yml
└── .github/workflows/ci-cd.yml   # Gitleaks, pruebas, imagen y despliegue
```

## Instalación

Requisitos: Python 3.10 o superior.

```bash
python -m venv .venv
.venv\Scripts\Activate.ps1        # Windows (PowerShell);  en Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env              # en PowerShell: Copy-Item .env.example .env
# Edite .env: GROQ_API_KEY (https://console.groq.com/keys). Nunca suba .env al repositorio.

# Índice del RAG (una vez; sin él la API funciona igual, pero sin citas)
python scripts/construir_corpus.py   # fichas + páginas fuente (con --sin-red, solo fichas)
python scripts/ingestar_rag.py       # fragmenta, calcula embeddings e indexa en data/vectorstore

uvicorn src.main:app --reload        # http://127.0.0.1:8000/docs
```

### Variables de entorno

Todas están en [.env.example](.env.example) (solo los nombres, sin valores). `.env` está en `.gitignore` y en
`.dockerignore`: nunca entra en git ni en la imagen. Las que importan:

| Variable | Para qué |
|---|---|
| `GROQ_API_KEY`, `GEMINI_API_KEY` | Claves del proveedor principal y del de respaldo (secretas) |
| `LLM_PRINCIPAL`, `LLM_RESPALDO`, `GROQ_MODEL`, `GEMINI_MODEL` | Qué proveedor y modelo usar |
| `LLM_TIMEOUT_S`, `LLM_REINTENTOS`, `LLM_MAX_TOKENS` | Tiempo límite, reintentos y tope de tokens de salida |
| `VECTOR_DB_PATH`, `EMBEDDING_MODEL`, `RAG_ACTIVO`, `RAG_*` | Índice vectorial, modelo de embeddings y umbrales del RAG |
| `WEATHER_API_BASE_URL`, `WEATHER_TIMEOUT_S` | Open-Meteo (no requiere clave) |

## Uso

**Itinerario** (`POST /itinerario`, o `/itinerario/stream` con texto en vivo):

```json
{"dias": 2, "presupuesto_usd": 150, "punto_partida": "Ambato", "intereses": ["natural", "gastronómico"],
 "notas": null, "fecha_inicio": "2026-11-20"}
```

El modelo elige los atractivos y escribe los motivos. El código descarta lo que no está en el catálogo, respeta la
jornada de 8 h, calcula los costos (los `POR VERIFICAR` se excluyen y el total se marca parcial), valida las citas,
agrega el clima por día y advierte si se supera el presupuesto. Reservas, pagos, consejo médico, destinos fuera de la
zona e instrucciones dentro de `notas` se rechazan **antes** de llamar al modelo.

**Agente** (`POST /agente`): se envía el itinerario actual con un mensaje, por ejemplo «va a llover el día 1». El
agente consulta el clima, reemplaza lo que es al aire libre con `recalcular` y devuelve el itinerario actualizado, los
cambios, las fuentes consultadas y las advertencias. Si el visitante pide enviarlo a su correo, la respuesta es
`requiere_confirmacion` y nada se envía hasta `POST /agente/confirmar/{id}`. Contrato en
[docs/06-guia-frontend.md §7](docs/06-guia-frontend.md).

## Despliegue

La API corre como contenedor Docker en un VPS, detrás de Traefik, en `https://planificador.bhsolutions.cloud` (el
frontend comparte el dominio). Cada push a `master` ejecuta `.github/workflows/ci-cd.yml`: revisión de secretos,
pruebas, construcción de la imagen y, si todo pasa, despliegue por SSH seguido de `tests/smoke.py` contra la URL. El
`.env` y el índice del RAG viven en el servidor, no en el repositorio ni en la imagen. Paso a paso, procedimiento para
actualizar el índice y problemas encontrados en [docs/08-despliegue-docker.md](docs/08-despliegue-docker.md).

Comprobación rápida: `GET /health` debe responder `status: ok`, la versión (0.5.0), los fragmentos del índice (251) y
qué proveedores están configurados, sin mostrar ninguna clave.

## Pruebas y evaluación

```bash
pytest -q                                   # 234 pruebas, sin red ni clave
pytest -q --cov=src                         # cobertura (CI exige 85 %)
python eval/evaluar.py rag                  # sin Groq: acierto y silencio del RAG
python eval/evaluar.py solicitudes --pausa 45
python eval/evaluar.py agente --pausa 40
```

**Pruebas funcionales contra la URL desplegada** (23 casos con el modelo real, sin clave en el cliente; también corren
en el pipeline después de cada despliegue; casos y resultado en [docs/08-pruebas.md](docs/08-pruebas.md)):

```bash
python tests/smoke.py https://planificador.bhsolutions.cloud
```

**Evaluación contra producción** (los mismos casos de la semana 3, por HTTP; la comparación está en
[docs/evidencias/semana-4/evaluacion-produccion.md](docs/evidencias/semana-4/evaluacion-produccion.md)):

```bash
python eval/evaluar.py solicitudes --url https://planificador.bhsolutions.cloud --pausa 45
python eval/evaluar.py agente --url https://planificador.bhsolutions.cloud --pausa 40
```

## Documentación

1. [Propuesta](docs/01-propuesta.md) · [Levantamiento](docs/levantamiento.md)
2. [Requisitos](docs/02-requisitos.md)
3. [Arquitectura](docs/03-arquitectura.md)
4. [Fuentes](docs/04-fuentes.md)
5. [Guía del frontend](docs/06-guia-frontend.md)
6. [RAG](docs/07-rag.md)
7. [Despliegue con Docker](docs/08-despliegue-docker.md) · [Pruebas funcionales](docs/08-pruebas.md)
8. [Decisiones (ADR)](docs/09-decisiones.md)
9. [Flujo automatizado](docs/10-automatizacion.md)
10. [Plan de calidad](docs/11-plan-de-calidad.md)
11. [Declaración de uso de IA y aportes](docs/12-declaracion-uso-ia.md)
12. [Matriz de riesgos](docs/riesgos.md) · [ADR-0003: plataforma de despliegue](docs/adr/0003-plataforma-despliegue.md)
13. Evidencias: [Semana 1](docs/evidencias/semana-1/README.md) · [Semana 2](docs/evidencias/semana-2/README.md) · [Semana 3](docs/evidencias/semana-3/README.md) · [Evaluación de la Entrega 3](docs/evidencias/semana-3/evaluacion-entrega3.md) · [Semana 4](docs/evidencias/semana-4/README.md) · [Evaluación contra producción](docs/evidencias/semana-4/evaluacion-produccion.md)
14. Presentación de la sustentación: [PDF](docs/sustentacion-grupo4.pdf)

| Formulario | Resultado con mapa |
|---|---|
| ![Formulario](docs/evidencias/semana-2/captura-02-formulario-frontend.png) | ![Resultado](docs/evidencias/semana-2/captura-04-resultado-mapa.png) |

## Integrantes y responsabilidades

Grupo 4. Detalle de los aportes de cada integrante, con la evidencia en el historial de git, en
[docs/12-declaracion-uso-ia.md](docs/12-declaracion-uso-ia.md).

| Integrante (GitHub) | Responsabilidad principal |
|---|---|
| Santy01 | Base del proyecto, API FastAPI y esquemas, servicio de índice y recuperación del RAG, evaluación, límite por IP y `/health`, pruebas funcionales y presentación |
| kleber212023 | Cliente del modelo y prompts, servicio del itinerario, corpus e ingesta del RAG, agente de alcance controlado, regla de alcance, Docker, Traefik y pipeline CI/CD, documentación de despliegue |
| CesarVasquez1985 | Catálogo y servicio de clima, suite de pruebas, herramientas del agente, Gemini como respaldo, catálogo verificado con importación segura, documentación y presentación |

## Aviso sobre IA y datos

- **El texto lo genera un modelo.** Los motivos de cada actividad, los supuestos y las respuestas del agente los escribe
  un modelo de lenguaje (Groq `openai/gpt-oss-20b`, con Gemini como respaldo). El código valida que los atractivos
  existan en el catálogo, calcula los costos y comprueba las citas, pero el texto puede tener imprecisiones: la información
  turística debe contrastarse con fuentes oficiales.
- **Qué se guarda en `logs/`** (sin el texto del visitante ni claves): `llm.jsonl` (proveedor, modelo, tokens, tiempo y tipo
  de error de cada llamada al modelo), `agente.jsonl` (cada decisión del agente: herramienta y resultado) y
  `bandeja_salida.jsonl` (envío simulado, con el correo **enmascarado**). La API no tiene cuentas ni guarda
  conversaciones: el cliente reenvía el itinerario en cada mensaje. El límite por IP vive en la memoria del proceso.
- **Qué sale hacia terceros.** A Groq o Gemini viaja la solicitud del visitante (días, presupuesto, intereses y notas
  libres) junto con el catálogo y los fragmentos recuperados: no escriba en las notas datos personales. A Open-Meteo
  solo viajan coordenadas de atractivos y fechas.
- El sistema no realiza reservas ni pagos ni emite recomendaciones médicas o de seguridad.
