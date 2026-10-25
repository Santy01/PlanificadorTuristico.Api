# Requisitos

**Versión:** 0.1 (Semana 1)

## 1. Historias de usuario

Prioridad: M = Must, S = Should, C = Could.

### HU-01 · Ingresar parámetros del viaje (M)
Como visitante quiero indicar días, presupuesto, punto de partida e intereses para recibir un itinerario ajustado a mi viaje.

- Dado que estoy en la pantalla de planificación, cuando ingreso 3 días, un presupuesto y un punto de partida válidos, entonces el sistema acepta el formulario y solicita el itinerario.
- Dado que dejo vacío un campo obligatorio, cuando envío el formulario, entonces se muestra un mensaje que indica cuál campo falta y no se genera itinerario.
- Dado que ingreso un número de días fuera del rango permitido, cuando envío, entonces se indica el rango válido.

### HU-02 · Generar itinerario día por día (M)
Como visitante quiero un itinerario organizado por día para saber qué visitar y en qué orden.

- Dado que envié parámetros válidos, cuando el sistema responde, entonces el itinerario contiene exactamente el número de días solicitado.
- Dado un itinerario generado, cuando reviso cada actividad, entonces todo atractivo pertenece al catálogo verificado.
- Dado que la duración total de un día excede la jornada máxima configurada, cuando se genera el itinerario, entonces el sistema redistribuye las actividades.

### HU-03 · Ver itinerario en mapa (M)
Como visitante quiero ver los atractivos en un mapa interactivo para entender la distribución y los traslados.

- Dado un itinerario generado, cuando abro la vista de mapa, entonces veo un marcador por atractivo con numeración según el orden de visita.
- Dado que selecciono un día, cuando el mapa se actualiza, entonces solo se resaltan los atractivos y la ruta de ese día.
- Dado que un atractivo tiene coordenadas `POR VERIFICAR`, cuando se genera el mapa, entonces no se dibuja marcador y se muestra una advertencia.

### HU-04 · Consultar descripciones con citas (M)
Como visitante quiero que cada descripción cite su fuente oficial para confiar en la información.

- Dado un atractivo en el itinerario, cuando leo su descripción, entonces incluye al menos una cita con nombre del documento y enlace.
- Dado que no existe fragmento recuperado que respalde una afirmación, cuando se genera la descripción, entonces la afirmación no se incluye.
- Dado que hago clic en una cita, cuando se abre, entonces veo el fragmento fuente utilizado.

### HU-05 · Ver costos estimados (M)
Como visitante quiero ver el costo estimado por actividad y total para validar mi presupuesto.

- Dado un itinerario, cuando reviso los costos, entonces cada valor muestra su fuente y fecha de verificación.
- Dado que un costo es `POR VERIFICAR`, cuando se calcula el total, entonces se excluye del total y se indica que el total es parcial.
- Dado que el total estimado supera el presupuesto, cuando se muestra el resultado, entonces se advierte y se ofrecen alternativas dentro del catálogo.

### HU-06 · Consultar pronóstico del clima (M)
Como visitante quiero ver el pronóstico por día y lugar para decidir qué actividades realizar.

- Dado un itinerario con fechas, cuando se consulta la API de clima, entonces cada día muestra el pronóstico del lugar principal.
- Dado que la API de clima no responde, cuando se genera el itinerario, entonces se muestra «clima no disponible» y el itinerario no falla.
- Dado que el pronóstico indica lluvia intensa para una actividad al aire libre, cuando se genera el itinerario, entonces se sugiere una alternativa del catálogo.

### HU-07 · Optimizar el orden de visitas (S)
Como visitante quiero que el orden minimice los traslados para aprovechar mejor el tiempo.

- Dado un conjunto de atractivos de un día, cuando el optimizador se ejecuta, entonces el tiempo total de traslado no es mayor que el del orden de entrada.
- Dado que no hay coordenadas verificadas, cuando se ejecuta, entonces se conserva el orden por cercanía de cantón y se informa la limitación.

### HU-08 · Recalcular ante cambios (S)
Como visitante quiero modificar días, presupuesto o excluir un atractivo y obtener un itinerario actualizado.

- Dado un itinerario existente, cuando quito un atractivo, entonces se recalcula sin volver a pedir todos los parámetros.
- Dado que cambio el número de días, cuando confirmo, entonces el nuevo itinerario respeta el nuevo total.
- Dado un recálculo, cuando termina, entonces se muestra qué cambió respecto a la versión anterior.

### HU-09 · Rechazo de solicitudes fuera de alcance (M)
Como responsable del sistema quiero que rechace solicitudes fuera del alcance para evitar usos indebidos.

- Dado que el usuario pide reservar o pagar, cuando envía la solicitud, entonces el sistema explica que no puede hacerlo.
- Dado que pide un atractivo que no está en el catálogo, cuando consulta, entonces responde que no tiene información verificada y no inventa.
- Dado que pide consejo médico o de seguridad, cuando consulta, entonces remite a fuentes oficiales.
- Dado un texto que intenta alterar las instrucciones del sistema, cuando se procesa, entonces se ignora la instrucción.

### HU-10 · Administrar el catálogo (S)
Como administrador quiero actualizar atractivos y su estado de verificación para mantener la calidad de datos.

- Dado un atractivo con campos `POR VERIFICAR`, cuando se completa con fuente y fecha, entonces queda disponible para costos y mapa.
- Dado un cambio en el catálogo, cuando se guarda, entonces queda registrado quién y cuándo lo hizo.

### HU-11 · Accesibilidad y uso móvil (S)
Como visitante con dispositivo móvil o tecnología de apoyo quiero usar la aplicación sin barreras.

- Dado un teléfono con pantalla pequeña, cuando abro la aplicación, entonces el contenido es utilizable sin desplazamiento horizontal.
- Dado un lector de pantalla, cuando navego el itinerario, entonces los elementos tienen etiquetas descriptivas.

## 2. Requisitos no funcionales

> Los umbrales son **metas de diseño propuestas** y deben validarse y ajustarse con mediciones reales.

| ID | Categoría | Requisito | Métrica / método de medición |
|---|---|---|---|
| RNF-01 | Latencia | La generación de un itinerario completo tiene p95 ≤ 20 s | Pruebas de carga con 50 consultas representativas |
| RNF-02 | Latencia | Respuesta de `/health` p95 ≤ 200 ms | Prueba automatizada |
| RNF-03 | Recálculo | El recálculo ante un cambio tiene p95 ≤ 10 s | Pruebas de escenarios de cambio |
| RNF-04 | Disponibilidad | ≥ 99 % mensual en horario de demostración (meta académica) | Monitoreo de `/health` |
| RNF-05 | Cobertura de citas | ≥ 95 % de las afirmaciones factuales sobre atractivos incluyen cita verificable | Auditoría sobre muestra de 50 itinerarios |
| RNF-06 | Alucinación | 0 atractivos fuera del catálogo; ≤ 2 % de afirmaciones no respaldadas por fragmentos | Conjunto de evaluación con revisión manual |
| RNF-07 | Robustez | 100 % de los casos adversarios del conjunto de pruebas (reserva, médico, injection) son rechazados | Suite en `tests/` |
| RNF-08 | Degradación | Si falla la API de clima o mapas, el itinerario se entrega con aviso | Pruebas con fallos simulados |
| RNF-09 | Accesibilidad | Cumplimiento de WCAG 2.1 nivel AA en pantallas principales | Auditoría con herramienta automática y revisión manual |
| RNF-10 | Privacidad | No se almacenan datos personales identificables; los parámetros del viaje no se asocian a una persona; retención de registros ≤ 30 días | Revisión de diseño y de registros |
| RNF-11 | Privacidad | Alineación con la Ley Orgánica de Protección de Datos Personales del Ecuador | Revisión documental (verificar texto vigente) |
| RNF-12 | Seguridad | Claves en variables de entorno, nunca en el repositorio | Escaneo de secretos antes de cada entrega |
| RNF-13 | Costo | Costo por consulta ≤ tope definido en la Semana 2 | Registro de tokens por consulta |
| RNF-14 | Mantenibilidad | Cobertura de pruebas unitarias ≥ 70 % en módulos de lógica | Informe de cobertura |
| RNF-15 | Trazabilidad | Cada itinerario registra versión del catálogo y fuentes usadas | Inspección de registros |
| RNF-16 | Idioma | Interfaz y respuestas en español | Revisión manual |
