"""Pronóstico del clima (Open-Meteo, sin clave). Regla de oro: el clima es un EXTRA.

Nada de lo que pase aquí (sin internet, 5xx, tiempo agotado, JSON raro, fecha fuera de rango)
puede romper el itinerario: toda falla se convierte en «clima no disponible» (HU-06, RNF-08).
"""
from __future__ import annotations

import logging
import os
import time
from datetime import date, timedelta
from typing import Callable

import httpx

from src.schemas import Clima

log = logging.getLogger("clima")

BASE_URL = "https://api.open-meteo.com/v1"
HORIZONTE_DIAS = 15            # Open-Meteo pronostica ~16 días contando hoy
UMBRAL_LLUVIA_MM = 10.0        # precipitación diaria desde la cual se considera lluvia intensa
CODIGOS_LLUVIA_INTENSA = {65, 67, 82, 95, 96, 99}  # lluvia fuerte, chubasco violento, tormenta
TTL_CACHE_S = 3600

# Códigos WMO que usa Open-Meteo → texto en español
CODIGOS_WMO = {
    0: "Despejado", 1: "Mayormente despejado", 2: "Parcialmente nublado", 3: "Nublado",
    45: "Niebla", 48: "Niebla con escarcha",
    51: "Llovizna ligera", 53: "Llovizna", 55: "Llovizna intensa", 56: "Llovizna helada", 57: "Llovizna helada intensa",
    61: "Lluvia ligera", 63: "Lluvia moderada", 65: "Lluvia fuerte", 66: "Lluvia helada", 67: "Lluvia helada fuerte",
    71: "Nevada ligera", 73: "Nevada moderada", 75: "Nevada fuerte", 77: "Granizo fino",
    80: "Chubascos ligeros", 81: "Chubascos", 82: "Chubascos violentos", 85: "Chubascos de nieve", 86: "Chubascos de nieve fuertes",
    95: "Tormenta eléctrica", 96: "Tormenta con granizo", 99: "Tormenta fuerte con granizo",
}


def no_disponible(motivo: str, fecha: date | None = None) -> Clima:
    return Clima(disponible=False, motivo_no_disponible=motivo, fecha=fecha)


class ClienteClima:
    def __init__(self, base_url: str | None = None, timeout_s: float | None = None, reintentos: int = 1,
                 transport: httpx.BaseTransport | None = None, hoy: Callable[[], date] = date.today):
        self.base_url = (base_url or os.getenv("WEATHER_API_BASE_URL") or BASE_URL).rstrip("/")
        self.timeout_s = timeout_s if timeout_s is not None else float(os.getenv("WEATHER_TIMEOUT_S", "5"))
        self.reintentos = reintentos
        self._http = httpx.Client(timeout=self.timeout_s, transport=transport)
        self._hoy = hoy
        self._cache: dict[tuple, tuple[float, Clima]] = {}

    def pronostico(self, lat: float | None, lon: float | None, dia: date | None) -> Clima:
        """NUNCA lanza excepciones: siempre devuelve un Clima (disponible o no)."""
        try:
            return self._pronostico(lat, lon, dia)
        except Exception as e:  # noqa: BLE001 — el clima no puede romper el flujo bajo ninguna circunstancia
            log.warning("clima_fallo tipo=%s", type(e).__name__)
            return no_disponible("El servicio de clima no respondió.", dia)

    def _pronostico(self, lat, lon, dia) -> Clima:
        if dia is None:
            return no_disponible("Indica la fecha de inicio del viaje para ver el pronóstico.")
        if lat is None or lon is None:
            return no_disponible("El lugar aún no tiene ubicación verificada.", dia)
        hoy = self._hoy()
        if dia < hoy:
            return no_disponible("La fecha ya pasó.", dia)
        if dia > hoy + timedelta(days=HORIZONTE_DIAS):
            return no_disponible(f"El pronóstico solo cubre los próximos {HORIZONTE_DIAS + 1} días.", dia)

        clave = (round(lat, 2), round(lon, 2), dia)
        en_cache = self._cache.get(clave)
        if en_cache and time.monotonic() - en_cache[0] < TTL_CACHE_S:
            return en_cache[1]

        params = {
            "latitude": lat, "longitude": lon, "timezone": "America/Guayaquil",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,precipitation_probability_max",
            "start_date": dia.isoformat(), "end_date": dia.isoformat(),
        }
        ultimo: Exception | None = None
        for _ in range(self.reintentos + 1):
            try:
                r = self._http.get(f"{self.base_url}/forecast", params=params)
                r.raise_for_status()
                clima = self._interpretar(r.json(), dia)
                self._cache[clave] = (time.monotonic(), clima)
                return clima
            except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as e:
                ultimo = e
        log.warning("clima_agotado tipo=%s", type(ultimo).__name__)
        return no_disponible("El servicio de clima no respondió.", dia)

    @staticmethod
    def _interpretar(datos: dict, dia: date) -> Clima:
        d = datos["daily"]
        codigo = d["weather_code"][0]
        mm, prob = d["precipitation_sum"][0], d["precipitation_probability_max"][0]
        tmax, tmin = d["temperature_2m_max"][0], d["temperature_2m_min"][0]
        if codigo is None and tmax is None:
            raise ValueError("pronóstico vacío")
        intensa = (mm or 0) >= UMBRAL_LLUVIA_MM or codigo in CODIGOS_LLUVIA_INTENSA
        return Clima(
            disponible=True, motivo_no_disponible=None, fecha=dia,
            resumen=CODIGOS_WMO.get(codigo, "Sin descripción"),
            temp_min_c=tmin, temp_max_c=tmax, prob_lluvia_pct=prob, precipitacion_mm=mm,
            lluvia_intensa=intensa, fuente="Open-Meteo",
        )
