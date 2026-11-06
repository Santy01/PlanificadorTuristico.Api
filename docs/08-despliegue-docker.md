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
| `Dockerfile` | Imagen de la API: Python 3.12, torch solo CPU, modelo de embeddings incluido, usuario sin privilegios, puerto por la variable `PORT` (8000 por defecto). |
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

Respuesta esperada: `{"status":"ok"}`.

## 6. Pipeline CI/CD (`.github/workflows/ci-cd.yml`)

Se dispara con `push` y `pull_request` a `develop` y `master`, y a mano desde la pestaña Actions (*Run workflow*).

```
secretos ─┐
pruebas ──┼─► imagen ─► despliegue (solo push a master o ejecución manual)
```

| Job | Qué hace |
|---|---|
| `secretos` | Gitleaks revisa el historial completo en busca de claves. |
| `pruebas` | `pytest` (104 pruebas). Omite `sentence-transformers`: las pruebas no cargan el modelo. |
| `imagen` | Construye el Dockerfile para comprobar que compila (sin publicarlo). |
| `despliegue` | Sube el código por SSH, construye la imagen en el VPS, hace `docker compose up -d` y comprueba `/health`. Necesita `secretos`, `pruebas` e `imagen` en verde. |

El despliegue **no toca** el `.env` ni `data/vectorstore`: viven en el servidor.

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

**Actualizar el índice del RAG:** reconstruirlo en el equipo (`python scripts/ingestar_rag.py`) y subir `data\vectorstore`
con `pscp`; luego `docker compose restart`.

## 8. Problemas encontrados

| Síntoma | Causa | Solución |
|---|---|---|
| `port is already allocated` al arrancar | El puerto 8000 del host lo usa Portainer | No publicar puertos; usar Traefik por la red `traefik_proxy`. |
| `pscp: src: No such file or directory` | El comando se ejecutó fuera de la carpeta del proyecto | Hacer `cd /d` a la carpeta del proyecto antes. |
| La API arranca lenta o intenta bajar el modelo | El modelo de embeddings se descargaba en cada arranque | Se descarga al construir la imagen y `HF_HUB_OFFLINE=1` evita consultar Hugging Face. |
| Sin certificado HTTPS | El dominio no apunta al VPS, o el puerto 80 está cerrado | Revisar `nslookup` y los logs de Traefik. |

## 9. Recomendaciones de seguridad

- Acceso SSH con llave y sin contraseña; evitar trabajar siempre como `root` (crear un usuario con permisos de Docker y usarlo en `VPS_USER`).
- Portainer publica los puertos 8000 y 9443 en todas las interfaces: conviene restringirlos o publicarlo también detrás de Traefik, con contraseña fuerte y 2FA.
- Docker ignora `ufw` en los puertos que publica; por eso la API no publica ninguno.
- Guardar una copia del `.env` en un gestor de contraseñas del equipo por si se pierde el servidor.
