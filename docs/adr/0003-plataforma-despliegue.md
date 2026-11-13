# ADR-0003 · Plataforma de despliegue

- **Estado:** aceptada
- **Fecha:** 7 de noviembre de 2026
- **Grupo 4 · Planificador turístico**

## Contexto

- **Embeddings:** locales, con torch (solo CPU) y `intfloat/multilingual-e5-small`. Juntos rondan los 470 MB en memoria, sin contar la aplicación.
- **Backend:** Python 3.12 con FastAPI; un solo proceso de uvicorn.
- **Datos escritos en ejecución:** logs, la bandeja de salida simulada y las acciones pendientes del agente (en memoria).
- **Administración de servidores:** el equipo ya administra un VPS con Docker, Traefik y Portainer, que aloja otros servicios.
- En el taller del 4 de noviembre se eligió *Azure for Students* (sin tarjeta). Al día siguiente (5 de noviembre) el
  equipo desplegó la API en su VPS con Docker, Traefik y HTTPS (rama `feature/11-docker-ci-cd`), y esa es la
  plataforma que se mantiene.

## Decisión

**VPS propio con Docker y Traefik**, en `https://planificador.bhsolutions.cloud`.

- Traefik termina HTTPS con Let's Encrypt y redirige HTTP a HTTPS.
- El contenedor se construye en el servidor con el `Dockerfile` del repositorio.
- CI/CD con GitHub Actions: en cada push o pull request corren Gitleaks, pytest con cobertura y la construcción de la
  imagen. **Solo desde `master`** (o a mano) se despliega por SSH, y únicamente si todo lo anterior pasó (`needs`).
- Las credenciales de producción (`GROQ_API_KEY`, `GEMINI_API_KEY`) viven en el `.env` del servidor (`chmod 600`),
  fuera del repositorio y de la imagen. Las del pipeline (`VPS_SSH_KEY`, `VPS_HOST`, `VPS_USER`, `VPS_KNOWN_HOSTS`,
  `APP_HEALTH_URL`) viven en GitHub › Settings › Secrets and variables › Actions.

## Dónde vive cada dato

| Dato | La app lo… | Dónde vive en producción |
|---|---|---|
| Índice del RAG (`data/vectorstore`, 251 fragmentos, catálogo verificado del 7 nov 2026) | lee | Volumen del servidor (`./data/vectorstore`), subido a mano desde el equipo que lo construye. No va en la imagen porque el corpus original (`data/raw`) no se versiona |
| Catálogo y manifiesto del corpus | lee | Dentro de la imagen |
| Configuración (`config/`, prompts) | lee | Dentro de la imagen |
| Modelo de embeddings | lee | Dentro de la imagen (se descarga al construir; `HF_HUB_OFFLINE=1` al arrancar) |
| Historial de la conversación | — | No existe en el servidor: el cliente lo reenvía en cada mensaje |
| Acciones pendientes del agente | escribe | En memoria; **se pierden al reiniciar y lo aceptamos**: vencen a los 15 minutos de todos modos y el visitante puede volver a pedir el envío |
| Contadores del límite por IP | escribe | En memoria; se pierden al reiniciar (aceptado: es una ventana de 60 s) |
| Logs (`llm.jsonl`, `agente.jsonl`) y bandeja de salida simulada | escribe | Volumen del servidor (`./logs`); sin texto del visitante y con el correo enmascarado |

**El despliegue no actualiza el índice.** El pipeline sube el código, `config/` y el catálogo, pero no
`data/vectorstore`: no está en git. Si cambia el catálogo o el corpus hay que reconstruir el índice en el equipo y
subirlo a mano; sin hacerlo, producción queda con el índice anterior y `/health` lo delata (`rag.fragmentos`). El
procedimiento está en [../08-despliegue-docker.md](../08-despliegue-docker.md), sección «Actualizar el índice del RAG».

## Alternativas descartadas

| Alternativa | Por qué no |
|---|---|
| Azure for Students (Container Apps) | Elegida en el taller; habría que volver a montar lo que ya funciona (dominio, HTTPS, CI/CD) y validar la cuenta institucional. No aporta nada que el VPS no tenga |
| Google Cloud Run | Pide tarjeta; con escala a cero, cada arranque en frío carga torch y E5 (varios segundos); la RAM se paga |
| Render Free | 512 MB no alcanzan para torch con E5 (unos 470 MB) más la aplicación; además se duerme a los 15 minutos |
| Fly.io, Koyeb, Hugging Face Spaces | Ya no tienen plan gratuito útil para cuentas nuevas (piden tarjeta o plan PRO) |

## Consecuencias

- **Lo que aceptamos:** un solo servidor y un solo proceso, sin alta disponibilidad. Si el VPS cae, la app cae. Las
  acciones pendientes y los contadores del límite son de ese proceso: escalar a varios procesos exigiría un almacén
  compartido, como Redis.
- **Arranque:** no hay escala a cero; la app está siempre encendida y el RAG se precarga al arrancar, así que no hay
  arranque en frío en la demo.
- **Costo:** el del VPS que el equipo ya paga; no hay costo por petición. El límite de gasto real es la cuota gratuita de
  Groq y de Gemini, protegida con el límite por IP (riesgo R1 en [docs/riesgos.md](../riesgos.md)).
- **Reproducible:** cualquiera con acceso al servidor puede repetir el despliegue desde cero con
  [docs/08-despliegue-docker.md](../08-despliegue-docker.md) y el `Dockerfile`.
- **Pendiente operativo:** al liberar la 0.4.0, agregar `LLM_RESPALDO=gemini`, `GEMINI_API_KEY` y `GEMINI_MODEL` al `.env`
  del servidor y comprobar con `/health` que `rag.fragmentos` es mayor que cero y que ambos proveedores aparecen
  configurados.
