# Importación de reducido_verificado_2026-11-07.csv

Fecha: 2026-11-07 · codificación detectada: **cp850** · separador: «;» · 60 filas.

Reglas: ver la cabecera de `scripts/importar_catalogo.py`.

## Resultado

| Campo | Por verificar en estas filas |
|---|---|
| costo_estimado | 0 |
| duracion_sugerida | 0 |
| canton | 0 |
| latitud | 0 |
| url_fuente | 0 |

Filas aplicadas al catálogo: **60**. Sin coincidencia por nombre: ninguna.

## Decisiones y cambios de datos conocidos

- **Volcán Chimborazo (Reserva de Producción de Fauna Chimborazo)**
  - costo_estimado: «0» → «10.00»
- **Parque Nacional Sangay**
  - costo_estimado: «0» → «7.00»
- **Parque Nacional Cotopaxi**
  - costo_estimado: «0» → «10.00-12.00»
- **Parque Nacional Llanganates (acceso por Píllaro)**
  - costo_estimado: «0» → «0 espacio público»
- **Centro Histórico de Latacunga (Rincón Mágico)**
  - coordenadas corregidas: (-0.9318, -78.6158) → (-0.934, -78.614)
  - duracion_sugerida: «4» → «1»
  - fuente: «MINTUR / GAD Municipal de Latacunga» → «GAD Municipal de Salcedo»
  - url_fuente: «https://primicias.ec/noticias/sociedad/latacunga-c» → «https://www.extra.ec/noticia/ecuador/conozca-encan»
  - tipo_fuente vacío en el archivo: se conserva «prensa (cita fuente oficial)»
  - estado_verificacion vacío en el archivo: se conserva «A_parcial»
  - precision_coord vacío en el archivo: se conserva «localidad_aprox»
  - notas vacío en el archivo: se conserva «Sexto Rincón Mágico (nov 2023); 21 atractivos; 39 establecim»
- **Plaza 15 de Mayo (Guaranda)**
  - coordenadas corregidas: (-1.5889, -79.0008) → (-1.588, -79)
  - duracion_sugerida: «0.5» → «1»
  - precision_coord: «sitio_aprox» → «localidad_aprox»
  - notas: «Atractivo del Centro Histórico (Rincón Mágico) Coo» → «Atractivo del Centro Histórico (Rincón Mágico)»

## Después de importar

- **Formato:** el archivo entregado venía en CP850, con «;» y coordenadas alteradas (`-1.3982` → `-13.982`). Como
  estaba, la API no habría arrancado. La importación lo dejó en UTF-8 con comas; `tests/test_catalogo_datos.py` (18
  validaciones) lo vigila en el CI y rechaza el archivo original.
- **Catálogos:** las 60 filas se aplicaron a `atractivos.csv` (fuente de verdad: agente y RAG) y a
  `atractivos_reducido.csv` (prompt del itinerario). Costos por verificar en el reducido: 44 → **0**.
- **Corpus e índice:** 184 documentos (antes 178; 6 páginas web nuevas, una con 404 y una sin texto suficiente) y
  **251 fragmentos** (antes 241); atractivos con fuente web citable: 33 → 35.
- **RAG:** 100 % de acierto y 100 % de silencio con las 15 preguntas; recall 8/8. Piso para preguntas sin cambios
  (6/6 y 5/5); para solicitudes 20/21 de la zona (detalle en `docs/07-rag.md` §9.1).
- **Costos reales en los itinerarios:** con los precios verificados los totales suben (en la evaluación: S01 de USD 9 a
  32, S02 de 20 a 29, S04 de 8 a 16.50).
- **Pendiente:** volver a correr `eval/evaluar.py solicitudes` y `agente`. El 7 de noviembre se agotó la cuota DIARIA
  de Groq (pedía esperar 10–12 minutos) y la de Gemini, por la cantidad de pruebas del día; 7 de 15 solicitudes
  respondieron 503 (comportamiento correcto). Los resultados vigentes en `eval/` siguen siendo los de la Semana 4.
