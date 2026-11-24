# =============================================================================
# registro_local.py — ANTI-DUPLICADOS DE VENTAS
# =============================================================================
# CAPSTONE: Etapa 2: calidad de datos.
# Guarda una 'huella' de cada archivo/cuaderno de ventas cargado, porque cada carga RESTA stock: subir dos veces lo mismo descontaría doble.
# (Explicación del proyecto completo y del modelo en README.md y docs/ARQUITECTURA.md)
# =============================================================================

"""Historial local de ventas ya cargadas (v02.6).

Sirve para avisar si el comerciante sube dos veces el mismo archivo/cuaderno, porque
cada carga RESTA unidades al stock y repetirla descontaría dos veces.
"""
import json
import threading
from pathlib import Path

import config

_lock = threading.Lock()
_MAX_POR_USUARIO = 200


# ▸ Lee el JSON local de huellas.
def _leer() -> dict:
    ruta = Path(config.HISTORIAL_VENTAS_FILE)
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


# ▸ Devuelve cuándo se cargó antes esa huella (o None).
def ya_cargado(telegram_id: str, huella: str):
    """Devuelve el texto de fecha en que se cargó esa misma venta, o None."""
    with _lock:
        return _leer().get(str(telegram_id), {}).get(huella)


# ▸ Anota la carga para avisar si se repite.
def marcar_cargado(telegram_id: str, huella: str, fecha_texto: str) -> None:
    with _lock:
        datos = _leer()
        usuario = datos.setdefault(str(telegram_id), {})
        usuario[huella] = fecha_texto
        while len(usuario) > _MAX_POR_USUARIO:      # el dict conserva el orden de inserción
            usuario.pop(next(iter(usuario)))
        try:
            Path(config.HISTORIAL_VENTAS_FILE).write_text(
                json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8"
            )
        except OSError:
            pass  # el historial es un aviso de comodidad; no debe romper la carga
