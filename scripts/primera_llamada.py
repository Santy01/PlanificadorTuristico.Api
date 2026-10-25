"""NIVEL 1 · Primera llamada real al modelo en Groq (sin protecciones, solo para ver cómo funciona).

    python scripts/primera_llamada.py
"""
import os

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()  # lee la clave del archivo .env (nunca la escriba aquí)

cliente = OpenAI(api_key=os.environ["GROQ_API_KEY"], base_url="https://api.groq.com/openai/v1")

respuesta = cliente.chat.completions.create(
    model=os.getenv("GROQ_MODEL", "openai/gpt-oss-20b"),
    messages=[
        {"role": "system", "content": "Respondes en español, en una sola oración."},
        {"role": "user", "content": "¿Qué atractivo natural destaca en Baños de Agua Santa?"},
    ],
)

print("Respuesta:", respuesta.choices[0].message.content)
print("Tokens de entrada:", respuesta.usage.prompt_tokens, "· de salida:", respuesta.usage.completion_tokens)
