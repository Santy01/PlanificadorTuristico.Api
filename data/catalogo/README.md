# Catálogo inicial de atractivos

Archivo: `atractivos.csv` (UTF-8, separador coma, 45 atractivos).

## Columnas

| Columna | Descripción |
|---|---|
| nombre | Nombre del atractivo |
| canton | Cantón; `POR VERIFICAR` si el atractivo abarca varios o no se confirmó |
| provincia | Tungurahua, Chimborazo, Cotopaxi o Bolívar |
| tipo | natural, gastronómico o cultural |
| costo_estimado | Costo en USD con fuente y fecha. **Todos `POR VERIFICAR`** |
| duracion_sugerida | Horas. **Supuesto de planificación del equipo**, no dato oficial; validar |
| latitud, longitud | Grados decimales. **Todos `POR VERIFICAR`** |
| fuente | Entidad responsable y URL por confirmar |

## Criterio

Los nombres y la ubicación provincial se incluyen por conocimiento general; los cantones marcados deben confirmarse. Costos, coordenadas y URLs **no se completaron** para no inventar datos.

## Cómo verificar

1. Costos: sitio oficial del GAD o Ministerio de Turismo, o llamada al administrador del sitio; registrar fecha.
2. Coordenadas: ficha oficial del atractivo o contraste con OpenStreetMap; verificar con una segunda fuente.
3. Eventos (fiestas): registrar fecha del año vigente.
4. Actualizar la columna `fuente` con la URL final.
