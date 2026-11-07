"""Límite de peticiones por IP (OWASP LLM10 · consumo sin límite; control «límite» de la integración estable).

Cada solicitud de itinerario o del agente gasta cuota del plan gratuito del proveedor. Sin límite, una sola persona
(o un script) puede agotarla para todos justo el día de la demo. Ventana deslizante en memoria: vale para UN proceso de
uvicorn, como en docker-compose.yml; con varios procesos haría falta un almacén compartido (Redis).
"""
from __future__ import annotations

import math
import threading
import time
from collections import deque
from typing import Callable


class LimitadorPorIP:
    def __init__(self, maximo: int, ventana_s: float, reloj: Callable[[], float] = time.monotonic):
        self.maximo, self.ventana_s, self._reloj = maximo, ventana_s, reloj
        self._marcas: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def permitir(self, clave: str) -> tuple[bool, int]:
        """(se permite, segundos a esperar si no). Registra la petición solo si se permite."""
        ahora = self._reloj()
        with self._lock:
            marcas = self._marcas.setdefault(clave, deque())
            while marcas and marcas[0] <= ahora - self.ventana_s:
                marcas.popleft()
            if len(marcas) >= self.maximo:
                return False, max(1, math.ceil(marcas[0] + self.ventana_s - ahora))
            marcas.append(ahora)
            if len(self._marcas) > 10_000:  # que IPs que ya no vuelven no llenen la memoria
                self._purgar(ahora)
            return True, 0

    def _purgar(self, ahora: float) -> None:
        for k in [k for k, m in self._marcas.items() if not m or m[-1] <= ahora - self.ventana_s]:
            del self._marcas[k]


def ip_cliente(cabecera_xff: str | None, ip_conexion: str | None, proxies_confiables: int) -> str:
    """IP real del visitante. Detrás de N proxies de confianza (Traefik = 1), la IP real es la N-ésima desde el final
    de X-Forwarded-For: las anteriores las puede escribir el propio cliente para hacerse pasar por otro."""
    if proxies_confiables and cabecera_xff:
        partes = [p.strip() for p in cabecera_xff.split(",") if p.strip()]
        if len(partes) >= proxies_confiables:
            return partes[-proxies_confiables]
    return ip_conexion or "desconocida"
