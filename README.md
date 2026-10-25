# Planificador Turístico Inteligente de la Zona Centro del Ecuador

Proyecto académico: constructor de itinerarios con mapa que utiliza RAG y un agente de alcance controlado sobre un catálogo verificado de atractivos de **Tungurahua, Chimborazo, Cotopaxi y Bolívar**, con pronóstico del clima de una API externa.

**Estado:** Semana 2 — integración con el modelo generativo (**Groq**) para generar itinerarios. Semana 1: propuesta, requisitos, arquitectura, fuentes, catálogo inicial. El RAG con citas, el clima, el mapa y el optimizador de ruta **aún no están implementados**.

## Estructura

```
.
├── README.md
├── .gitignore
├── .env.example
├── requirements.txt
├── docs/
│   ├── 01-propuesta.md
│   ├── 02-requisitos.md
│   ├── 03-arquitectura.md
│   ├── 04-fuentes.md
│   ├── levantamiento.md
│   └── evidencias/
│       └── semana-1/
│           └── README.md
├── data/
│   ├── raw/                  # documentos fuente descargados (no versionados)
│   └── catalogo/
│       ├── atractivos.csv
│       └── README.md
├── src/
│   ├── main.py               # FastAPI: /health y POST /itinerario
│   ├── config.py             # lee .env (Groq / simulado)
│   ├── catalogo.py           # carga el catálogo verificado
│   ├── schemas.py            # entrada validada y esquema JSON del modelo
│   ├── services/
│   │   ├── llm.py            # ClienteLLM: reintentos, 429, timeout, respaldo, log
│   │   └── itinerario.py     # el modelo propone, el código dispone
│   └── prompts/              # system_v1.md … v3.md
├── scripts/                  # primera_llamada, probar_itinerario, comparar_prompts, demo_429, servidor_simulado
├── eval/entradas_prompts.csv # 10 entradas de evaluación
└── tests/
```

## Instalación

Requisitos: Python 3.10 o superior.

```bash
# 1. Crear y activar entorno virtual
python -m venv .venv
# Windows (PowerShell)
.venv\Scripts\Activate.ps1
# Linux / macOS
source .venv/bin/activate

# 2. Instalar dependencias
pip install -r requirements.txt

# 3. Configurar variables de entorno
cp .env.example .env        # en PowerShell: Copy-Item .env.example .env
# Edite .env y complete los valores. Nunca suba .env al repositorio.

# 4. Ejecutar el servidor
uvicorn src.main:app --reload
```

Verificar: abrir `http://127.0.0.1:8000/health`, debe responder `{"status": "ok"}`.

## Integración con el LLM (Groq)

1. Cree una clave en https://console.groq.com/keys y péguela en `.env` como `GROQ_API_KEY` (el modelo por defecto es `openai/gpt-oss-20b`, configurable con `GROQ_MODEL`).
2. `python scripts/primera_llamada.py` — primera llamada real.
3. `python scripts/probar_itinerario.py --dias 2 --presupuesto 150 --partida Ambato --intereses natural gastronómico`
4. `uvicorn src.main:app --reload` y `POST /itinerario` en `http://127.0.0.1:8000/docs`:

```json
{"dias": 2, "presupuesto_usd": 150, "punto_partida": "Ambato", "intereses": ["natural", "gastronómico"], "notas": null}
```

**Reparto de responsabilidades** («el modelo propone, el código dispone»):
- El modelo recibe la petición y el catálogo y devuelve solo `id` de atractivos por día, con un motivo (JSON validado con esquema).
- El código descarta ids que no estén en el catálogo, quita repetidos, respeta la jornada máxima de 8 h, calcula costos (los `POR VERIFICAR` se excluyen y el total se marca parcial), adjunta la fuente del catálogo y advierte si se supera el presupuesto.
- Pedidos de reserva/pago, consejo médico o instrucciones dentro de `notas` se rechazan (`estado: "rechazado"`).
- Si Groq falla (429, timeout, respuesta vacía) se reintenta con espera exponencial; si no responde, el endpoint devuelve 503 con un mensaje claro. Cada llamada queda en `logs/llm.jsonl` (tokens y tiempo, sin texto del usuario).

Comparación de prompts: `python scripts/comparar_prompts.py` genera `docs/05-prompts.md` para calificar en grupo. Pruebas sin gastar API: `pytest -q`.

## Variables de entorno

Ver `.env.example`. Las claves reales no se versionan.

## Datos

- `data/catalogo/atractivos.csv` contiene 45 atractivos. Costos y coordenadas están marcados `POR VERIFICAR` y deben completarse con fuentes oficiales. Ver `data/catalogo/README.md`.
- `data/raw/` almacena los documentos descargados; está excluido de Git.

## Documentación

1. [Propuesta](docs/01-propuesta.md)
2. [Requisitos](docs/02-requisitos.md)
3. [Arquitectura](docs/03-arquitectura.md)
4. [Fuentes](docs/04-fuentes.md)
5. [Levantamiento](docs/levantamiento.md)
6. [Evidencias de la Semana 1](docs/evidencias/semana-1/README.md)

## Aviso

La información turística debe contrastarse con fuentes oficiales. El sistema no realiza reservas ni pagos ni emite recomendaciones médicas o de seguridad.
