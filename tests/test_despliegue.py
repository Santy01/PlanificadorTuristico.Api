"""El despliegue sube al VPS lo que el Dockerfile copia. Hallazgo de la Semana 4: el job subía src, scripts y data,
pero no config/, y desde que el Dockerfile hace `COPY config` el próximo `docker build` en el servidor habría fallado."""
import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


def copiados_por_el_dockerfile() -> set[str]:
    origenes = set()
    for linea in (RAIZ / "Dockerfile").read_text(encoding="utf-8").splitlines():
        m = re.match(r"\s*COPY\s+(?!--from)(.+)\s+\S+\s*$", linea)
        if m:
            origenes.update(m.group(1).split())
    return origenes


def subidos_por_el_despliegue() -> set[str]:
    flujo = (RAIZ / ".github" / "workflows" / "ci-cd.yml").read_text(encoding="utf-8")
    m = re.search(r"tar czf - (.+?)\\", flujo)
    assert m, "no se encontró el tar del job de despliegue"
    return set(m.group(1).split())


def test_el_despliegue_sube_todo_lo_que_copia_el_dockerfile():
    # «data» cuenta como subida si se suben sus subcarpetas versionadas (data/catalogo, data/corpus): el índice
    # (data/vectorstore) llega por volumen a propósito.
    subidos = subidos_por_el_despliegue()
    faltan = {o for o in copiados_por_el_dockerfile()
              if not any(o == s or o.startswith(s + "/") or s.startswith(o + "/") for s in subidos)}
    assert not faltan, f"el job de despliegue no sube {faltan}"


def test_lo_que_se_reemplaza_tambien_se_borra_antes():
    """Si una carpeta se sube sin borrarla antes, los archivos eliminados del repositorio seguirían en el servidor."""
    flujo = (RAIZ / ".github" / "workflows" / "ci-cd.yml").read_text(encoding="utf-8")
    borrados = set(re.search(r"rm -rf ([^\"]+)\"", flujo).group(1).split())
    carpetas = {s for s in subidos_por_el_despliegue() if (RAIZ / s).is_dir()}
    assert carpetas <= borrados, f"se suben sin borrar antes: {carpetas - borrados}"
