# Despliegue con Docker, Traefik y CI/CD

La API se publica en un VPS de Hostinger como un contenedor Docker detrás de **Traefik** (que ya atendía otros
servicios del servidor, junto con Portainer). El dominio y el certificado HTTPS los gestiona Traefik; el despliegue
se automatiza con **GitHub Actions**.

URL pública: `https://planificador.bhsolutions.cloud` (documentación interactiva en `/docs`, salud en `/health`).

## 1. Arquitectura

```
Internet ──443──► Traefik ──red traefik_proxy──► contenedor planificador-api (uvicorn, puerto 8000)
                  (HTTPS, Let's Encrypt)              │
                                                      ├─ .env            (claves, solo en el VPS, chmod 600)
                                                      ├─ data/vectorstore (índice Chroma del RAG, volumen)
                                                      └─ logs/            (volumen)
```

- La API **no publica ningún puerto** en el servidor: Traefik llega a ella por la red Docker `traefik_proxy`.
  (El puerto 8000 del host lo ocupa Portainer, por eso un mapeo `8000:8000` falla con *port is already allocated*.)
- Traefik redirige HTTP a HTTPS y renueva el certificado solo.

## 2. Archivos del repositorio

| Archivo | Para qué sirve |
|---|---|
| `Dockerfile` | Imagen de la API: base `python:3.12-slim` fijada por digest, torch solo CPU con versión exacta, modelo de embeddings incluido, usuario sin privilegios, puerto por la variable `PORT` (8000 por defecto). Las dependencias van con `==` en `requirements.txt` ([ADR 6](09-decisiones.md)). |
| `.dockerignore` | Deja fuera de la imagen el `.env`, `.git`, `.venv`, `tests/`, `docs/`, los logs y el índice. |
| `docker-compose.yml` | Define el servicio, los volúmenes, la red `traefik_proxy` y los *labels* de Traefik. |
| `.github/workflows/ci-cd.yml` | Pipeline: revisión de secretos, pruebas, construcción de la imagen y despliegue. |

## 3. Protección de las claves

1. El `.env` está en `.gitignore` (solo se versiona `.env.example`) y en `.dockerignore`: **nunca entra en git ni en la imagen**.
2. El `.env` real existe en un solo lugar, `/opt/planificador/.env` en el VPS, con permisos `600` (solo root lo lee).
3. Docker lo inyecta al arrancar el contenedor (`env_file: .env`). `src/config.py` usa `load_dotenv()`, que no pisa
   las variables que ya existen en el entorno, así que el código no cambia entre local y servidor.
4. El pipeline no contiene claves: solo referencias `${{ secrets.NOMBRE }}`. Gitleaks revisa cada push y pull request.
5. La imagen no debe tener secretos ni en sus capas. Comprobación:

```bash
docker run --rm planificador-api:latest ls -a /app            # no debe aparecer .env
docker history --no-trunc planificador-api:latest | grep -i -E "key|token|secret"   # sin resultados
```

Si una clave real llegó alguna vez a git, a un chat o a un archivo compartido, debe **rotarse** (Groq, Google Maps).

## 3.1 Frontend y API en el mismo dominio

Desde la versión 0.4.2, `https://planificador.bhsolutions.cloud` sirve **también el frontend** (repositorio
`PlanificadorTuristico.Web`, contenedor `planificador-web`). Traefik reparte por ruta:

| Ruta | Contenedor | Regla |
|---|---|---|
| `/itinerario`, `/agente`, `/health`, `/docs`, `/redoc`, `/openapi.json` | `planificador-api` | `Host(...) && (PathPrefix(...) \|\| ...)`, prioridad **100** (`docker-compose.yml` de este repositorio) |
| Todo lo demás (`/`, archivos de la aplicación) | `planificador-web` | `Host(...)`, prioridad **1** (`docker-compose.yml` del frontend) |

No hace falta CORS (mismo origen) ni tocar el DNS, y la API sigue recibiendo la IP real del visitante para su límite por
IP: entre el visitante y la API solo está Traefik. **Si se agrega un endpoint a la API, hay que sumarlo a la regla:**
`tests/test_despliegue.py` falla si alguna ruta de la API quedó fuera.

Orden al desplegar por primera vez: primero la API con la regla nueva (deja libre `/` para el frontend) y después el
frontend.

## 4. Datos del Traefik del servidor

Se obtuvieron con `docker inspect traefik` y `cat /opt/traefik/traefik.yml`:

| Dato | Valor |
|---|---|
| Red de Docker | `traefik_proxy` |
| Entrypoint HTTPS | `websecure` (443) |
| Entrypoint HTTP | `web` (80) |
| Resolver de certificados | `letsencryptresolver` (desafío HTTP) |
| Provider Docker | activo, con `exposedByDefault: false` (cada servicio necesita `traefik.enable=true`) |

Dominio: se creó un registro **A** `planificador` hacia la IP del VPS (la raíz `bhsolutions.cloud` ya la usa otra web).
Comprobación desde cualquier equipo:

```powershell
nslookup planificador.bhsolutions.cloud
```

## 5. Primer despliegue (manual, una sola vez)

Los comandos de **[PuTTY]** se ejecutan en el servidor; los de **[PowerShell]**, en la carpeta del proyecto.
Se asume que el usuario SSH es `root` y la IP se escribe como `IP_VPS`.

**Carpeta del proyecto** [PuTTY]

```bash
mkdir -p /opt/planificador/data
```

**Subir código, datos e índice** [PowerShell] — hay que estar dentro de la carpeta del proyecto (`cd /d D:\...\PlanificadorTuristico.Api`),
de lo contrario `pscp` responde *No such file or directory*:

```powershell
pscp -r src scripts requirements.txt Dockerfile .dockerignore docker-compose.yml root@IP_VPS:/opt/planificador/
pscp -r data\catalogo data\corpus data\vectorstore root@IP_VPS:/opt/planificador/data/
```

**Subir el `.env` y protegerlo**

```powershell
pscp .env root@IP_VPS:/opt/planificador/.env
```

```bash
chown root:root /opt/planificador/.env && chmod 600 /opt/planificador/.env
```

**Permisos de los volúmenes** (el contenedor corre con el usuario `app`, uid 1000) [PuTTY]

```bash
cd /opt/planificador && mkdir -p logs && chown -R 1000:1000 logs data/vectorstore
```

**Construir la imagen y arrancar** [PuTTY] — la primera construcción tarda varios minutos y la imagen pesa unos 4 GB
(torch y el modelo de embeddings):

```bash
cd /opt/planificador && docker build -t planificador-api:latest . && docker compose up -d
docker compose ps        # el estado debe llegar a "healthy"
curl https://planificador.bhsolutions.cloud/health
```

Respuesta esperada: `status: ok`, la versión (`0.5.0`), el índice (`"rag":{"activo":true,"fragmentos":251}`) y los dos
proveedores configurados (Groq y Gemini), sin ninguna clave.

## 6. Pipeline CI/CD (`.github/workflows/ci-cd.yml`)

Se dispara con `push` y `pull_request` a `develop` y `master`, y a mano desde la pestaña Actions (*Run workflow*).

```
secretos ─┐
pruebas ──┼─► imagen ─► despliegue (solo push a master o ejecución manual)
```

| Job | Qué hace |
|---|---|
| `secretos` | Gitleaks revisa el historial completo en busca de claves. |
| `pruebas` | `pytest` (234 pruebas). Omite `sentence-transformers`: las pruebas no cargan el modelo. |
| `imagen` | Construye el Dockerfile para comprobar que compila (sin publicarlo). |
| `despliegue` | Sube el código por SSH, construye la imagen en el VPS, hace `docker compose up -d`, comprueba `/health` y corre `tests/smoke.py` contra la URL ([08-pruebas.md](08-pruebas.md)). Necesita `secretos`, `pruebas` e `imagen` en verde. |

El despliegue **no toca** el `.env` ni `data/vectorstore`: viven en el servidor. Al cambiar el catálogo o el corpus,
el índice se actualiza a mano (ver «Actualizar el índice del RAG» en §7).

### Secrets de GitHub

*Settings → Secrets and variables → Actions → New repository secret*:

| Secret | Contenido |
|---|---|
| `VPS_HOST` | IP del VPS |
| `VPS_USER` | Usuario SSH |
| `VPS_SSH_KEY` | Llave privada SSH creada solo para el despliegue |
| `VPS_KNOWN_HOSTS` | Salida de `ssh-keyscan IP_VPS` (evita aceptar un servidor falso) |
| `APP_HEALTH_URL` | `https://planificador.bhsolutions.cloud/health` |

Llave de despliegue: se genera en el equipo con `ssh-keygen -t ed25519 -f deploy_key -N '""'`, la pública
(`deploy_key.pub`) se agrega a `~/.ssh/authorized_keys` del servidor, la privada se pega en `VPS_SSH_KEY`, y ambos
archivos se borran del equipo.

## 7. Operación

**Actualizar la API:** hacer push a `master` (despliegue automático) o ejecutar *Run workflow*. En manual:

```bash
cd /opt/planificador && docker build -t planificador-api:latest . && docker compose up -d
```

**Cambiar o rotar una clave:** editar el `.env` del servidor y recrear el contenedor.

```bash
nano /opt/planificador/.env
cd /opt/planificador && docker compose up -d
```

**Ver registros:**

```bash
docker compose logs -f
docker logs traefik 2>&1 | grep -i -E "planificador|acme|error" | tail -20
```

### Actualizar el índice del RAG (a mano)

**Cuándo:** cada vez que cambia el catálogo (`data/catalogo/`) o el corpus (`data/corpus/manifiesto.csv`, `data/raw/`).
El despliegue por CD **no** lo actualiza: `data/vectorstore` no está en git ni en la imagen (el corpus original no se
versiona). Fusionar una versión nueva en `master` sin hacer estos pasos deja a producción con el índice anterior; `/health`
lo delata porque informa `rag.fragmentos` (riesgo **R9** de [riesgos.md](riesgos.md)). La versión 0.5.0 trae el catálogo
verificado de 60 atractivos y un índice de **251 fragmentos** (la 0.4.2 tenía 241).

1. **En el equipo**, con el catálogo y el corpus definitivos (reconstruye la colección completa: no duplica):

```powershell
python scripts/construir_corpus.py      # solo si cambió el corpus (descarga las páginas fuente)
python scripts/ingestar_rag.py          # imprime cuántos fragmentos indexó: deben ser 251
```

2. **En el servidor**, apartar el índice anterior [PuTTY]:

```bash
cd /opt/planificador && mv data/vectorstore data/vectorstore.anterior
```

3. **Subir el nuevo** [PowerShell], desde la carpeta del proyecto:

```powershell
pscp -r data\vectorstore root@IP_VPS:/opt/planificador/data/
```

4. **Permisos y reinicio** [PuTTY] (el contenedor corre con el usuario `app`, uid 1000):

```bash
chown -R 1000:1000 /opt/planificador/data/vectorstore && cd /opt/planificador && docker compose restart
```

5. **Comprobar** que producción muestra la versión y el índice esperados:

```bash
curl -s https://planificador.bhsolutions.cloud/health
```

   Debe responder `"version":"0.5.0"` y `"rag":{"activo":true,"fragmentos":251}`. Si `fragmentos` no coincide o `activo`
   es `false`, devolver el anterior (`rm -rf data/vectorstore && mv data/vectorstore.anterior data/vectorstore`) y
   reiniciar. Cuando está bien: `rm -rf /opt/planificador/data/vectorstore.anterior`.

## 8. Problemas encontrados

| Síntoma | Causa | Solución |
|---|---|---|
| `port is already allocated` al arrancar | El puerto 8000 del host lo usa Portainer | No publicar puertos; usar Traefik por la red `traefik_proxy`. |
| `pscp: src: No such file or directory` | El comando se ejecutó fuera de la carpeta del proyecto | Hacer `cd /d` a la carpeta del proyecto antes. |
| La API arranca lenta o intenta bajar el modelo | El modelo de embeddings se descargaba en cada arranque | Se descarga al construir la imagen y `HF_HUB_OFFLINE=1` evita consultar Hugging Face. |
| Sin certificado HTTPS | El dominio no apunta al VPS, o el puerto 80 está cerrado | Revisar `nslookup` y los logs de Traefik. |
| El smoke del pipeline falla con **405 de nginx** justo después de desplegar, aunque «Verificar que la API responde» pasó (release 0.5.0, 12 nov) | Al reiniciar el contenedor, Traefik no enruta la API hasta que su healthcheck pasa (~60 s por el modelo de embeddings) y el frontend, que comparte el dominio, responde 200 a cualquier GET, también a `/health` (`<!doctype html>`). El chequeo daba por buena la respuesta del frontend | El paso ahora exige el **JSON de la API** (`"status":"ok"`) y espera hasta 4 minutos antes de correr el smoke. |

## 9. Recomendaciones de seguridad

- Acceso SSH con llave y sin contraseña; evitar trabajar siempre como `root` (crear un usuario con permisos de Docker y usarlo en `VPS_USER`).
- Portainer publica los puertos 8000 y 9443 en todas las interfaces: conviene restringirlos o publicarlo también detrás de Traefik, con contraseña fuerte y 2FA.
- Docker ignora `ufw` en los puertos que publica; por eso la API no publica ninguno.
- Guardar una copia del `.env` en un gestor de contraseñas del equipo por si se pierde el servidor.
