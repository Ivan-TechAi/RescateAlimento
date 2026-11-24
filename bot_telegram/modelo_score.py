# =============================================================================
# modelo_score.py — ETAPA 4 DEL CAPSTONE: MODELO DE DECISIÓN ("transformar en acción")
# =============================================================================
# QUÉ HACE
#   Convierte los datos de cada lote (stock, vencimiento, precio, historial de ventas y
#   precio de la competencia) en un RANKING y en una RECOMENDACIÓN concreta:
#   "bajá este lote a $X hoy" / "mantené" / "retirá".
#
# QUÉ TIPO DE MODELO ES (guía del Capstone, punto 4.A "Modelos estadísticos")
#   Combina tres técnicas de la lista A, que es lo que corresponde cuando hay pocos datos:
#     1) SCORE / ÍNDICE COMPUESTO ponderado (40% urgencia + 25% ritmo + 20% valor + 15% precio).
#     2) MEDIA MÓVIL + FORECAST SIMPLE: ritmo de venta = unidades/día de los últimos 7 días,
#        proyectado hasta la fecha de vencimiento para estimar cuánto se perdería (merma).
#     3) REGLAS DE NEGOCIO: umbrales que traducen el score en una acción y un precio sugerido.
#   No se usa Machine Learning a propósito: con pocas ventas por comercio un modelo ML
#   sobreajustaría y no se podría explicar al comerciante por qué se recomienda algo.
#   Cuando haya semanas de historial, el siguiente paso natural es predecir demanda (ML).
#
# POR QUÉ SIRVE AL OBJETIVO DEL PROYECTO (inteligencia competitiva)
#   El componente "Precio" compara el precio del comerciante con el de la COMPETENCIA
#   (catálogo que alimenta n8n) y el descuento sugerido se calcula sobre ese precio de
#   referencia: así la decisión se apoya en datos del mercado, no solo en el vencimiento.
#
# DISEÑO
#   Este módulo es LÓGICA PURA: no usa red, Telegram ni Google Sheets. Recibe listas de
#   dicts y devuelve listas de dicts. Por eso se prueba sola (ver tests/test_modelo_score.py).
# =============================================================================
import csv
import datetime
import io

import config
from backend import clave_ean
from logica_ventas import tiempo_restante
from utils import a_float, norm_id, parsear_fecha

# Columnas del CSV de salida (el orden es el que ve el comerciante / el dashboard).
COLUMNAS_SCORE = [
    "ranking", "id_lote", "ean", "producto", "marca", "cantidad",
    "precio_actual", "precio_referencia", "dias_restantes", "tiempo_restante",
    "ritmo_diario", "merma_proyectada", "valor_en_riesgo",
    "pts_urgencia", "pts_ritmo", "pts_valor", "pts_precio",
    "score", "nivel", "accion", "precio_sugerido", "descuento_sugerido_pct", "datos_usados",
]


def _acotar(x: float, minimo: float = 0.0, maximo: float = 1.0) -> float:
    """Limita x al rango [minimo, maximo]."""
    return max(minimo, min(maximo, x))


# -----------------------------------------------------------------------------
# COMPONENTE 1 — URGENCIA (qué tan cerca está el vencimiento)
# -----------------------------------------------------------------------------
def puntos_urgencia(dias):
    """0-100. Vencido o vence hoy = 100; baja linealmente hasta 0 en el horizonte.

    El horizonte es el doble de DIAS_NARANJA, así el umbral "naranja" del semáforo de
    stock queda en la mitad de la escala (~50 puntos). Devuelve None si no hay fecha.
    """
    if dias is None:
        return None
    horizonte = max(1, config.DIAS_NARANJA * 2)
    return 100.0 * _acotar(1 - dias / horizonte)


# -----------------------------------------------------------------------------
# COMPONENTE 2 — RITMO DE VENTA (media móvil + forecast simple)
# -----------------------------------------------------------------------------
def normalizar_historial(filas_crudas: list) -> list:
    """Convierte las filas de la pestaña Ventas_Registradas en dicts con tipos útiles.

    Cada fila resultante: {telegram_id, ean, cantidad (float), fecha (date)}.
    La fecha es la de la venta (fecha_vendido); si no se puede leer, la de la carga.
    Las filas inválidas se descartan.
    """
    historial = []
    for fila in filas_crudas:
        fecha = parsear_fecha(fila.get("fecha_vendido")) or parsear_fecha(fila.get("fecha_hora"))
        cantidad = a_float(fila.get("cantidad_unitarias"))
        if fecha is None or cantidad <= 0:
            continue
        historial.append({
            "telegram_id": norm_id(fila.get("telegram_id")),
            "ean": norm_id(fila.get("ean")),
            "cantidad": cantidad,
            "fecha": fecha,
        })
    return historial


def ritmo_diario(historial: list, telegram_id, ean, hoy: datetime.date):
    """Unidades vendidas por día de ESE producto en los últimos N días (media móvil).

    Devuelve None cuando el comercio no tiene NINGUNA venta registrada en la ventana:
    no hay evidencia y no se debe inventar un ritmo. En cambio, si el comercio sí vendió
    otras cosas pero de este producto nada, el ritmo es 0 (el producto no rota).
    """
    tid = norm_id(telegram_id)
    ventana = config.VENTANA_RITMO_DIAS
    desde = hoy - datetime.timedelta(days=ventana)
    del_comercio = [h for h in historial
                    if h["telegram_id"] == tid and desde < h["fecha"] <= hoy]
    if not del_comercio:
        return None
    unidades = sum(h["cantidad"] for h in del_comercio if clave_ean(h["ean"]) == clave_ean(ean))
    return unidades / ventana


def merma_proyectada(cantidad: float, ritmo, dias):
    """Forecast simple: unidades que NO se alcanzarían a vender antes de vencer.

    merma = max(0, stock - ritmo * días_de_venta_que_quedan). Hoy cuenta como día de
    venta si el lote vence al final del día. Un lote ya vencido pierde todo.
    """
    if ritmo is None or dias is None:
        return None
    if dias < 0:
        return float(cantidad)
    dias_venta = dias + (1 if config.VENCE_AL_FINAL_DEL_DIA else 0)
    return max(0.0, cantidad - ritmo * dias_venta)


# -----------------------------------------------------------------------------
# COMPONENTE 3 — VALOR EN RIESGO (cuánta plata hay inmovilizada)
# -----------------------------------------------------------------------------
def puntos_valor(valor: float) -> float:
    """0-100. Escala lineal hasta VALOR_LOTE_ALTO (a partir de ahí, máximo)."""
    return 100.0 * _acotar(valor / max(1.0, config.VALOR_LOTE_ALTO))


# -----------------------------------------------------------------------------
# COMPONENTE 4 — POSICIÓN DE PRECIO vs COMPETENCIA (inteligencia competitiva)
# -----------------------------------------------------------------------------
def descuento_objetivo(urgencia: float, merma_frac) -> float:
    """Descuento (sobre el precio de referencia) que corresponde al nivel de urgencia.

    Regla de negocio: urgencia 100 -> DESCUENTO_MAXIMO (50%); se suma hasta 15% extra
    cuando se proyecta que gran parte del lote no se vendería. Tope: DESCUENTO_TOPE.
    """
    extra = 0.15 * (merma_frac or 0.0)
    return min(config.DESCUENTO_TOPE, config.DESCUENTO_MAXIMO * (urgencia / 100.0) + extra)


def puntos_precio(precio_actual: float, referencia, desc_objetivo: float):
    """0-100. Qué tan lejos está el precio propio del descuento que la urgencia exige.

    100 = el comerciante vende al precio de la competencia (o más caro) con el producto
    por vencer; 0 = ya aplicó (o superó) el descuento recomendado.
    Devuelve None si el catálogo no tiene precio de referencia para ese EAN.
    """
    if not referencia or referencia <= 0:
        return None
    desc_actual = 1 - precio_actual / referencia
    return 100.0 * _acotar((desc_objetivo - desc_actual) / config.DESCUENTO_TOPE)


# -----------------------------------------------------------------------------
# COMBINACIÓN (índice compuesto)
# -----------------------------------------------------------------------------
def combinar(componentes: dict):
    """Promedio ponderado de los componentes DISPONIBLES.

    Si falta alguno (p. ej. no hay historial de ventas todavía) se excluye y se
    renormalizan los pesos restantes: el score sigue siendo 0-100 y comparable.
    Devuelve (score, datos_usados) donde datos_usados es la fracción del peso total
    que tuvo datos reales (sirve como indicador de confianza).
    """
    pesos = {
        "urgencia": config.PESO_URGENCIA, "ritmo": config.PESO_RITMO,
        "valor": config.PESO_VALOR, "precio": config.PESO_PRECIO,
    }
    total = sum(pesos.values()) or 1.0
    disponibles = {k: v for k, v in componentes.items() if v is not None}
    peso_disponible = sum(pesos[k] for k in disponibles)
    if peso_disponible == 0:
        return 0.0, 0.0
    score = sum(disponibles[k] * pesos[k] for k in disponibles) / peso_disponible
    return score, peso_disponible / total


# -----------------------------------------------------------------------------
# REGLAS DE NEGOCIO -> ACCIÓN RECOMENDADA
# -----------------------------------------------------------------------------
ACCIONES = {
    "RETIRAR": "Vencido: retirá el lote de la venta.",
    "LIQUIDAR_DONAR": "Vence en el día y no alcanza a venderse: liquidá a precio mínimo o coordiná una donación mientras esté apto.",
    "BAJAR_YA": "Bajá el precio hoy",
    "BAJAR": "Bajá un poco el precio",
    "REFORZAR": "El precio ya es competitivo: destacá el producto (exhibición/promo) para acelerar la venta.",
    "MANTENER": "Mantené el precio: hay tiempo y el ritmo alcanza.",
}


def decidir_accion(nivel, dias, merma_frac, precio_actual, precio_sugerido):
    """Traduce score + contexto en una acción. Reglas en orden de prioridad."""
    if dias is not None and dias < 0:
        return "RETIRAR"
    if (dias is not None and dias <= config.DIAS_LIQUIDAR_DONAR
            and (merma_frac is None or merma_frac >= 0.5)):
        return "LIQUIDAR_DONAR"
    if nivel in ("ROJO", "NARANJA"):
        # Si el precio sugerido no es más bajo que el actual, bajarlo no ayuda:
        # el precio ya es competitivo y hay que reforzar la venta por otro lado.
        if precio_sugerido is None or precio_sugerido >= precio_actual * 0.99:
            return "REFORZAR"
        return "BAJAR_YA" if nivel == "ROJO" else "BAJAR"
    return "MANTENER"


# -----------------------------------------------------------------------------
# CÁLCULO COMPLETO DE UN LOTE
# -----------------------------------------------------------------------------
def calcular_lote(lote: dict, maestro: dict, historial: list, ahora: datetime.datetime):
    """Devuelve el dict de resultados de UN lote (o None si no tiene unidades)."""
    cantidad = a_float(lote.get("cantidad"))
    if cantidad <= 0:
        return None  # lote agotado: no hay nada que decidir

    precio_actual = a_float(lote.get("precio_venta"))
    fecha_cad = parsear_fecha(lote.get("fecha_caducidad"))
    dias = (fecha_cad - ahora.date()).days if fecha_cad else None
    ean = norm_id(lote.get("ean"))

    # Datos externos: precio de la competencia (catálogo) y ritmo de venta propio.
    info = maestro.get(clave_ean(ean)) or {}
    referencia = (info.get("precio_lista") or info.get("precio_min") or 0.0) or None
    ritmo = ritmo_diario(historial, lote.get("telegram_id"), ean, ahora.date())
    merma = merma_proyectada(cantidad, ritmo, dias)
    merma_frac = (merma / cantidad) if merma is not None else None

    # Los cuatro componentes (cada uno 0-100 o None si falta el dato).
    urg = puntos_urgencia(dias)
    d_obj = descuento_objetivo(urg or 0.0, merma_frac)
    comp = {
        "urgencia": urg,
        "ritmo": None if merma_frac is None else 100.0 * merma_frac,
        "valor": puntos_valor(cantidad * precio_actual),
        "precio": puntos_precio(precio_actual, referencia, d_obj),
    }
    score, datos_usados = combinar(comp)

    # Un lote vencido es siempre prioridad máxima, aunque falten otros datos.
    if dias is not None and dias < 0:
        score = 100.0
    nivel = ("ROJO" if score >= config.UMBRAL_SCORE_ROJO
             else "NARANJA" if score >= config.UMBRAL_SCORE_NARANJA else "VERDE")

    # Precio sugerido: descuento objetivo sobre la referencia (o sobre el precio propio si
    # no hay referencia). Nunca se sugiere SUBIR el precio.
    base = referencia or precio_actual
    sugerido = round(min(precio_actual, base * (1 - d_obj)), 2) if precio_actual > 0 else None
    accion = decidir_accion(nivel, dias, merma_frac, precio_actual, sugerido)
    if accion not in ("BAJAR_YA", "BAJAR"):
        sugerido_final = None
        desc_pct = None
    else:
        sugerido_final = sugerido
        desc_pct = round(100 * (1 - sugerido / precio_actual), 1)

    return {
        "id_lote": norm_id(lote.get("id_lote")), "ean": ean,
        "producto": str(lote.get("producto", "")), "marca": str(lote.get("marca", "")),
        "cantidad": int(cantidad), "precio_actual": precio_actual,
        "precio_referencia": referencia, "dias_restantes": dias,
        "tiempo_restante": tiempo_restante(ahora, fecha_cad),
        "ritmo_diario": None if ritmo is None else round(ritmo, 2),
        "merma_proyectada": None if merma is None else round(merma, 1),
        "valor_en_riesgo": round(cantidad * precio_actual, 2),
        "pts_urgencia": _r(comp["urgencia"]), "pts_ritmo": _r(comp["ritmo"]),
        "pts_valor": _r(comp["valor"]), "pts_precio": _r(comp["precio"]),
        "score": round(score, 1), "nivel": nivel, "accion": accion,
        "precio_sugerido": sugerido_final, "descuento_sugerido_pct": desc_pct,
        "datos_usados": round(datos_usados * 100),
    }


def _r(x):
    """Redondea a 1 decimal conservando None."""
    return None if x is None else round(x, 1)


def ranking(lotes: list, telegram_id, maestro: dict, historial: list, ahora: datetime.datetime) -> list:
    """Score de todos los lotes con stock de UN comerciante, del más urgente al menos."""
    tid = norm_id(telegram_id)
    filas = []
    for lote in lotes:
        if norm_id(lote.get("telegram_id")) != tid:
            continue  # cada comerciante solo ve sus propios lotes
        fila = calcular_lote(lote, maestro, historial, ahora)
        if fila:
            filas.append(fila)
    # Desempate: más valor en riesgo primero.
    filas.sort(key=lambda f: (-f["score"], -f["valor_en_riesgo"]))
    for i, fila in enumerate(filas, start=1):
        fila["ranking"] = i
    return filas


# -----------------------------------------------------------------------------
# INDICADORES PARA EL ROI / PITCH (Etapa 6)
# -----------------------------------------------------------------------------
def indicadores(filas: list) -> dict:
    """Totales que sirven para cuantificar el valor del sistema.

    - valor_en_riesgo: plata en lotes de prioridad ROJA o NARANJA (lo que hay que mover).
    - merma_proyectada_valor: valor estimado de lo que se perdería sin actuar (forecast).
    Son ESTIMACIONES basadas en el ritmo reciente: en el pitch hay que presentarlas así.
    """
    en_riesgo = sum(f["valor_en_riesgo"] for f in filas if f["nivel"] in ("ROJO", "NARANJA"))
    merma_valor = sum((f["merma_proyectada"] or 0) * f["precio_actual"] for f in filas)
    return {
        "lotes": len(filas),
        "rojos": sum(1 for f in filas if f["nivel"] == "ROJO"),
        "naranjas": sum(1 for f in filas if f["nivel"] == "NARANJA"),
        "valor_en_riesgo": round(en_riesgo, 2),
        "merma_proyectada_valor": round(merma_valor, 2),
    }


def csv_score(filas: list) -> bytes:
    """CSV (UTF-8 con BOM para Excel) con el ranking y sus componentes (transparencia)."""
    salida = io.StringIO()
    escritor = csv.DictWriter(salida, fieldnames=COLUMNAS_SCORE, extrasaction="ignore")
    escritor.writeheader()
    for fila in filas:
        escritor.writerow({**fila, "accion": ACCIONES.get(fila["accion"], fila["accion"])})
    return salida.getvalue().encode("utf-8-sig")


def explicacion() -> str:
    """Texto para el botón «¿Cómo se calcula?» (usa los pesos reales de la config)."""
    return (
        "ℹ️ CÓMO SE CALCULA EL SCORE DE RESCATE (0 a 100)\n\n"
        f"Score = {config.PESO_URGENCIA:.0%} Urgencia + {config.PESO_RITMO:.0%} Ritmo de venta + "
        f"{config.PESO_VALOR:.0%} Valor en riesgo + {config.PESO_PRECIO:.0%} Precio vs competencia\n\n"
        "• Urgencia: cuánto falta para vencer.\n"
        f"• Ritmo: con lo que vendiste en los últimos {config.VENTANA_RITMO_DIAS} días, ¿alcanzás a vender el lote antes de que venza?\n"
        "• Valor: cuánta plata hay parada en ese lote.\n"
        "• Precio: qué tan lejos está tu precio del descuento que corresponde, comparado con la competencia.\n\n"
        f"🔴 {config.UMBRAL_SCORE_ROJO:.0f}+ actuar hoy · 🟠 {config.UMBRAL_SCORE_NARANJA:.0f}+ bajar un poco · 🟢 menos: mantener.\n"
        "Si todavía no cargaste ventas o el producto no está en el catálogo, ese componente se deja "
        "afuera y se indica en «datos usados»."
    )
