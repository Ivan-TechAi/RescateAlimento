# =============================================================================
# cuaderno.py — LECTURA DEL CUADERNO MANUSCRITO CON IA
# =============================================================================
# CAPSTONE: Etapa 1-2: ingesta (innovación: comercios sin sistema).
# Usa visión de Claude para transcribir ventas escritas a mano; el comerciante SIEMPRE revisa antes de confirmar.
# (Explicación del proyecto completo y del modelo en README.md y docs/ARQUITECTURA.md)
# =============================================================================

"""Lectura de ventas desde la FOTO de un cuaderno manuscrito (v02.6).

Usa la visión de Claude (API de Anthropic). Requiere ANTHROPIC_API_KEY en .env; sin clave la
opción queda desactivada y el bot lo avisa. Lo leído NUNCA se guarda directo: el comerciante
ve un resumen y confirma antes de tocar el stock (la letra a mano puede leerse mal).
"""
import base64
import json
import re

import cv2

import config
from archivos_ventas import normalizar_filas

PROMPT = """Esta es la foto de un cuaderno donde un comerciante anota sus ventas del día, un renglón por venta.
Extraé cada renglón con estos campos:
- ean: código de barras (solo dígitos)
- id_lote: identificador del lote, con formato LOT- seguido de 8 letras/números (ej. LOT-E1B50FB5)
- cantidad_unitarias: unidades vendidas (número entero)
- precio_unidad: precio por unidad (número)
- fecha_vendido: fecha de la venta (texto tal como está escrita)

Reglas: respondé SOLO con un arreglo JSON, sin texto antes ni después. Si un campo no se lee con
seguridad o no está, poné null; no inventes datos. Ignorá renglones tachados o que no sean ventas.
Ejemplo: [{"ean":"7790360026578","id_lote":"LOT-E1B50FB5","cantidad_unitarias":2,"precio_unidad":7101,"fecha_vendido":"02/11/2026"}]"""


class CuadernoNoDisponible(Exception):
    """No hay ANTHROPIC_API_KEY configurada."""


# ▸ Reduce y codifica la foto antes de enviarla a la IA.
def _preparar_imagen(ruta: str) -> str:
    """Reduce la foto a 1600 px como máximo y la devuelve en base64 (JPEG)."""
    imagen = cv2.imread(ruta)
    if imagen is None:
        raise ValueError("No pude abrir la imagen.")
    alto, ancho = imagen.shape[:2]
    escala = 1600 / max(alto, ancho)
    if escala < 1:
        imagen = cv2.resize(imagen, None, fx=escala, fy=escala, interpolation=cv2.INTER_AREA)
    ok, buffer = cv2.imencode(".jpg", imagen, [cv2.IMWRITE_JPEG_QUALITY, 88])
    if not ok:
        raise ValueError("No pude procesar la imagen.")
    return base64.standard_b64encode(buffer.tobytes()).decode()


# ▸ Convierte el JSON de la IA en filas de ventas.
def parsear_respuesta(texto: str) -> list:
    """Extrae el arreglo JSON de la respuesta del modelo (tolera texto o ``` alrededor)."""
    coincidencia = re.search(r"\[.*\]", texto, re.DOTALL)
    if not coincidencia:
        raise ValueError("No pude interpretar el cuaderno.")
    try:
        datos = json.loads(coincidencia.group(0))
    except ValueError as exc:
        raise ValueError("No pude interpretar el cuaderno.") from exc
    return [d for d in datos if isinstance(d, dict)]


# ▸ Envía la foto a Claude y devuelve las ventas leídas.
def leer_cuaderno(ruta: str) -> list:
    """Foto -> filas de venta normalizadas (mismo formato que el archivo CSV)."""
    if not config.ANTHROPIC_API_KEY:
        raise CuadernoNoDisponible("Falta ANTHROPIC_API_KEY en .env")

    import anthropic
    cliente = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY, timeout=90)
    respuesta = cliente.messages.create(
        model=config.ANTHROPIC_MODEL,
        max_tokens=3000,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                             "data": _preparar_imagen(ruta)}},
                {"type": "text", "text": PROMPT},
            ],
        }],
    )
    texto = "".join(b.text for b in respuesta.content if getattr(b, "type", "") == "text")
    items = parsear_respuesta(texto)
    if not items:
        raise ValueError("No encontré ventas escritas en la foto.")
    # Se garantizan las claves para que normalizar_filas reconozca las columnas.
    for item in items:
        for clave in ("ean", "id_lote", "cantidad_unitarias", "precio_unidad", "fecha_vendido"):
            item.setdefault(clave, None)
    return normalizar_filas(items)
