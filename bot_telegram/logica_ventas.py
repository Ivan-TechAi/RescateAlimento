# =============================================================================
# logica_ventas.py — LÓGICA PURA DE STOCK Y VENTAS
# =============================================================================
# CAPSTONE: Etapa 2-3.
# Sin Telegram ni red: descuenta cantidades, calcula tiempo restante y arma el semáforo. Por eso se puede probar sola.
# (Explicación del proyecto completo y del modelo en README.md y docs/ARQUITECTURA.md)
# =============================================================================

"""Lógica pura de Stock y Ventas (v02.6): sin Telegram ni red, para poder probarla sola.

Regla del diagrama: se busca el lote por id_lote y se hace
    cantidad          = cantidad - cantidad_unitarias
    fecha_actualizacion = fecha y hora en que se sube el archivo (automática)
    tiempo_restante   = fecha_caducidad - fecha_actualizacion
Solo se cambian esas tres columnas, y solo de los lotes del telegram_id que sube las ventas.
"""
import csv
import datetime
import hashlib
import io
import json

from dateutil.relativedelta import relativedelta

import config
from backend import clave_ean
from utils import a_float, fecha_hora_ar, norm_id, parsear_fecha


# ▸ Hora actual en Argentina (no la del servidor).
def ahora_local() -> datetime.datetime:
    """Fecha y hora actual en la zona horaria del bot, sin tzinfo (para restar con fechas del Sheet)."""
    return datetime.datetime.now(config.ZONA_HORARIA).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# tiempo_restante
# ---------------------------------------------------------------------------
# ▸ Instante en que vence (fin del día si VENCE_AL_FINAL_DEL_DIA).
def _momento_vencimiento(fecha_cad: datetime.date) -> datetime.datetime:
    hora = datetime.time(23, 59, 59) if config.VENCE_AL_FINAL_DEL_DIA else datetime.time.min
    return datetime.datetime.combine(fecha_cad, hora)


# ▸ Texto 'X años, Y meses, Z días, H horas' hasta el vencimiento.
def tiempo_restante(ahora: datetime.datetime, fecha_cad) -> str:
    """Texto con lo que falta para vencer: '1 año, 2 meses, 24 días, 3 horas'.

    Las unidades en cero se omiten (los años solo aparecen si hace falta). 'Vencido' si ya pasó.
    """
    if fecha_cad is None:
        return ""
    fin = _momento_vencimiento(fecha_cad)
    if fin <= ahora:
        return "Vencido"
    rd = relativedelta(fin, ahora)
    partes = []
    for valor, singular, plural in (
        (rd.years, "año", "años"),
        (rd.months, "mes", "meses"),
        (rd.days, "día", "días"),
        (rd.hours, "hora", "horas"),
    ):
        if valor:
            partes.append(f"{valor} {singular if valor == 1 else plural}")
    return ", ".join(partes) or "Menos de 1 hora"


# ---------------------------------------------------------------------------
# Cargar ventas
# ---------------------------------------------------------------------------
# ▸ Hash del contenido para detectar cargas repetidas.
def huella_ventas(filas: list) -> str:
    """Identificador estable de un conjunto de ventas (no depende del orden de los renglones)."""
    claves = sorted(
        (f.get("id_lote", ""), clave_ean(f.get("ean")), f.get("cantidad_unitarias", 0),
         f.get("fecha_vendido", ""), f.get("precio_unidad", 0))
        for f in filas
    )
    return hashlib.sha256(json.dumps(claves, ensure_ascii=False).encode()).hexdigest()[:20]


# ▸ Calcula los cambios SIN escribir; rechaza lotes ajenos, inexistentes o sin stock suficiente.
def planificar_ventas(lotes: list, filas: list, telegram_id, ahora: datetime.datetime) -> dict:
    """Cruza las ventas con los lotes del comerciante.

    Devuelve {"cambios": [...], "errores": [...]}. Un renglón con problema NO frena a los demás:
    queda en `errores` y se explica. Nada se escribe acá.
    """
    tid = norm_id(telegram_id)
    # Seguridad: un comerciante solo puede tocar SUS lotes.
    mios = [l for l in lotes if norm_id(l.get("telegram_id")) == tid]
    por_id = {norm_id(l["id_lote"]).upper(): l for l in mios}

    errores = []
    acumulado = {}   # id_lote -> {"lote", "unidades", "precio", "fecha"}

    for fila in filas:
        n = fila.get("_n", "?")
        unidades = fila.get("cantidad_unitarias", 0)
        if unidades <= 0 or unidades != int(unidades):
            errores.append(f"Renglón {n}: la cantidad no es válida ({unidades or 'vacía'}).")
            continue
        unidades = int(unidades)

        id_lote = fila.get("id_lote", "")
        if id_lote:
            lote = por_id.get(id_lote)
            if lote is None:
                errores.append(f"Renglón {n}: el lote {id_lote} no existe en tu stock.")
                continue
            ean_fila = clave_ean(fila.get("ean"))
            if ean_fila and ean_fila != clave_ean(lote.get("ean")):
                errores.append(
                    f"Renglón {n}: el EAN {fila.get('ean')} no coincide con el del lote {id_lote}."
                )
                continue
        else:
            # Sin id_lote (típico del cuaderno): se intenta resolver por EAN, solo si no hay dudas.
            ean_fila = clave_ean(fila.get("ean"))
            if not ean_fila:
                errores.append(f"Renglón {n}: falta el id_lote y el EAN.")
                continue
            candidatos = [
                l for l in mios
                if clave_ean(l.get("ean")) == ean_fila and a_float(l.get("cantidad")) > 0
            ]
            if not candidatos:
                errores.append(f"Renglón {n}: no tenés stock con el EAN {fila.get('ean')}.")
                continue
            if len(candidatos) > 1:
                ids = ", ".join(norm_id(c["id_lote"]) for c in candidatos[:5])
                errores.append(
                    f"Renglón {n}: el EAN {fila.get('ean')} está en varios lotes ({ids}); indicá el id_lote."
                )
                continue
            lote = candidatos[0]

        clave = norm_id(lote["id_lote"]).upper()
        item = acumulado.setdefault(clave, {"lote": lote, "unidades": 0, "precio": 0.0, "fecha": ""})
        item["unidades"] += unidades        # varias ventas del mismo lote en el archivo se suman
        item["precio"] = fila.get("precio_unidad") or item["precio"]
        item["fecha"] = fila.get("fecha_vendido") or item["fecha"]

    cambios = []
    fecha_act = fecha_hora_ar(ahora)
    for clave, item in acumulado.items():
        lote = item["lote"]
        actual = int(a_float(lote.get("cantidad")))
        if item["unidades"] > actual:
            errores.append(
                f"Lote {clave}: se informan {item['unidades']} unidades vendidas pero solo hay {actual} en stock."
            )
            continue
        fecha_cad = parsear_fecha(lote.get("fecha_caducidad"))
        cambios.append({
            "_fila": lote["_fila"],
            "id_lote": clave,
            "producto": str(lote.get("producto", "")),
            "marca": str(lote.get("marca", "")),
            "ean": norm_id(lote.get("ean")),            # v02.7: para el historial de ventas
            "telegram_id": norm_id(lote.get("telegram_id")),
            "fecha_vendido": item["fecha"],             # v02.7: fecha informada de la venta
            "vendidas": item["unidades"],
            "cantidad_anterior": actual,
            "cantidad": actual - item["unidades"],
            "precio_unidad": item["precio"],
            "fecha_actualizacion": fecha_act,
            "tiempo_restante": tiempo_restante(ahora, fecha_cad),
        })
    return {"cambios": cambios, "errores": errores}


# ---------------------------------------------------------------------------
# Ver stock
# ---------------------------------------------------------------------------
COLUMNAS_STOCK = ["id_lote", "ean", "producto", "marca", "precio_venta", "cantidad", "tiempo_restante", "estado"]


# ▸ Semáforo por días: verde / naranja / rojo.
def clasificar(dias):
    """Semáforo según los días que faltan para vencer. Devuelve (color, texto)."""
    if dias is None:
        return "SIN_FECHA", "⚪ SIN FECHA DE VENCIMIENTO"
    if dias < 0:
        return "ROJO", "🔴 ROJO - VENCIDO: bajar el precio inmediatamente"
    if dias <= config.DIAS_ROJO:
        cuando = "vence hoy" if dias == 0 else f"vence en {dias} día{'s' if dias != 1 else ''}"
        return "ROJO", f"🔴 ROJO - {cuando}: bajar el precio inmediatamente"
    if dias <= config.DIAS_NARANJA:
        return "NARANJA", f"🟠 NARANJA - vence en {dias} días: disminuir un poco el precio"
    return "VERDE", "🟢 VERDE - falta vencer mucho"


# ▸ Filas de stock del comerciante ordenadas por urgencia.
def construir_stock(lotes: list, telegram_id, ahora: datetime.datetime) -> list:
    """Filas del stock actual del comerciante (solo lotes con unidades), lo más urgente primero.

    tiempo_restante se calcula AL MOMENTO de pedir el stock (no se lee del Sheet) para que
    siempre esté al día, aunque no haya ventas nuevas.
    """
    tid = norm_id(telegram_id)
    filas = []
    for lote in lotes:
        if norm_id(lote.get("telegram_id")) != tid:
            continue
        if a_float(lote.get("cantidad")) <= 0:
            continue
        fecha_cad = parsear_fecha(lote.get("fecha_caducidad"))
        dias = (fecha_cad - ahora.date()).days if fecha_cad else None
        color, estado = clasificar(dias)
        filas.append({
            "id_lote": norm_id(lote["id_lote"]),
            "ean": norm_id(lote.get("ean")),
            "producto": str(lote.get("producto", "")),
            "marca": str(lote.get("marca", "")),
            "precio_venta": _num(a_float(lote.get("precio_venta"))),
            "cantidad": int(a_float(lote.get("cantidad"))),
            "tiempo_restante": tiempo_restante(ahora, fecha_cad),
            "estado": estado,
            "_color": color,
            "_dias": dias,
        })
    filas.sort(key=lambda f: (f["_dias"] is None, f["_dias"] if f["_dias"] is not None else 0))
    return filas


# ▸ Entero si no tiene decimales.
def _num(x: float):
    """2280.0 -> 2280 (sin decimales de más en el CSV)."""
    return int(x) if float(x).is_integer() else round(x, 2)


# ▸ Conteo por color.
def resumen_semaforo(filas: list) -> dict:
    cuenta = {"ROJO": 0, "NARANJA": 0, "VERDE": 0, "SIN_FECHA": 0}
    for f in filas:
        cuenta[f["_color"]] += 1
    return cuenta


# ▸ CSV (UTF-8 con BOM para Excel).
def csv_stock(filas: list) -> bytes:
    """CSV listo para abrir en Excel (UTF-8 con BOM para que se vean bien tildes y emojis)."""
    salida = io.StringIO()
    escritor = csv.DictWriter(salida, fieldnames=COLUMNAS_STOCK, extrasaction="ignore")
    escritor.writeheader()
    escritor.writerows(filas)
    return salida.getvalue().encode("utf-8-sig")
