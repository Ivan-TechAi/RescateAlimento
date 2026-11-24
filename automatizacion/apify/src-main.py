import asyncio
import json
import logging
import math
from datetime import date, datetime
from pathlib import Path

import joblib
import pandas as pd
from apify import Actor

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("score-rescate-inferencia")

# Pesos del Score Ponderado de Rescate descritos para DataByte.
WEIGHTS = {"urgencia": 0.40, "ritmo": 0.25, "valor": 0.20, "precio": 0.15}
DEFAULTS = {
    "dias_horizonte": 14,
    "valor_lote_alto": 100000.0,
    "umbral_rojo": 70.0,
    "umbral_naranja": 40.0,
    "descuento_maximo": 0.50,
    "descuento_tope": 0.50,
    "elasticidad_precio": 1.99,
    "dias_donar": 1,
}


def number(value, default=None):
    try:
        if value is None or value == "":
            return default
        result = float(value)
        return result if math.isfinite(result) else default
    except (TypeError, ValueError):
        return default


def parse_date(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value)[:10]).date()
    except ValueError:
        return None


def clamp(value, low=0.0, high=1.0):
    return max(low, min(high, value))


def get_first(row, *keys, default=None):
    for key in keys:
        if row.get(key) is not None and row.get(key) != "":
            return row.get(key)
    return default


def stock_of(row):
    direct = number(get_first(row, "stock_actual", "cantidad", "stock"))
    if direct is not None:
        return max(0.0, direct)
    initial = number(row.get("cantidad_inicial"))
    sold = number(row.get("vendidas"), 0.0)
    waste = number(row.get("merma"), 0.0)
    if initial is not None:
        return max(0.0, initial - sold - waste)
    return 0.0


def build_model_features(row, days_left, stock, price, cost, ref_price, today):
    """Construye las 13 variables esperadas por el Pipeline Gradient Boosting adjunto."""
    initial = number(get_first(row, "cantidad_inicial", "stock_inicial_dia"), stock) or stock
    sold = number(row.get("vendidas"), 0.0) or 0.0
    elapsed = max(1, (today - (parse_date(row.get("fecha_ingreso")) or today)).days + 1)
    observed_daily = sold / elapsed
    price_rel = (price / cost) if cost and cost > 0 else 1.0
    return {
        "precio_rel": price_rel,
        "dias_al_vencimiento": days_left if days_left is not None else 30,
        "stock_inicial_dia": initial,
        "dow": today.weekday(),
        "es_finde": int(today.weekday() >= 5),
        "dia_mes": today.day,
        "ventas_lag1": number(row.get("ventas_lag1"), observed_daily) or 0.0,
        "ventas_lag7": number(row.get("ventas_lag7"), observed_daily * 7) or 0.0,
        "media_movil_7": number(row.get("media_movil_7"), observed_daily) or 0.0,
        "media_movil_28": number(row.get("media_movil_28"), observed_daily) or 0.0,
        "categoria": str(get_first(row, "categoria", default="Sin categoria")),
        "ean": str(get_first(row, "ean", default="")),
        "telegram_id": str(get_first(row, "telegram_id", default="")),
    }


def predict_daily_demand(row, model, days_left, stock, price, cost, ref_price, today):
    supplied = number(get_first(row, "venta_diaria_estimada", "demanda_diaria", "ritmo_diario"))
    if supplied is not None:
        return max(0.0, supplied), "entrada"
    if model is not None:
        features = build_model_features(row, days_left, stock, price, cost, ref_price, today)
        frame = pd.DataFrame([features])
        prediction = float(model.predict(frame)[0])
        return max(0.0, prediction), "modelo_demanda.joblib"
    # Fallback explícito si el artefacto no fue cargado.
    sold = number(row.get("vendidas"), 0.0) or 0.0
    elapsed = max(1, (today - (parse_date(row.get("fecha_ingreso")) or today)).days + 1)
    return max(0.0, sold / elapsed), "heuristica_fallback"


def score_one(row, model, today, settings):
    lot_id = str(get_first(row, "id_lote", default="SIN_ID"))
    stock = stock_of(row)
    price = number(get_first(row, "precio_lista", "precio_venta", "precio_base"), 0.0) or 0.0
    cost = number(row.get("costo"), 0.0) or 0.0
    competitor = number(get_first(row, "precio_competencia", "precio_referencia"), None)
    expiry = parse_date(get_first(row, "fecha_vencimiento", "fecha_caducidad"))
    days_left = int((expiry - today).days) if expiry else number(row.get("dias_para_vencer"))
    days_left = int(days_left) if days_left is not None else None

    if stock <= 0:
        return None

    demand, demand_source = predict_daily_demand(
        row, model, days_left, stock, price, cost, competitor, today
    )
    days_sellable = max(0, days_left or 0) + 1 if days_left is not None else None
    projected_sales = demand * days_sellable if days_sellable is not None else None
    projected_waste = max(0.0, stock - projected_sales) if projected_sales is not None else None
    waste_fraction = (projected_waste / stock) if projected_waste is not None and stock else None

    urgency = None if days_left is None else 100.0 * clamp(
        1.0 - days_left / max(1, settings["dias_horizonte"] * 2)
    )
    pace = None if waste_fraction is None else 100.0 * clamp(waste_fraction)
    value_at_risk = stock * (price if price > 0 else cost)
    value_points = 100.0 * clamp(value_at_risk / max(1.0, settings["valor_lote_alto"]))

    # Brecha competitiva: puntúa cuando el precio actual queda por encima
    # del precio objetivo calculado por urgencia y merma proyectada.
    target_discount = min(
        settings["descuento_tope"],
        settings["descuento_maximo"] * ((urgency or 0.0) / 100.0)
        + 0.15 * (waste_fraction or 0.0),
    )
    reference = competitor if competitor and competitor > 0 else (price if price > 0 else None)
    if reference:
        current_discount = 1.0 - price / reference
        price_points = 100.0 * clamp(
            (target_discount - current_discount) / max(0.01, settings["descuento_tope"])
        )
    else:
        price_points = None

    components = {"urgencia": urgency, "ritmo": pace, "valor": value_points, "precio": price_points}
    available_weight = sum(WEIGHTS[k] for k, v in components.items() if v is not None)
    score = (
        sum(components[k] * WEIGHTS[k] for k in components if components[k] is not None)
        / available_weight
        if available_weight else 0.0
    )
    if days_left is not None and days_left < 0:
        score = 100.0

    if score >= settings["umbral_rojo"]:
        alert = "ROJO"
    elif score >= settings["umbral_naranja"]:
        alert = "NARANJA"
    else:
        alert = "VERDE"

    # Elasticidad-precio: estima el descuento para elevar la demanda hasta
    # el ritmo necesario para vender el stock antes del vencimiento.
    elasticity = max(0.01, settings["elasticidad_precio"])
    elasticity_discount = 0.0
    if days_sellable and demand > 0:
        required_daily = stock / days_sellable
        uplift = required_daily / demand
        if uplift > 1:
            elasticity_discount = 1.0 - (1.0 / uplift) ** (1.0 / elasticity)
    desired_discount = min(settings["descuento_tope"], max(target_discount, elasticity_discount))

    # El precio sugerido nunca supera el precio actual ni cae por debajo del costo.
    base_price = reference or price
    raw_suggested = min(price, base_price * (1.0 - desired_discount)) if price > 0 else 0.0
    suggested = max(cost, raw_suggested) if cost > 0 else max(0.0, raw_suggested)
    suggested = round(suggested, 2) if price > 0 else None

    # La donación se recomienda solamente antes del vencimiento.
    if days_left is not None and days_left < 0:
        action = "MANTENER"
        note = "LOTE_VENCIDO: bloquear venta y gestionar retiro; no donar producto vencido."
    elif days_left is not None and days_left <= settings["dias_donar"] and (waste_fraction is None or waste_fraction >= 0.5):
        action = "DONACION"
        note = "Coordinar donación antes del vencimiento y solo si el alimento sigue apto."
    elif suggested is not None and cost > 0 and suggested <= cost * 1.001 and score >= settings["umbral_naranja"]:
        action = "LIQUIDACION_COSTO"
        note = "Precio limitado por el piso de costo."
    elif suggested is not None and price > 0 and (1 - suggested / price) >= 0.30:
        action = "DESCUENTO_30"
        note = ""
    elif suggested is not None and price > 0 and (1 - suggested / price) >= 0.10:
        action = "DESCUENTO_10"
        note = ""
    else:
        action = "MANTENER"
        note = ""

    return {
        "id_lote": lot_id,
        "ean": str(get_first(row, "ean", default="")),
        "nombre": str(get_first(row, "nombre", "producto", default="")),
        "categoria": str(get_first(row, "categoria", default="")),
        "stock_actual": round(stock, 2),
        "precio_lista": round(price, 2),
        "costo": round(cost, 2),
        "precio_competencia": competitor,
        "dias_para_vencer": days_left,
        "venta_diaria_estimada": round(demand, 4),
        "fuente_demanda": demand_source,
        "merma_proyectada": round(projected_waste, 2) if projected_waste is not None else None,
        "valor_en_riesgo": round(value_at_risk, 2),
        "pts_urgencia": round(urgency, 2) if urgency is not None else None,
        "pts_ritmo": round(pace, 2) if pace is not None else None,
        "pts_valor": round(value_points, 2),
        "pts_precio": round(price_points, 2) if price_points is not None else None,
        "score_rescate": round(score, 2),
        "nivel_alerta": alert,
        "accion_recomendada": action,
        "precio_sugerido": suggested,
        "descuento_sugerido_pct": round((1 - suggested / price) * 100, 2) if suggested is not None and price > 0 else None,
        "datos_usados_pct": round(available_weight * 100, 1),
        "bloqueo_comercial": bool(days_left is not None and days_left < 0),
        "observacion": note,
    }


async def main():
    async with Actor:
        actor_input = await Actor.get_input() or {}
        lots = actor_input.get("lotes", [])
        if not isinstance(lots, list) or not lots:
            raise ValueError('El Input debe contener una lista no vacía en la clave "lotes".')

        today = parse_date(actor_input.get("fecha_referencia")) or date.today()
        settings = DEFAULTS.copy()
        for key in settings:
            if actor_input.get(key) is not None:
                settings[key] = number(actor_input[key], settings[key])

        model_path = Path(__file__).resolve().parent.parent / "modelo_demanda.joblib"
        model = None
        if model_path.exists():
            logger.info("Cargando modelo de demanda: %s", model_path)
            model = joblib.load(model_path)
        else:
            logger.warning("No se encontró modelo_demanda.joblib; se usará fallback si no viene demanda.")

        results = []
        skipped = 0
        for lot in lots:
            if not isinstance(lot, dict):
                skipped += 1
                continue
            result = score_one(lot, model, today, settings)
            if result is None:
                skipped += 1
                continue
            results.append(result)

        results.sort(key=lambda x: (-x["score_rescate"], -x["valor_en_riesgo"]))
        for rank, item in enumerate(results, start=1):
            item["ranking"] = rank
            await Actor.push_data(item)

        summary = {
            "lotes_recibidos": len(lots),
            "lotes_procesados": len(results),
            "lotes_omitidos_sin_stock_o_invalidos": skipped,
            "fecha_referencia": today.isoformat(),
            "modelo_demanda_cargado": model is not None,
            "dataset": "default",
        }
        await Actor.set_value("RESUMEN", summary)
        logger.info("Inferencia terminada: %s", json.dumps(summary, ensure_ascii=False))
        logger.info("Exportá el Dataset default como CSV y guardalo como score_simulado.csv.")


if __name__ == "__main__":
    asyncio.run(main())
