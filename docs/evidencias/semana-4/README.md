# Semana 4 · Credenciales, riesgos y despliegue robusto

Evidencia de lo trabajado sobre los talleres «Tablero, credenciales y riesgos» (4 de noviembre) y «Desplegar, probar
y documentar» (5 y 6 de noviembre). Se completa a medida que avanzan las fases.

## 1. Credenciales (misiones 2, 3 y 6 del taller de credenciales)

**Gitleaks sobre todo el historial**, localmente con Docker:

```bash
docker run --rm -v "$PWD:/repo" zricethezav/gitleaks:latest git /repo -v --redact
```

| Momento | Commits revisados | Hallazgos |
|---|---|---|
| Primera corrida (7 nov) | 75 | **1**: `generic-api-key` en `tests/test_llm.py`, en un commit local que todavía no se había subido |
| Después de corregir | 75 | **0** («no leaks found») |

**El hallazgo era un falso positivo:** un valor ficticio (`"gsk-…"`) que una prueba usaba para comprobar que `/health`
nunca muestra la clave. Aun así se trató como un secreto:

- **Rotar:** no hizo falta, porque no era una clave real.
- **Limpiar:** el commit no se había publicado, así que se reescribió localmente (cherry-pick con el valor cambiado a
  `"valor-ficticio"`) y se borró la rama de respaldo. El historial que llega a GitHub nunca lo tuvo, y no hizo falta un
  `.gitleaksignore`.
- **Prevenir:** Gitleaks ya corre en CI con todo el historial (`fetch-depth: 0`); ese push habría fallado. Lección:
  los valores de prueba que imitan una clave también se detectan, así que se usan textos que no tengan forma de clave.

**Higiene de `.env`:** `.env` y `.env.*` están en `.gitignore` y `!.env.example` versionado; `.env.example` solo trae
nombres (las claves vacías). Las claves de producción viven en el `.env` del VPS y las del pipeline en GitHub Secrets.

## 2. Riesgos y plataforma (misiones 4 y 5)

- Matriz de riesgos: [docs/riesgos.md](../../riesgos.md). Son 9 riesgos reales con referencia OWASP 2026; 5 ya
  ocurrieron en pruebas o en la evaluación.
- ADR-0003: [docs/adr/0003-plataforma-despliegue.md](../../adr/0003-plataforma-despliegue.md). Se mantiene el VPS propio
  con Traefik y se documenta dónde vive cada dato.

## 3. Despliegue robusto (misiones 1 a 5 y 7 del taller de despliegue)

**Bug encontrado en el pipeline:** el job `despliegue` no subía `config/` al VPS, y el `Dockerfile` la copia desde la
Fase 2. El próximo `docker build` en el servidor habría fallado. Se corrigió y se agregó `tests/test_despliegue.py`,
que compara lo que copia el `Dockerfile` con lo que sube el job. Contra el workflow anterior, la prueba detecta
exactamente la carpeta `config` que faltaba.

**`/health` avanzado**, en local con el índice real:

```json
{"status":"ok","version":"0.4.0","rag":{"activo":true,"fragmentos":241},
 "modelo":{"principal":{"nombre":"groq","modelo":"openai/gpt-oss-20b","configurado":true},"respaldo":null}}
```

No llama al modelo y nunca muestra el valor de una clave. `respaldo` aparece `null` porque el `.env` local todavía no
tiene `LLM_RESPALDO=gemini`.

**Límite por IP**, en local: 10 solicitudes seguidas a `/itinerario` respondieron 200 (las 10 rechazadas por la regla de
alcance, sin gastar tokens) y la 11.ª respondió:

```
HTTP/1.1 429 Too Many Requests
retry-after: 60
{"detail":"Demasiadas solicitudes seguidas. Intenta de nuevo en 60 segundos."}
```

**Gemini como respaldo.** Primero se probó con dobles, sin red: si Groq agota su cuota o tiene la clave mala, responde
Gemini con el esquema adaptado a su dialecto; si los dos fallan, la API responde 503 con un mensaje claro. Después se
validó con **Gemini real** (7 de noviembre de 2026), y la prueba encontró dos problemas que los dobles no podían ver:

1. **Modelo retirado.** `gemini-2.5-flash` (el valor por defecto inicial) respondió 404: «no longer available to new
   users». El modelo que Google recomienda, `gemini-3.8-flash`, dio tiempo agotado y 503 por alta demanda. Se eligió
   **`gemini-3.5-flash`**, que respondió de forma estable; se cambia con `GEMINI_MODEL` sin tocar el código.
2. **Firma de pensamiento.** Gemini 3 adjunta a cada pedido de herramienta un `extra_content.google.thought_signature` y
   responde **400** en la vuelta siguiente si no se le devuelve. El agente ahora conserva y devuelve tal cual los campos
   propios del proveedor (prueba `test_thought_signature_de_gemini_vuelve_en_la_siguiente_vuelta`).

Resultado con Gemini real como proveedor:

| Prueba | Resultado |
|---|---|
| Itinerario (esquema adaptado, con RAG) | válido: 2 días, 4 actividades, 2 citas, incluye Quilotoa · 11 s |
| Agente con herramientas («va a llover el día 1») | `consultar_clima` → `recalcular`: sale Termas de la Virgen, entra la Basílica de Baños · 3 vueltas, sin datos sin respaldo |
| Streaming | 12 trozos y el itinerario final válido |
| **Respaldo real**: Groq con clave inválida | Groq da 401 (error definitivo, sin reintentos) → **responde Gemini**, itinerario válido · 13 s |

Gemini tarda unos 11–13 s por itinerario (Groq, ~1 s): sirve como respaldo dentro del p95 de 20 s de RNF-01. En el
streaming la respuesta final todavía no indica qué proveedor respondió.

**Pruebas:** 214 pasan, con 95 % de cobertura.
