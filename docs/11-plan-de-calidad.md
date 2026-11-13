# Plan de calidad

**Versión:** 1.0 (Entrega 3, noviembre de 2026)

Regla del plan: **si no se mide, no se puede defender.** Cada parte del sistema tiene métricas, un umbral, un comando
que las produce y un lugar donde queda la evidencia. Lo esperado de cada caso de evaluación se escribe **antes** de
correrlo.

## 1. Qué se mide

| Parte | Métrica | Umbral | Último resultado | Cómo se mide |
|---|---|---|---|---|
| **RAG** | Acierto: la fuente esperada está entre los fragmentos devueltos | ≥ 70 % | 100 % (11/11) | `python eval/evaluar.py rag` |
| | Silencio correcto: preguntas sin respuesta en el corpus vuelven vacías | ≥ 90 % | 100 % (4/4) | ídem |
| | Recall de atractivos nombrados en la solicitud | 8/8 | 8/8 | `python scripts/evaluar_rag.py recuperacion` |
| | Citas válidas (id enviado y del mismo atractivo) | 100 % | 100 %: las inválidas se descartan en código | `_citas_validas` + `tests/test_itinerario_rag.py` |
| **Flujo** (itinerario) | Solicitudes que cumplen lo esperado | ≥ 13/15 | 14/15 (+1 corrida aparte) | `python eval/evaluar.py solicitudes --pausa 45` |
| | Adversarias rechazadas: reserva, médico, inyección, fuera de zona (RNF-07) | 100 % | 4/4 | ídem + `tests/test_alcance.py` |
| | Atractivos inventados (RNF-06) | 0 | 0 | ídem |
| | Errores silenciosos: una solicitud sin estado final | 0 | 0: toda respuesta es `ok`, `rechazado` o `revision_humana` | ídem |
| **Agente** | Tareas cumplidas (escenario A) | 100 % | 5/5 | `python eval/evaluar.py agente --pausa 40` |
| | Rechazos correctos fuera de la lista (escenario B) | 100 % | 3/3 | ídem |
| | Confirmación correcta (escenario D) | 100 % | 2/2 | ídem |
| | Vueltas frente al tope (escenario C) | máximo < 6 | media 1.6, máximo 3 | ídem; el tope se prueba en `tests/test_agente.py` |
| | Respuestas con datos sin respaldo | 0 | 0 | campo `advertencias` |
| **Software** | Pruebas unitarias y de integración | 100 % pasan | 234 pasan | `pytest -q` (en CI) |
| | Cobertura de `src/` (RNF-14 pide ≥ 70 % en lógica) | ≥ 85 % (falla el build) | 95 % | `pytest --cov=src` (en CI) |
| | Secretos en el repositorio (RNF-12) | 0 | 0 | Gitleaks en CI, con el historial completo |
| | La imagen Docker se construye | sí | sí | job `imagen` en CI |
| **Costo** | Tokens por conversación del agente | informativo | ~2 400 por caso | `logs/agente.jsonl`, `eval/resultados_agente.json` |
| | Tokens por itinerario | informativo | ~2 700 de entrada con RAG | `logs/llm.jsonl` |

## 2. Conjuntos de evaluación

| Archivo | Casos | Qué cubre |
|---|---|---|
| `eval/preguntas.jsonl` | 15 (4 sin respuesta) | Recuperación: atractivos con fuente web y con ficha; fuera de la zona, médico |
| `eval/solicitudes.jsonl` | 15 | Intereses genéricos sin nombres, presupuestos bajos, atractivo nombrado, salida desde fuera de la zona, 4 adversarias, 1 y 4 días |
| `eval/agente_casos.jsonl` | 10 | Escenarios A (libre y termina), B (fuera de la lista e inyección) y D (confirmación; correo ausente) |
| `eval/entradas_prompts.csv` | 10 | Comparación de prompts y con y sin RAG (semanas 2 y 3) |

Cada revisión de `eval/evaluar.py` tiene su propia prueba (`tests/test_evaluar.py`): si una revisión estuviera mal,
el número no valdría nada.

## 3. Cuándo se corre

| Momento | Qué se corre |
|---|---|
| Cada push y pull request a `develop` o `master` | CI: Gitleaks, `pytest` con cobertura (mínimo 85 %), construcción de la imagen |
| Al cambiar un prompt, el modelo, el corpus o el modelo de embeddings | `eval/evaluar.py rag`, `solicitudes` y `agente`, comparados con `eval/resultados_*.json` |
| Al reindexar el corpus o cambiar el modelo de embeddings | `scripts/evaluar_rag.py calibracion`, para recalibrar los pisos de similitud |
| Antes de una entrega | Todo lo anterior y actualizar [evidencias/](evidencias/) |

**Por qué la evaluación con modelo no corre en CI:** necesita la clave de Groq (gasta cuota del plan gratuito) y el modelo
de embeddings, que CI no instala para no descargar torch. Las pruebas de `pytest` usan dobles del modelo, del RAG y del
clima, y sí corren en CI.

## 4. Lo que el plan todavía no cubre

- **Variación del modelo:** una corrida por caso. Correr 3 por caso mediría cuánto cambia la respuesta.
- **Calidad del texto:** la verificación del agente revisa horas y montos, no afirmaciones en texto libre. Las citas se
  validan por id, no con una revisión manual de una muestra.
- **Latencia (RNF-01):** se registra por solicitud (unos 1–1.5 s con Groq, hasta 13 s con reintentos), pero no se hizo la
  prueba de carga con 50 consultas.
- **Accesibilidad (RNF-09):** corresponde al frontend y no está auditada.
- **Lint y revisión de dependencias:** no hay `ruff` ni auditoría de dependencias en CI.
