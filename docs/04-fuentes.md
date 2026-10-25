# Inventario de fuentes

**Versión:** 0.1 (Semana 1)

> **Advertencia:** este inventario fue elaborado **sin acceso verificado a los sitios**. Ninguna URL ni vigencia se ha confirmado. Los dominios son los esperables de cada institución; **toda fila marcada `VERIFICAR` debe revisarse manualmente** antes de ingerirse al RAG. Registrar fecha de descarga y responsable en `docs/evidencias/semana-1/README.md`.

## 1. Inventario

| ID | Documento / recurso | Origen oficial | URL (dominio esperado) | Vigencia | Formato | Fragmentación prevista para RAG | Estado |
|---|---|---|---|---|---|---|---|
| F01 | Catastro / registro de atractivos turísticos | Ministerio de Turismo del Ecuador | turismo.gob.ec (ruta exacta por confirmar) | POR VERIFICAR | Por confirmar (HTML, PDF o datos abiertos) | Un fragmento por atractivo; metadatos: nombre, cantón, provincia, fecha | VERIFICAR |
| F02 | Datos abiertos de turismo / estadísticas de visitantes | Ministerio de Turismo | turismo.gob.ec (sección de cifras, por confirmar) | POR VERIFICAR | Por confirmar (XLSX, CSV, PDF) | Tablas no vectorizadas; se usan como datos estructurados | VERIFICAR |
| F03 | Portal turístico del GAD Provincial de Tungurahua | GAD Provincial de Tungurahua | tungurahua.gob.ec (por confirmar) | POR VERIFICAR | HTML / PDF | Por sección y atractivo, 300–500 tokens con solape 10–15 % | VERIFICAR |
| F04 | Portal turístico del GAD Provincial de Chimborazo | GAD Provincial de Chimborazo | chimborazo.gob.ec (por confirmar) | POR VERIFICAR | HTML / PDF | Ídem | VERIFICAR |
| F05 | Portal turístico del GAD Provincial de Cotopaxi | GAD Provincial de Cotopaxi | cotopaxi.gob.ec (por confirmar) | POR VERIFICAR | HTML / PDF | Ídem | VERIFICAR |
| F06 | Portal turístico del GAD Provincial de Bolívar | GAD Provincial de Bolívar | Por confirmar | POR VERIFICAR | HTML / PDF | Ídem | VERIFICAR |
| F07 | Sitios de GAD municipales (Baños, Ambato, Riobamba, Latacunga, Guaranda, Alausí, Pujilí, Saquisilí, etc.) | GAD cantonales | Por confirmar uno a uno | POR VERIFICAR | HTML / PDF | Por atractivo o evento; incluir fecha del evento | VERIFICAR |
| F08 | Planes de Desarrollo Turístico / PDOT provinciales y cantonales | GAD correspondientes / SENPLADES-Planifica Ecuador | Por confirmar | POR VERIFICAR (fecha del plan) | PDF extenso | Por capítulo y título; descartar secciones no turísticas | VERIFICAR |
| F09 | Áreas protegidas: Parque Nacional Cotopaxi, Sangay, Reserva de Producción de Fauna Chimborazo, Reserva Ecológica Los Ilinizas, Parque Nacional Llanganates | Ministerio del Ambiente, Agua y Transición Ecológica (denominación a verificar) | ambiente.gob.ec (por confirmar) | POR VERIFICAR | HTML / PDF | Por área; reglas de visita, accesos y horarios como metadatos | VERIFICAR |
| F10 | Estado de actividad volcánica (Tungurahua, Cotopaxi, Chimborazo) | Instituto Geofísico de la Escuela Politécnica Nacional (IGEPN) | igepn.edu.ec | Dinámica (tiempo real) | HTML / boletines | **No indexar en RAG**: se muestra solo como enlace oficial por seguridad | VERIFICAR |
| F11 | Alertas y gestión de riesgos | Servicio Nacional de Gestión de Riesgos y Emergencias (SNGRE) | Por confirmar | Dinámica | HTML | **No indexar**: enlace oficial | VERIFICAR |
| F12 | Estado de vías | Ministerio de Transporte y Obras Públicas / ECU 911 | Por confirmar | Dinámica | HTML / redes | **No indexar**: enlace oficial | VERIFICAR |
| F13 | Pronóstico meteorológico oficial | INAMHI (o entidad sucesora; verificar) | inamhi.gob.ec (por confirmar) | Dinámica | HTML / posible API | Solo consulta; no indexar | VERIFICAR |
| F14 | API de pronóstico (comercial o abierta) | Proveedor por seleccionar (p. ej., Open-Meteo, OpenWeatherMap) | Documentación del proveedor | Tiempo real | API JSON | No aplica: herramienta; cachear con TTL | VERIFICAR términos y límites |
| F15 | Cartografía y rutas | OpenStreetMap y servicios de rutas basados en él | openstreetmap.org | Continua | API / teselas | No aplica: herramienta; respetar atribución y políticas de uso | VERIFICAR |
| F16 | Tren Ecuador: rutas, horarios y tarifas (p. ej., Nariz del Diablo) | Ferrocarriles del Ecuador EP / Tren Ecuador | Por confirmar | POR VERIFICAR | HTML / PDF | Un fragmento por ruta; tarifas como dato estructurado con fecha | VERIFICAR |
| F17 | Calendario de fiestas y eventos (Mama Negra, Carnaval de Guaranda, Fiesta de las Flores y las Frutas, Diablada Pillareña) | GAD cantonales / Ministerio de Cultura y Patrimonio | Por confirmar | POR VERIFICAR (cambian por año) | HTML / PDF | Un fragmento por evento con fecha y año | VERIFICAR |
| F18 | Patrimonio cultural inmaterial / inventario patrimonial | Instituto Nacional de Patrimonio Cultural (INPC) | patrimoniocultural.gob.ec (por confirmar) | POR VERIFICAR | HTML / PDF | Por ficha de patrimonio | VERIFICAR |
| F19 | Información demográfica y territorial (cantones y parroquias) | INEC | inec.gob.ec | POR VERIFICAR | XLSX / CSV / PDF | Datos estructurados; no vectorizar | VERIFICAR |
| F20 | Gastronomía típica: fichas oficiales o publicaciones institucionales | Ministerio de Turismo / GAD / INPC | Por confirmar | POR VERIFICAR | HTML / PDF | Por plato o producto | VERIFICAR |
| F21 | Ley Orgánica de Protección de Datos Personales | Asamblea Nacional / Registro Oficial | Por confirmar | Verificar texto y reformas vigentes | PDF | No se indexa; referencia legal del proyecto | VERIFICAR |
| F22 | Entrevistas y encuestas propias | Levantamiento del estudiante | `docs/levantamiento.md` | Según fecha de aplicación | Tablas / transcripciones | Anonimizar; no mezclar con fuentes oficiales | Propia |

## 2. Fuentes que deben verificarse manualmente

**Todas las filas con estado `VERIFICAR`.** En especial:

1. **URLs exactas** de F01–F09, F16–F18: confirmar que existen, son oficiales y accesibles.
2. **Vigencia y fecha de publicación** de cada documento.
3. **Costos, horarios y tarifas** (F09, F16, F17): cambian con frecuencia; no deben usarse sin fecha.
4. **Nombres institucionales actuales:** varias entidades cambiaron de nombre o fueron fusionadas; confirmar denominación vigente.
5. **Términos de uso y licencia** de F14 y F15 (límites de peticiones, atribución, uso comercial).
6. **Disponibilidad de datos abiertos** de F01/F02 (podrían existir en formato estructurado).

### Procedimiento sugerido de verificación

1. Abrir el sitio oficial desde un buscador y desde la ruta institucional.
2. Registrar en la evidencia: URL final, fecha de acceso, captura y responsable.
3. Descargar a `data/raw/<id>/` con la fecha en el nombre del archivo.
4. Contrastar al menos un dato clave (p. ej., costo de entrada) con una segunda fuente oficial o por llamada al GAD.
5. Actualizar este inventario: cambiar el estado a `Verificada` y completar vigencia.

## 3. Estrategia de fragmentación (propuesta)

- Tamaño inicial: 300–500 tokens con solape de 10–15 %, ajustable tras evaluación.
- Dividir primero por estructura (títulos, atractivos) y luego por tamaño.
- Metadatos obligatorios: `fuente_id`, `documento`, `url`, `fecha_descarga`, `fecha_vigencia`, `provincia`, `canton`, `atractivo`, `pagina`.
- Datos volátiles (clima, alertas, estado de vías, volcanes) **no se indexan**: se consultan o enlazan.
- Tablas de costos se manejan como datos estructurados y no como texto embebido.
