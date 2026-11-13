# Catálogo de atractivos

| Archivo | Contenido | Quién lo usa |
|---|---|---|
| `atractivos.csv` | **Fuente de verdad**: 139 atractivos (130 con coordenadas) | El agente, el RAG (fichas del corpus), las pruebas |
| `atractivos_reducido.csv` | 60 atractivos **verificados por el equipo** (costos, duraciones, cantones y fuentes completos; 7 nov 2026). Son las mismas filas que en `atractivos.csv` | El prompt del itinerario (menos tokens) |
| `entrada/` | Archivos tal como los entregó el equipo, antes de importarlos (trazabilidad) | `scripts/importar_catalogo.py` |
| `atractivos_pruebas.csv` | Copia antigua; ningún código la usa | — |

Formato obligatorio: **UTF-8, separador coma, punto decimal**. `tests/test_catalogo_datos.py` lo comprueba en el CI, junto con
coordenadas dentro de la zona centro, valores válidos y que el reducido coincida con el completo.

## Columnas

| Columna | Descripción |
|---|---|
| nombre | Nombre del atractivo. De él sale el `id`: cambiarlo cambia el id (y hay que reconstruir el corpus) |
| canton | Cantón; `POR VERIFICAR` si abarca varios o no se confirmó |
| provincia | Tungurahua, Chimborazo, Cotopaxi o Bolívar |
| tipo | natural, cultural o gastronómico |
| costo_estimado | USD: número, rango (`2.00-2.50`), «desde 18.00» o `POR VERIFICAR`. Con varios números se usa el mayor |
| duracion_sugerida | Horas de visita |
| latitud, longitud | Grados decimales con **punto** (`-1.3982`, `-78.4186`) |
| fuente, url_fuente, tipo_fuente | Entidad, enlaces (separados por `\|`) y tipo de fuente |
| estado_verificacion | `A`, `A_parcial`, `B` o `C` (sin fuente verificada) |
| precision_coord | `verificada_fuente`, `sitio_aprox` o `localidad_aprox` |
| notas | Aclaraciones (cobros, estacionalidad, origen de las coordenadas) |

## Cómo editar sin dañar el catálogo

**No guarde el CSV directamente desde Excel.** Con la configuración regional de Ecuador, Excel lo guarda con `;`, en la
codificación de DOS y con los números alterados (`-1.3982` → `-13.982`), y corta los textos en cada `;`. Así pasó el 7 de
noviembre de 2026; si ese archivo hubiera reemplazado al catálogo, la API no habría arrancado.

1. Edite en Excel (o en Google Sheets) y guarde el archivo **en `data/catalogo/entrada/`**, con el nombre y la fecha.
2. Importe con el script, que corrige el formato, rearma las coordenadas, conserva los textos cortados y no deja que un
   campo vacío borre un dato:
   ```bash
   python scripts/importar_catalogo.py data/catalogo/entrada/ARCHIVO.csv --simular   # revisar el reporte
   python scripts/importar_catalogo.py data/catalogo/entrada/ARCHIVO.csv             # aplicar
   ```
   El reporte queda en `docs/evidencias/catalogo/`.
3. Corra `pytest -q` y reconstruya el RAG: `python scripts/construir_corpus.py` y `python scripts/ingestar_rag.py`.
4. En producción, suba el índice nuevo al VPS (`docs/08-despliegue-docker.md` §7).

`scripts/curar_catalogo.py` ya no sobrescribe el reducido (elegiría 4 atractivos sin verificar); use `--salida OTRO_ARCHIVO`
para comparar.
