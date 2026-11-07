# Semana 3 · Evaluación del RAG (Chroma + multilingual-e5-small)

Se evalúa con `scripts/evaluar_rag.py`; los resultados crudos están en `eval/resultados_rag.json`.

## 1. Recuperación (sin LLM)

8 solicitudes en las que el visitante nombra un atractivo en sus notas (tren, Quilotoa, Pailón, Chimborazo,
carnaval, hornado, Cotopaxi, Salasaca). El atractivo apareció recuperado en **8/8** con todas las combinaciones de
`top_k` (3, 5, 8, 12) y margen (0.02, 0.05, 0.10).

El margen solo cambia el tamaño del conjunto (con `top_k=12`): 1.6 atractivos con 0.02, 5.5 con 0.05 y 11.8 con 0.10.
Con 0.02 queda poca variedad para llenar los días; con 0.10 el margen no recorta y solo actúa `top_k`.
Se conserva `RAG_MARGEN_SIMILITUD=0.05`. La muestra es pequeña y de consultas fáciles (nombran el atractivo):
no mide el caso de intereses genéricos.

## 2. Itinerario con Groq, con y sin RAG (`eval/entradas_prompts.csv`)

Las 10 entradas, una vez por modo. La entrada 6 (4 días, 3 intereses) falló en AMBOS modos con
`ProveedorNoDisponible` (errores 400 de Groq y luego 429), así que los promedios son sobre las 9 restantes.

| Métrica (promedio, 9 entradas) | Sin RAG (v3) | Con RAG (v4) |
|---|---|---|
| Tokens de entrada | 2 763 | 2 672 (-3 %) |
| Tokens de salida | 464 | 668 (+44 %) |
| Latencia | 1 113 ms | 1 464 ms (+32 %) |
| Citas válidas / descartadas | 0 / 0 | 16 / 0 |
| Itinerarios con al menos una cita | 0 | 6 de 8 aceptados |
| Atractivos inventados | 0 | 0 |

- La entrada no crece como se estimó: el RAG acota el catálogo (24 candidatos) y compensa los fragmentos.
  El costo está en la salida (las citas) y en la latencia.
- Entrada 9 (reservar hotel): rechazada en ambos modos. Entrada 8 (Galápagos y Cuenca): con RAG se rechazó; sin RAG
  generó un itinerario. Entrada 10 (receta de pizza): ambos modos generaron itinerario, sin seguir la instrucción.
- Entrada 3 (1 día, cultural, Riobamba): con RAG salió 1 actividad contra 3 sin RAG. Está por revisar.

## 3. Hallazgos y correcciones

- **Citas fuera de tema** (prueba manual con Groq): un fragmento de prensa que lista varios atractivos se asignaba a
  todos los que nombraba. Corrección en `asignar`: se asigna solo al atractivo más nombrado y se descarta si hay empate.
  Costo: atractivos con fuente web 73 → 33 (fragmentos 303 → 241). Es una compensación entre precisión y cobertura.
- **Errores 400 de Groq** (modo estricto): ocurren con y sin RAG, no son causados por el RAG. Los reintentos los absorben
  casi siempre, pero consumen tokens y pueden agotar los intentos.

## 4. Límites

- La calidad de las citas se midió por validez de id, no revisando una muestra a mano. Falta esa revisión.
- 10 entradas, una corrida por modo: la variación del modelo no está medida.
- No se comparó `bge-m3` ni otro modelo de embeddings.

## 5. Piso de similitud (Entrega 3)

Antes, `buscar()` nunca decía «nada se parece»: una solicitud de Galápagos recibía igual los atractivos «más parecidos»
de la zona centro como candidatos prioritarios. Ahora hay un piso absoluto, además del margen. Se calibró con
`python scripts/evaluar_rag.py calibracion` (resultados en `eval/calibracion_piso.json`; detalle en `docs/07-rag.md` §9.1):

| Tipo de consulta | Zona (mín–máx) | Fuera (mín–máx) | Piso | Conserva zona | Corta fuera |
|---|---|---|---|---|---|
| Solicitud de itinerario | 0.832–0.930 | 0.806–0.858 | 0.83 | 21/21 | 6/14 |
| Pregunta concreta (agente) | 0.882–0.933 | 0.791–0.834 | 0.86 | 6/6 | 5/5 |

- En las solicitudes, los grupos **se solapan**: «natural» solo (0.838) puntúa igual que «playas de Galápagos» (0.839).
  El piso corta lo ajeno al turismo; los otros destinos los sigue rechazando el modelo (`fuera_de_alcance`).
- El recall de la sección 1 se mantiene en 8/8 con el piso activo.
