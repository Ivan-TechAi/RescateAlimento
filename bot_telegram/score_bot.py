# =============================================================================
# score_bot.py — OPCIÓN "3. SCORE DE RESCATE" DEL MENÚ (v02.7)
# =============================================================================
# QUÉ HACE (flujo, de punta a punta)
#   1. Lee los lotes del comerciante (Google Sheet).
#   2. Lee su historial de ventas (para el ritmo de venta).
#   3. Consulta a n8n el precio de la COMPETENCIA de esos EAN (catálogo).
#   4. Aplica el modelo (modelo_score.py) y envía:
#        - un resumen con los lotes más urgentes y la acción recomendada, y
#        - el archivo Score_Rescate_<fecha>.csv con el ranking completo y sus componentes.
#
# CAPSTONE
#   Etapa 4 (modelo de decisión: transformar datos en acción) y Etapa 5 (insights).
#
# Si falta el historial de ventas o el catálogo, el modelo igual responde con los datos
# que haya y lo avisa (columna "datos usados"); no se frena.
# =============================================================================
import asyncio
import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackQueryHandler

import logica_ventas as LV
import modelo_score as MS
import sheets_lotes
import sheets_ventas
from backend import consultar_multiples_ean
from menu_principal import enviar_menu_principal
from utils import norm_id

log = logging.getLogger(__name__)

# Cuántos lotes se detallan en el mensaje (el resto va en el CSV).
_TOP_EN_MENSAJE = 5

_ICONO = {"ROJO": "🔴", "NARANJA": "🟠", "VERDE": "🟢"}


def _linea_lote(f: dict) -> str:
    """Texto de UN lote para el mensaje de Telegram."""
    ritmo = "sin ventas cargadas" if f["ritmo_diario"] is None else f"ritmo {f['ritmo_diario']}/día"
    texto = (
        f"{f['ranking']}. {_ICONO[f['nivel']]} {f['score']:.0f}/100 · {f['producto']} ({f['id_lote']})\n"
        f"   Vence en: {f['tiempo_restante']} · quedan {f['cantidad']} un. · {ritmo}\n"
        f"   👉 {MS.ACCIONES[f['accion']]}"
    )
    if f["precio_sugerido"] is not None:
        texto += (f": de ${f['precio_actual']:,.0f} a ${f['precio_sugerido']:,.0f} "
                  f"(−{f['descuento_sugerido_pct']:.0f}%)")
    return texto


async def ver_score(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Botón «Score de Rescate»: calcula y envía el ranking del comerciante que lo pide."""
    query = update.callback_query
    await query.answer()
    await query.message.reply_text("⏳ Calculando tu Score de Rescate...")
    telegram_id = str(query.from_user.id)

    # 1) Lotes (obligatorio: sin esto no hay nada que calcular).
    try:
        lotes = await asyncio.to_thread(sheets_lotes.leer_lotes)
    except sheets_lotes.SheetsError as exc:
        log.error("Sheets: %s", exc)
        await query.message.reply_text("❌ No pude conectar con Google Sheets. Avisá al administrador.")
        return

    # 2) Historial de ventas (opcional: si falla, el modelo trabaja sin el componente Ritmo).
    try:
        historial = MS.normalizar_historial(await asyncio.to_thread(sheets_ventas.leer_historial))
    except sheets_lotes.SheetsError as exc:
        log.warning("Sin historial de ventas: %s", exc)
        historial = []

    # 3) Competencia: precios de referencia de los EAN de este comerciante (1 sola consulta a n8n;
    #    si n8n falla devuelve {} y el modelo deja afuera el componente Precio).
    eans = sorted({norm_id(l.get("ean")) for l in lotes if norm_id(l.get("telegram_id")) == telegram_id})
    maestro = await consultar_multiples_ean(eans) if eans else {}

    # 4) Modelo de decisión.
    ahora = LV.ahora_local()
    filas = MS.ranking(lotes, telegram_id, maestro, historial, ahora)
    if not filas:
        await query.message.reply_text("📭 No tenés lotes con stock para evaluar todavía.")
        await enviar_menu_principal(query.message, context)
        return

    ind = MS.indicadores(filas)
    encabezado = (
        "🎯 SCORE DE RESCATE — tus lotes priorizados\n"
        f"🔴 {ind['rojos']} actuar hoy · 🟠 {ind['naranjas']} bajar un poco · "
        f"🟢 {ind['lotes'] - ind['rojos'] - ind['naranjas']} con tiempo\n"
        f"💰 Plata en lotes de prioridad alta/media: ${ind['valor_en_riesgo']:,.0f}"
    )
    if not historial:
        encabezado += "\nℹ️ Todavía no hay ventas cargadas: el ritmo de venta no se pudo considerar."
    cuerpo = "\n\n".join(_linea_lote(f) for f in filas[:_TOP_EN_MENSAJE])
    pie = f"\n\n(Ranking completo de {len(filas)} lote(s) en el archivo.)" if len(filas) > _TOP_EN_MENSAJE else ""

    teclado = InlineKeyboardMarkup([[InlineKeyboardButton("ℹ️ ¿Cómo se calcula?", callback_data="SCORE_INFO")]])
    await query.message.reply_text(f"{encabezado}\n\n{cuerpo}{pie}")
    await query.message.reply_document(
        document=MS.csv_score(filas),
        filename=f"Score_Rescate_{ahora:%Y-%m-%d_%H-%M-%S}.csv",
        caption="📎 Ranking completo con el detalle de cada componente.",
        reply_markup=teclado,
    )
    await enviar_menu_principal(query.message, context)


async def info_score(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Botón «¿Cómo se calcula?»: explica el modelo con los pesos reales configurados."""
    query = update.callback_query
    await query.answer()
    await query.message.reply_text(MS.explicacion())


def crear_handler_score():
    """Un solo handler para los dos botones (SCORE_VER y SCORE_INFO)."""
    async def _router(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.callback_query.data == "SCORE_INFO":
            return await info_score(update, context)
        return await ver_score(update, context)
    return CallbackQueryHandler(_router, pattern=r"^SCORE_(VER|INFO)$")
