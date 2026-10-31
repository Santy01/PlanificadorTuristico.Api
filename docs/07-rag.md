# 07 · RAG: corpus, embeddings y base vectorial

Documento de la implementación de la semana 3. Describe qué se construyó, dónde está, cómo funciona y para qué sirve cada pieza.

## 1. Idea general

El planificador ya tenía un catálogo verificado de 139 atractivos (CSV) y un modelo de lenguaje (Groq) que propone el itinerario. El RAG (*Retrieval-Augmented Generation*) agrega **respaldo documental**: antes de pedir el itinerario, el sistema busca fragmentos de las fuentes que hablan de lo que el visitante pidió, se los entrega al modelo y el itinerario sale con **citas** a esas fuentes.

```
 OFFLINE (una vez)                                    EN CADA SOLICITUD
 ─────────────────                                    ─────────────────
 catálogo CSV ──► fichas ─┐                           solicitud ──► consulta (intereses + notas)
 URLs del catálogo ──► web/PDF ┤                                        │
                          ▼                                              ▼ embedding "query: …"
                  corpus + manifiesto                          Chroma (similitud coseno)
                          │ fragmentar                                   │ agrupar por atractivo + margen
                          │ asignar a atractivos                         ▼
                          │ embedding "passage: …"             atractivos + fragmentos recuperados
                          ▼                                              │
                  Chroma (data/vectorstore/)                             ▼
                                                      prompt v4: catálogo acotado + <fragmentos>
                                                                         │ Groq (esquema con `citas`)
                                                                         ▼
                                                 el CÓDIGO valida las citas y arma la respuesta
```

Principio rector, el mismo de todo el proyecto: **el modelo propone, el código dispone**. El modelo solo elige ids de fragmentos; la cita final (texto, URL, tipo de fuente) la construye el código a partir de lo que realmente se recuperó.

## 2. Corpus

**Qué es:** el conjunto de textos sobre los que se busca. Son dos clases:

| Clase | Origen | Para qué sirve |
|---|---|---|
| `ficha` | Una por atractivo (139), generada desde el catálogo; solo incluye datos verificados (no "POR VERIFICAR") | Que cada atractivo tenga al menos un texto buscable, aunque no tenga página web |
| `web` | Páginas y PDF citados en las URL del catálogo (33 documentos descargados correctamente) | Aportan contenido de fuente externa que se puede citar |

**Dónde:**
- Construcción: [scripts/construir_corpus.py](../scripts/construir_corpus.py)
- Manifiesto (versionado): [data/corpus/manifiesto.csv](../data/corpus/manifiesto.csv) — una fila por documento con `doc_id, clase, archivo, atractivo_ids, fuente, url, tipo_fuente, estado_verificacion, fecha_descarga, estado, caracteres`
- Textos crudos: `data/raw/fichas/` y `data/raw/web/` (no versionados, se regeneran con el script)

**Cómo funciona el script:** genera las fichas, descarga las URL del catálogo, convierte HTML a texto (con `HTMLParser`) y PDF a texto (con `pypdf`), y escribe el manifiesto. Omite dominios comerciales (5 URL), una lista de páginas irrelevantes (1) y todo texto de menos de 400 caracteres. Resultado: 178 filas en el manifiesto.

**Por qué un manifiesto:** deja trazabilidad de cada texto (de dónde viene, cuándo se descargó, qué tan oficial es) y es lo que permite que una cita diga su fuente y su nivel de verificación.

## 3. Fragmentación y asignación a atractivos

**Dónde:** [src/services/indice.py](../src/services/indice.py), funciones `fragmentar`, `asignar`, `menciones`, `nombra_a`, `construir_registros`.

**Fragmentar:** las páginas se cortan en trozos de hasta 1 200 caracteres con solape de 150, para que cada trozo sea una unidad de sentido y no se pierda contexto en los cortes. Las fichas no se cortan.

**Asignar:** un fragmento solo es útil si se sabe de qué atractivo habla.
- Página de **un solo atractivo**: todos sus fragmentos son de ese atractivo.
- Página de **varios atractivos** (por ejemplo una nota de prensa): el fragmento se asigna al atractivo que **más veces se nombra**. Para contar, deben aparecer todas las palabras distintivas del nombre (sin tildes ni mayúsculas, ignorando genéricas como «cascada» o «parque»). Si dos atractivos empatan, o ninguno se nombra, el fragmento se **descarta**.

**Por qué esta regla:** una prueba con el modelo real mostró que un fragmento sobre la Nariz del Diablo se citaba para Nizag y para unas cascadas, solo porque los nombraba de pasada. Es preferible perder cobertura (hoy 33 de 139 atractivos tienen fuente web) a respaldar con un texto que no corresponde.

**Resultado actual:** 241 fragmentos indexados (139 de fichas y 102 web).

## 4. Embeddings

**Qué son:** vectores numéricos que representan el significado de un texto; textos de significado parecido quedan cerca. Permiten buscar por sentido, no por palabras exactas (por ejemplo «cascada» encuentra «caída de agua»).

**Modelo:** `intfloat/multilingual-e5-small`, local, mediante `sentence-transformers`. Se eligió porque funciona bien en español, es pequeño (corre en CPU sin costo ni cuota) y no envía datos a terceros.

**Cómo se usa** (en `vectorizar`, [src/services/indice.py](../src/services/indice.py)):
- Los fragmentos se vectorizan con el prefijo `passage: ` y la consulta con `query: `; el modelo E5 lo exige para dar buenos resultados.
- Los vectores se normalizan, de modo que la similitud coseno se calcula como producto punto.
- Lo que se vectoriza es `"{nombre} ({provincia}): {fragmento}"`, para que el vector conozca de qué atractivo habla el texto; lo que se guarda y se cita es el fragmento original.

**Dato práctico:** con E5 las similitudes salen muy juntas (0.80–0.90), por lo que un umbral absoluto no sirve. Se usa un **margen respecto al mejor resultado** (sección 6).

## 5. Base vectorial (Chroma)

**Qué es:** la base de datos donde se guardan los vectores y se buscan los más cercanos a una consulta.

**Por qué Chroma:** funciona embebida (un directorio local, sin servidor), es gratuita y alcanza para unos cientos de fragmentos. Decisión registrada en [docs/03-arquitectura.md](03-arquitectura.md).

**Dónde y cómo:**
- Ingesta: [scripts/ingestar_rag.py](../scripts/ingestar_rag.py) lee el manifiesto, construye los registros, vectoriza y **reconstruye** la colección completa (la borra y la crea; así nunca quedan fragmentos viejos). Tiene un modo `--simular` para probar sin cargar el modelo.
- Almacén: `data/vectorstore/` (no versionado; quien clone el repositorio debe ejecutar `python scripts/ingestar_rag.py`).
- Colección `atractivos`, métrica coseno.
- Metadatos por fragmento: `atractivo_id, nombre, provincia, tipo, doc_id, clase, fuente, url, tipo_fuente, estado_verificacion, fecha`. Sirven para filtrar (por tipo de atractivo) y para armar la cita.

## 6. Recuperación

**Dónde:** [src/services/rag.py](../src/services/rag.py), clase `ClienteRAG`.

**Cómo funciona `recuperar`:**
1. La consulta es la concatenación de los **intereses y las notas** del visitante (el punto de partida y el presupuesto no dicen qué quiere ver).
2. Se filtra por tipo de atractivo (natural, cultural, gastronómico) según los intereses.
3. Se buscan los `top_k × 4` fragmentos más cercanos y se descarta cualquier id que no esté en el catálogo verificado.
4. Se **agrupa por atractivo** (máximo 2 fragmentos por atractivo). Sin esto, un volcán con tres fragmentos parecidos ocupaba todos los lugares y desplazaba al tren de la Nariz del Diablo.
5. Se conservan los atractivos cuya similitud está a menos de `margen` (0.05) del mejor, hasta `top_k` (12).

**Regla de oro:** `recuperar` **nunca lanza excepciones**. Si falta el índice, no carga el modelo o falla Chroma, devuelve «no disponible» y el itinerario se genera como antes, con una advertencia.

**Configuración** (en `.env`, plantilla en [.env.example](../.env.example)):

| Variable | Valor por defecto | Efecto |
|---|---|---|
| `RAG_ACTIVO` | `true` | `false` desactiva todo el RAG |
| `VECTOR_DB_PATH` | `data/vectorstore` | Ubicación del índice |
| `VECTOR_DB_COLECCION` | `atractivos` | Nombre de la colección |
| `EMBEDDING_MODEL` | `intfloat/multilingual-e5-small` | Modelo de embeddings |
| `RAG_TOP_K` | `12` | Máximo de atractivos recuperados |
| `RAG_MARGEN_SIMILITUD` | `0.05` | Margen respecto al mejor resultado |

## 7. Integración en el itinerario

**Dónde:** [src/services/itinerario.py](../src/services/itinerario.py), [src/schemas.py](../src/schemas.py), [src/prompts/system_v4.md](../src/prompts/system_v4.md), [src/main.py](../src/main.py).

- **Catálogo acotado:** con RAG, el modelo recibe unos 24 candidatos (`max(24, 6 × días)`): primero los recuperados y luego un relleno intercalado por provincia, para no dejarlo sin variedad. Esto reduce los tokens de entrada.
- **Fragmentos en el prompt:** hasta 5 fragmentos web (el mejor de cada atractivo), de 350 caracteres, con ids `f1…f5`, dentro de un bloque `<fragmentos>`.
- **Prompt v4:** el v3 más reglas de citas. Indica que cada atractivo lista en `citas` los ids de los fragmentos que respaldan su motivo, que solo puede citar fragmentos de ese mismo atractivo, y que `citas = []` es normal.
- **Esquema:** `ItinerarioConCitas` (con `citas` obligatorio, por el modo estricto de Groq). El flujo sin RAG usa el esquema anterior sin cambios.
- **Validación en código (`_citas_validas`):** una cita se acepta solo si el id existe entre los fragmentos enviados **y** pertenece al mismo atractivo. Las demás se descartan y se agrega una advertencia.
- **Respuesta:** cada actividad trae `citas`, con `fragmento_id, texto, fuente, url, tipo_fuente, estado_verificacion`. Documentado en [docs/06-guia-frontend.md](06-guia-frontend.md).
- **Arranque:** `obtener_rag()` en `main.py` entrega el cliente (o `None` si `RAG_ACTIVO` es falso o no hay índice) y el modelo se precarga al iniciar la API, para que la primera solicitud no pague la carga.

## 8. Seguridad y degradación

- **Inyección de instrucciones:** los fragmentos son texto de páginas web. Se les quitan `<` y `>`, se pasan a una sola línea, se truncan y van dentro de `<fragmentos>`; el prompt v4 los declara **datos**, no órdenes.
- **Nada fuera del catálogo:** los ids recuperados que no estén en el catálogo se descartan.
- **Sin RAG todo sigue igual:** índice ausente, modelo no cargado, Chroma caído o `RAG_ACTIVO=false` producen el mismo itinerario de antes; si el RAG estaba configurado, se agrega la advertencia «No se pudieron consultar las fuentes de apoyo: el itinerario no incluye citas.»

## 9. Pruebas y evaluación

| Qué | Dónde | Resultado |
|---|---|---|
| Pruebas unitarias | [tests/test_indice.py](../tests/test_indice.py), [tests/test_rag.py](../tests/test_rag.py), [tests/test_itinerario_rag.py](../tests/test_itinerario_rag.py) | 104 pruebas en total pasan (con modelo y Chroma simulados) |
| Evaluación | [scripts/evaluar_rag.py](../scripts/evaluar_rag.py), [docs/evidencias/semana-3/README.md](evidencias/semana-3/README.md) | Recall 8/8 en recuperación; con Groq 16 citas válidas y 0 descartadas |

Las pruebas no cargan el modelo ni el índice real: `tests/conftest.py` los reemplaza por un RAG nulo.

## 10. Resumen: para qué sirve cada pieza

| Pieza | Dónde | Para qué sirve |
|---|---|---|
| Fichas | `scripts/construir_corpus.py` | Que todo atractivo tenga un texto buscable |
| Páginas web/PDF | ídem | Contenido de fuentes externas citable |
| Manifiesto | `data/corpus/manifiesto.csv` | Trazabilidad: origen, fecha y nivel de verificación de cada texto |
| Fragmentación y asignación | `src/services/indice.py` | Trozos del tamaño adecuado, atribuidos al atractivo correcto |
| Embeddings (E5-small) | `src/services/indice.py` | Buscar por significado, local y sin costo |
| Chroma | `data/vectorstore/`, `scripts/ingestar_rag.py` | Guardar los vectores y encontrar los más cercanos |
| Recuperación | `src/services/rag.py` | Elegir atractivos y fragmentos pertinentes a lo que pide el visitante |
| Prompt v4 y esquema con citas | `src/prompts/system_v4.md`, `src/schemas.py` | Que el modelo use los fragmentos y señale cuáles respaldan cada atractivo |
| Validación de citas | `src/services/itinerario.py` | Que ninguna cita sea inventada ni pertenezca a otro atractivo |
| Degradación controlada | `rag.py`, `itinerario.py`, `main.py` | Que el RAG sea un extra y nunca haga fallar la solicitud |

## 11. Limitaciones conocidas

- Solo 33 de 139 atractivos tienen fuente web citable; el resto cita solo su ficha (que el prompt no ofrece como cita) o no tiene citas.
- La calidad de las citas se midió por validez de id; falta revisión manual de una muestra del corpus y de las citas.
- Una sola corrida por modo con 10 entradas; la variación del modelo no está medida.
- La entrada de 4 días y 3 intereses falló por errores de Groq (400 y 429) con y sin RAG.
- No se comparó `bge-m3` ni otros modelos de embeddings.
