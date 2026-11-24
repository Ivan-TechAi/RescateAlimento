# =============================================================================
# backend.py — CONEXIÓN CON n8n (CATÁLOGO/COMPETENCIA Y GUARDADO)
# =============================================================================
# CAPSTONE: Etapa 1-2: datos de la competencia y automatización.
# Pregunta a n8n por precios de catálogo/competencia de uno o muchos EAN (alimenta precio sugerido y Score).
# Normaliza las respuestas de n8n (que pueden venir en distintas formas) a un diccionario {ean: datos}.
# Envía lotes y usuarios a n8n, que los escribe en Google Sheets.
# Todo el trabajo de red (requests) es bloqueante: el bot lo llama con asyncio.to_thread para no trabarse.
# (Explicación del proyecto completo y del modelo en README.md y docs/ARQUITECTURA.md)
# =============================================================================

"""Módulo de conexión de datos y guardado con n8n para DataByte."""
import asyncio
import datetime
import logging
import uuid

import requests

import config
from utils import a_float

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Búsqueda de productos
# ---------------------------------------------------------------------------
# ▸ Consulta a n8n los datos de UN EAN (catálogo/competencia).
def consultar_competencia(ean):
    """Busca un EAN en el backend de n8n. Devuelve dict o None (función bloqueante)."""
    try:
        respuesta = requests.post(
            config.URL_BUSCAR, json={"ean": str(ean)}, timeout=config.TIMEOUT_HTTP
        )
        if respuesta.status_code != 200:
            return None
        data = respuesta.json()
    except (requests.RequestException, ValueError) as exc:
        log.error("Error consultando EAN %s: %s", ean, exc)
        return None

    # n8n suele devolver una lista de items: [{...}] o [{"json": {...}}]
    if isinstance(data, list):
        data = data[0] if data else None
    if isinstance(data, dict) and isinstance(data.get("json"), dict):
        data = data["json"]
    return data if isinstance(data, dict) else None


# ▸ Unifica el formato del EAN para que '779...' y 779... coincidan.
def clave_ean(ean) -> str:
    """Clave de comparación de EAN: sin espacios ni ceros a la izquierda
    (Google Sheets suele perderlos al guardar el EAN como número)."""
    return str(ean or "").strip().lstrip("0")


# ▸ Convierte la respuesta de n8n (varias formas posibles) en {ean: {producto, marca, precio_lista, precio_min}}.
def normalizar_maestro(data) -> dict:
    """Convierte cualquier forma razonable de respuesta de n8n en
    {clave_ean: {producto, marca, precio_lista, precio_min}}.

    Acepta: dict indexado por EAN, lista de productos, un solo producto, o
    estas estructuras dentro de las claves productos/items/data/resultado(s).
    """
    if not data:
        return {}
    if isinstance(data, dict):
        for clave in ("productos", "items", "data", "resultado", "resultados"):
            if isinstance(data.get(clave), (list, dict)):
                data = data[clave]
                break

    if isinstance(data, dict):
        if "ean" in data and "producto" in data:
            registros = [data]
        else:
            registros = []
            for ean, valor in data.items():
                if isinstance(valor, dict):
                    valor = dict(valor)
                    valor.setdefault("ean", ean)
                    registros.append(valor)
    elif isinstance(data, list):
        registros = [r.get("json", r) if isinstance(r, dict) else r for r in data]
    else:
        registros = []

    maestro = {}
    for reg in registros:
        if not isinstance(reg, dict):
            continue
        ean = reg.get("ean") or reg.get("EAN")
        nombre = reg.get("producto")
        if not ean or not nombre:
            continue
        maestro[clave_ean(ean)] = {
            "producto": str(nombre),
            "marca": str(reg.get("marca") or "Genérico"),
            "precio_lista": a_float(reg.get("precio_lista")),
            "precio_min": a_float(
                reg.get("precio_min_proc")
                or reg.get("precio_min_producto")
                or reg.get("precio_min")
            ),
        }
    return maestro


# ▸ Busca un EAN en el diccionario ya normalizado.
def buscar_en_maestro(maestro: dict, ean):
    return maestro.get(clave_ean(ean))


# ▸ POST bloqueante con todos los EAN en una sola consulta.
def _post_masivo(lista_eans):
    respuesta = requests.post(
        config.URL_BUSCAR_FACTURA_MASIVA,
        json={"eans": lista_eans},
        timeout=config.TIMEOUT_HTTP,
    )
    respuesta.raise_for_status()
    return respuesta.json()


# ▸ Una sola llamada a n8n para muchos EAN; si n8n falla devuelve {} y el bot sigue sin referencia de precio.
async def consultar_multiples_ean(lista_eans):
    """Consulta todos los EAN de una factura en una sola llamada a n8n.

    Devuelve el maestro normalizado (ver normalizar_maestro). Si n8n falla
    devuelve {} y el flujo continúa con datos por defecto.
    """
    try:
        data = await asyncio.to_thread(_post_masivo, lista_eans)
    except (requests.RequestException, ValueError) as exc:
        log.error("Error en la consulta masiva: %s", exc)
        print(f"❌ Error en la consulta masiva: {exc}")
        return {}
    return normalizar_maestro(data)


# ---------------------------------------------------------------------------
# Guardado
# ---------------------------------------------------------------------------
# ▸ Arma el JSON de un lote con las columnas que espera el Sheet.
def construir_payload_lote(*, telegram_id, ean, producto, marca, precio_venta,
                           cantidad, fecha_caducidad, costo_unitario=None,
                           numero_lote_factura=None) -> dict:
    """Arma el payload de un lote con los mismos campos para ambos flujos."""
    payload = {
        "id_lote": f"LOT-{uuid.uuid4().hex[:8].upper()}",
        "telegram_id": str(telegram_id),
        "id_usuario": str(telegram_id),
        "ean": str(ean),
        "fecha_registro": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "producto": producto,
        "marca": marca,
        "precio_venta": float(precio_venta),
        "cantidad": int(cantidad),
        "fecha_caducidad": str(fecha_caducidad),
    }
    if costo_unitario is not None:
        payload["costo_unitario"] = float(costo_unitario)
    if numero_lote_factura is not None:
        payload["numero_lote_factura"] = int(numero_lote_factura)
    return payload


# ▸ POST a n8n; True si respondió 2xx.
def _post_ok(url, payload) -> bool:
    try:
        respuesta = requests.post(url, json=payload, timeout=config.TIMEOUT_HTTP)
        return respuesta.status_code == 200
    except requests.RequestException as exc:
        log.error("Error enviando a %s: %s", url, exc)
        return False


# ▸ Guarda UN lote vía n8n.
def guardar_lote_sheets(payload):
    """Inyecta la fila de stock en la pestaña Lotes_Registrados."""
    return _post_ok(config.URL_REGISTRAR_LOTE, payload)


# ▸ Guarda varios lotes (modo masivo si GUARDADO_MASIVO).
def guardar_lotes_sheets(lista_payloads):
    """Guarda varios lotes. Devuelve (exito_total, ids_de_lotes_fallidos).

    - GUARDADO_MASIVO=True : un solo POST {"lotes": [...]}.
    - GUARDADO_MASIVO=False: un POST por lote, informando cuáles fallaron.
    """
    if config.GUARDADO_MASIVO:
        if _post_ok(config.URL_REGISTRAR_LOTE, {"lotes": lista_payloads}):
            return True, []
        return False, [p["id_lote"] for p in lista_payloads]

    fallidos = [p["id_lote"] for p in lista_payloads if not _post_ok(config.URL_REGISTRAR_LOTE, p)]
    return not fallidos, fallidos


# ▸ Guarda un usuario nuevo vía n8n.
def guardar_usuario_sheets(payload):
    """Inyecta los datos del comercio en la pestaña Usuarios_Registrados."""
    return _post_ok(config.URL_REGISTRAR_USUARIO, payload)
