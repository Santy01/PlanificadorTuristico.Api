"""Un "proveedor" falso que corre en su computadora y responde como la API de OpenAI.
Sirve para practicar el manejo de errores sin gastar cuota real.

    python scripts/servidor_simulado.py --limite 5           # 429 a partir de la 6.ª solicitud en 10 segundos
    python scripts/servidor_simulado.py --romper-json 0.5  # la mitad de las respuestas trae JSON roto
    python scripts/servidor_simulado.py --lento 40         # tarda 40 s (para probar el tiempo límite)

Luego, en .env:  LLM_PRINCIPAL=simulado
"""
import argparse
import json
import math
import random
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

OPC = argparse.Namespace(limite=5, ventana=10, romper_json=0.0, lento=0.0, vacio=0.0)
_tiempos: deque = deque()
_candado = threading.Lock()


def _ejemplo(esquema: dict, defs: dict):
    """Inventa un valor que cumpla el esquema (es un simulador, no un modelo)."""
    if "$ref" in esquema:
        return _ejemplo(defs[esquema["$ref"].split("/")[-1]], defs)
    if "anyOf" in esquema:
        return _ejemplo(next(s for s in esquema["anyOf"] if s.get("type") != "null"), defs)
    if "enum" in esquema:
        return random.choice(esquema["enum"])
    t = esquema.get("type")
    if t == "object":
        return {k: _ejemplo(v, defs) for k, v in esquema.get("properties", {}).items()}
    if t == "array":
        return [_ejemplo(esquema.get("items", {"type": "string"}), defs)] if random.random() < .5 else []
    return {"boolean": True, "integer": 1, "number": 1.0}.get(t, "texto simulado")


class Manejador(BaseHTTPRequestHandler):
    def log_message(self, *a):  # silencio
        pass

    def _enviar(self, codigo: int, cuerpo: dict, cabeceras: dict | None = None):
        datos = json.dumps(cuerpo).encode()
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json")
        for k, v in (cabeceras or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(datos)))
        self.end_headers()
        self.wfile.write(datos)

    def do_GET(self):
        self._enviar(200, {"estado": "ok"})

    def do_POST(self):
        cuerpo = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        with _candado:
            ahora = time.time()
            while _tiempos and ahora - _tiempos[0] > OPC.ventana:
                _tiempos.popleft()
            if len(_tiempos) >= OPC.limite:
                espera = max(1, math.ceil(OPC.ventana - (ahora - _tiempos[0])))
                return self._enviar(429, {"error": {"message": "Rate limit reached (simulado)", "type": "rate_limit"}},
                                    {"retry-after": str(espera)})
            _tiempos.append(ahora)
        if OPC.lento:
            time.sleep(OPC.lento)
        rf = cuerpo.get("response_format") or {}
        if rf.get("type") == "json_schema":
            esq = rf["json_schema"]["schema"]
            contenido = json.dumps(_ejemplo(esq, esq.get("$defs", {})), ensure_ascii=False)
            if random.random() < OPC.romper_json:
                contenido = contenido[: len(contenido) // 2]
        else:
            contenido = "Respuesta simulada: aquí iría el texto del modelo."
        if random.random() < OPC.vacio:
            contenido = ""
        self._enviar(200, {
            "id": "sim-1", "object": "chat.completion", "created": int(time.time()), "model": cuerpo.get("model"),
            "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": contenido}}],
            "usage": {"prompt_tokens": 42, "completion_tokens": 58, "total_tokens": 100},
        })


def iniciar(puerto: int = 8099, **opciones) -> ThreadingHTTPServer:
    """Arranca el servidor en segundo plano (lo usan demo_429.py y las pruebas)."""
    for k, v in opciones.items():
        setattr(OPC, k, v)
    _tiempos.clear()
    srv = ThreadingHTTPServer(("127.0.0.1", puerto), Manejador)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limite", type=int, default=5, help="solicitudes permitidas por ventana")
    ap.add_argument("--ventana", type=float, default=10, help="segundos de la ventana")
    ap.add_argument("--romper-json", type=float, default=0.0)
    ap.add_argument("--lento", type=float, default=0.0)
    ap.add_argument("--vacio", type=float, default=0.0)
    a = ap.parse_args()
    OPC.limite, OPC.ventana, OPC.romper_json, OPC.lento, OPC.vacio = a.limite, a.ventana, a.romper_json, a.lento, a.vacio
    print(f"Proveedor simulado en http://127.0.0.1:8099/v1 · {a.limite} solicitudes cada {a.ventana:g} s · Ctrl+C para salir")
    ThreadingHTTPServer(("127.0.0.1", 8099), Manejador).serve_forever()
