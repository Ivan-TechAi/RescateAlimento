# =============================================================================
# usuarios_backend.py — CONSULTA DE USUARIOS EN n8n
# =============================================================================
# CAPSTONE: Etapa 2: automatización.
# Pregunta a n8n si un telegram_id ya está registrado (para no pedir los datos dos veces).
# (Explicación del proyecto completo y del modelo en README.md y docs/ARQUITECTURA.md)
# =============================================================================

"""Consulta el registro de usuarios mediante un webhook de n8n."""
import asyncio

import requests

import config


# ▸ POST bloqueante a n8n.
def _consultar(url: str, telegram_id: str):
    respuesta = requests.post(url, json={"telegram_id": str(telegram_id)}, timeout=10)
    respuesta.raise_for_status()
    return respuesta.json()


# ▸ Devuelve los datos del usuario o None si no está registrado.
async def buscar_usuario_por_telegram(telegram_id: str):
    """Devuelve dict del usuario, None si no existe, o "ERROR_CONSULTA" si n8n falla."""
    url = config.URL_BUSCAR_USUARIO
    if not url:
        raise RuntimeError("Falta configurar URL_BUSCAR_USUARIO en config.py")

    try:
        data = await asyncio.to_thread(_consultar, url, telegram_id)
    except Exception as e:
        print(f"❌ Error de conexión o respuesta en n8n: {e}")
        return "ERROR_CONSULTA"

    # n8n puede responder con una lista de items; vacía = no encontrado.
    if isinstance(data, list):
        if not data:
            return None
        data = data[0]
    if isinstance(data, dict) and isinstance(data.get("json"), dict):
        data = data["json"]

    if not isinstance(data, dict):
        raise ValueError("El webhook de usuarios no devolvió un objeto JSON")

    # Un objeto vacío (búsqueda sin resultados en n8n) significa "no existe".
    if not data:
        return None

    if data.get("encontrado") is True:
        usuario = data.get("usuario") or data
        return usuario if isinstance(usuario, dict) else None

    if data.get("encontrado") is False:
        return None

    if data.get("telegram_id"):
        return data

    raise ValueError("Respuesta de n8n ambigua: indicar encontrado=true/false")
