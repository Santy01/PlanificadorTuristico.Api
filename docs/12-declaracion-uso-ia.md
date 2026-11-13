# Declaración de uso de IA y aportes del grupo

*Grupo 4 · Planificador turístico de la zona centro del Ecuador · Seminario «Ingeniería de Software con IA Generativa» · UNIANDES 2026*

Este documento declara qué se generó con IA en el desarrollo, cómo se revisó, qué lo respalda y qué aportó cada
integrante. La IA que usa el producto en ejecución (Groq y Gemini) se declara aparte, en el «Aviso sobre IA y datos» del
[README](../README.md).

## 1. Qué se generó con IA

- **Código del backend y del frontend**, con un asistente de programación con IA (Claude Code), a partir de las
  historias de usuario y de las decisiones del equipo.
- **Pruebas, scripts de evaluación y documentación** (incluida la presentación de la sustentación).
- **Lo que decidió y verificó el equipo, no la IA:** el alcance del producto (qué entra y qué queda fuera), las
  prioridades, los **datos del catálogo** (los 60 atractivos verificados con sus costos, duraciones y fuentes), las
  fuentes del corpus del RAG, los umbrales del RAG y su recalibración, la plataforma de despliegue y qué se acepta de lo
  que la IA propone.

## 2. Cómo se revisó

- **Pull requests por tarea** (ramas `feature/NN-nombre` desde `develop`) con el pipeline obligatorio: Gitleaks, pruebas
  y construcción de la imagen.
- **Evaluación con lo esperado escrito antes de correr** (`eval/`: 15 preguntas, 15 solicitudes y 10 casos del agente),
  con línea base y comparación contra producción
  ([semana 3](evidencias/semana-3/evaluacion-entrega3.md) y [producción](evidencias/semana-4/evaluacion-produccion.md)).
- **Pruebas contra el modelo real y contra la URL desplegada** (`tests/smoke.py`, 23 casos:
  [docs/08-pruebas.md](08-pruebas.md)).
- **Gitleaks** en cada push y pull request, sobre todo el historial.
- **Criterio:** nada generado se acepta sin una prueba que lo respalde; cuando una prueba falla se corrige el código, no
  la prueba (salvo que la prueba estuviera mal, y entonces se documenta).

## 3. Qué lo respalda y qué se corrigió

- **234 pruebas** en la API, con 95 % de cobertura (el CI falla por debajo del 85 %), y 37 en el frontend.
- Fallas que la revisión encontró en lo generado y que quedaron cubiertas con una prueba, por ejemplo:
  - el estado del agente permitía **confirmar dos veces** la misma acción: ahora cada id se decide una sola vez, y
    `tests/smoke.py` lo comprueba contra la URL (segundo intento → 404);
  - el modelo aceptó 4 de 4 solicitudes fuera de alcance aunque el prompt le pedía rechazarlas: se agregó la **regla de
    alcance en código** (`config/alcance.yaml`), que rechaza sin llamar al modelo;
  - el respaldo con Gemini fallaba a mitad de una conversación del agente (firma de pensamiento): corregido con prueba
    ([semana 4 §5](evidencias/semana-4/README.md));
  - el agente con el catálogo reducido no encontraba atractivos que sí existían: ahora usa el catálogo completo;
  - el mensaje de un valor ficticio con forma de clave se detectó con Gitleaks: se cambió el texto de la prueba.
- Las limitaciones que quedan están en «Lo que NO hace todavía» del [README](../README.md).

## 4. Aportes de cada integrante

Según el historial de git del repositorio de la API (`git shortlog -sn --all`) y el trabajo no versionado que se detalla
abajo. El frontend (`PlanificadorTuristico.Web`) tiene su propio historial.

| Integrante (GitHub) | Aportes en este repositorio |
|---|---|
| **Santy01** | Estructura base y esquemas Pydantic; API FastAPI (`/health`, `/itinerario`, `/itinerario/stream`); servicio de índice vectorial y de recuperación del RAG con agrupación por atractivo; integración del RAG con citas validadas por el código; piso de similitud; llamadas con herramientas en `ClienteLLM`; evaluación de la Entrega 3 y sus resultados; `/health` avanzado y límite por IP; pruebas funcionales de humo contra la URL; presentación de la sustentación; versión 0.4.1 |
| **kleber212023** | Configuración del modelo, prompts y cliente con reintentos; servicio de generación y armado del itinerario; corpus e ingesta del RAG; agente de alcance controlado; regla de alcance en código; parámetros de negocio en `config/`; Dockerfile, Traefik y pipeline CI/CD con Gitleaks y cobertura; despliegue a mismo dominio; matriz de riesgos, ADR-0003 y guía de despliegue; importación segura del catálogo |
| **CesarVasquez1985** | Catálogo de atractivos y servicio de clima (Open-Meteo); suite de pruebas (LLM, clima, itinerario, integración simulada, RAG); herramientas del agente (`recalcular`, `buscar_fragmentos`, `consultar_clima`, `enviar_itinerario`); Gemini como proveedor de respaldo y su corrección a mitad de conversación; catálogo verificado de 60 atractivos; arquitectura y requisitos; versión 0.4.2; presentación con despliegue, QA y credenciales |

**Trabajo del grupo que no aparece como commit:** la verificación manual de los datos del catálogo (costos, duraciones y
fuentes de los 60 atractivos), la elección de las fuentes del corpus y la sustentación oral.

## 5. Llave de despliegue: qué se rotó y qué no

Las diapositivas decían «1 llave rotada» y la evidencia de la semana 4 decía que no hizo falta rotar ninguna. Eran dos
hechos distintos:

| Hecho | ¿Se rotó? | Qué se hizo |
|---|---|---|
| **Valor ficticio detectado por Gitleaks** en `tests/test_llm.py` (el texto `gsk-…` que una prueba usa para comprobar que `/health` no muestra la clave) | **No.** No era una clave real | El commit no se había publicado: se reescribió localmente con `"valor-ficticio"`. El historial de GitHub nunca lo tuvo. Detalle en [semana 4 §1](evidencias/semana-4/README.md) |
| **Llave SSH de despliegue** que quedó expuesta | **Sí, 1** | Se generó otra **antes de usarla**; el despliegue de la 0.4.0 se hizo con la llave nueva (semana 4 §5). Cada repositorio tiene su propia llave, solo para desplegar, y la huella del servidor se verifica (`known_hosts`) |

Las claves de los proveedores (Groq, Gemini) viven en el `.env` del servidor y las del pipeline en GitHub Secrets;
Gitleaks no encuentra ninguna clave en el historial (0 hallazgos sobre 75 commits en la semana 4, y en cada push desde
entonces). Si una clave real llegara a exponerse, se rota de inmediato: ver «Cambiar o rotar una clave» en
[08-despliegue-docker.md](08-despliegue-docker.md).
