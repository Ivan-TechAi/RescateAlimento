# =============================================================================
# stock_ventas.py — STOCK Y VENTAS (BOT)
# =============================================================================
# CAPSTONE: Etapa 2-3: actualización de stock y vista del semáforo.
# Carga de ventas (archivo o foto) con vista previa y confirmación; v02.7 además guarda el historial en Ventas_Registradas para el modelo.
# Ver stock: CSV con semáforo verde/naranja/rojo según días al vencimiento.
# (Explicación del proyecto completo y del modelo en README.md y docs/ARQUITECTURA.md)
# =============================================================================

"""Parte 2 del bot: STOCK Y VENTAS (v02.6).

  1. Cargar ventas de hoy  -> archivo .csv/.xlsx del sistema externo, o foto del cuaderno.
                              Descuenta unidades en Lotes_Registrados y actualiza
                              fecha_actualizacion y tiempo_restante (solo esas 3 columnas).
  2. Ver stock actual      -> envía un CSV (Stock_Actual_<fecha>.csv) con los lotes del
                              telegram_id, con semáforo según los días que faltan para vencer.
"""
import asyncio
import logging
import tempfile
import uuid
from pathlib import Path

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    ContextTypes, ConversationHandler, CallbackQueryHandler,
    MessageHandler, CommandHandler, filters,
)

import config
import logica_ventas as LV
import registro_local
import sheets_lotes
import sheets_ventas
from archivos_ventas import leer_archivo_ventas
from cuaderno import CuadernoNoDisponible, leer_cuaderno
from menu_principal import enviar_menu_principal
from utils import dividir_mensaje, fecha_hora_ar

log = logging.getLogger(__name__)

VENTAS_ESPERAR, VENTAS_CONFIRMAR = range(60, 62)
_CLAVES_VENTAS = ("ventas_filas", "ventas_huella", "ventas_origen")
_MAX_BYTES = 5 * 1024 * 1024


# ---------------------------------------------------------------------------
# 1. CARGAR VENTAS DE HOY
# ---------------------------------------------------------------------------
# ▸ Borra datos temporales de la conversación (conserva el origen hasta registrar).
def _limpiar(context):
    for clave in _CLAVES_VENTAS:
        context.user_data.pop(clave, None)


# ▸ Entrada: elegir archivo o cuaderno.
async def iniciar_ventas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _limpiar(context)
    teclado = InlineKeyboardMarkup([
        [InlineKeyboardButton("📄 Subir archivo .csv / .xlsx", callback_data="VENTAS_INFO_ARCHIVO")],
        [InlineKeyboardButton("📓 Foto de mi cuaderno", callback_data="VENTAS_INFO_CUADERNO")],
        [InlineKeyboardButton("⬅️ Volver", callback_data="VENTAS_VOLVER")],
    ])
    await query.message.reply_text(
        "🧾 CARGAR VENTAS DE HOY\n\n"
        "Mandame las ventas del día de alguna de estas formas:\n"
        "• el archivo .csv o .xlsx de tu sistema de ventas, o\n"
        "• una foto de tu cuaderno.\n\n"
        "Tocá una opción para ver cómo prepararla, o mandá directamente el archivo/la foto.\n"
        "Podés cancelar con /cancelar.",
        reply_markup=teclado,
    )
    return VENTAS_ESPERAR


# ▸ Explica el formato del archivo.
async def info_archivo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.reply_text(
        "📄 ARCHIVO DEL SISTEMA DE VENTAS\n\n"
        "Subilo como documento (.csv o .xlsx) con estas columnas:\n"
        "ean, producto, marca, cantidad_unitarias, precio_unidad, fecha_vendio, id_lote\n\n"
        "Lo que se usa para descontar stock es el id_lote y la cantidad_unitarias."
    )
    return VENTAS_ESPERAR


# ▸ Explica qué escribir en el cuaderno.
async def info_cuaderno(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.reply_text(
        "📓 FOTO DE TU CUADERNO\n\n"
        "Anotá una venta por renglón, con estos campos:\n"
        "ean · cantidad_unitaria · precio_unidad · fecha_vendio · id_lote\n"
        "Ejemplo: 7790360026578 | 2 | 7101 | 02/11/2026 | LOT-E1B50FB5\n\n"
        "Con el EAN completamos el producto y la marca. El id_lote lo ves en tu stock "
        "(opción «Ver Stock Actual»).\n\n"
        "Sacá la foto de frente, con buena luz y que se lea cada renglón completo. "
        "Antes de guardar te muestro lo que entendí para que lo confirmes."
    )
    return VENTAS_ESPERAR


# ▸ Pide el archivo o la foto.
async def pedir_ventas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Necesito un archivo .csv/.xlsx (como documento) o una foto del cuaderno. "
        "También podés usar /cancelar."
    )
    return VENTAS_ESPERAR


# ▸ Vuelve al menú principal.
async def volver_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _limpiar(context)
    await enviar_menu_principal(query.message, context)
    return ConversationHandler.END


# ▸ Lee el archivo, valida y muestra vista previa.
async def recibir_archivo_ventas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    documento = update.message.document
    nombre = documento.file_name or "ventas"
    if not nombre.lower().endswith((".csv", ".xlsx")):
        await update.message.reply_text("❌ Formato no soportado. Subí un archivo .csv o .xlsx.")
        return VENTAS_ESPERAR
    if documento.file_size and documento.file_size > _MAX_BYTES:
        await update.message.reply_text("❌ El archivo supera los 5 MB.")
        return VENTAS_ESPERAR

    ruta = Path(tempfile.gettempdir()) / f"ventas_{update.effective_user.id}_{uuid.uuid4().hex[:8]}{Path(nombre).suffix.lower()}"
    try:
        archivo = await documento.get_file()
        await archivo.download_to_drive(custom_path=str(ruta))
        filas = await asyncio.to_thread(leer_archivo_ventas, str(ruta))
    except ValueError as exc:
        await update.message.reply_text(f"❌ {exc}")
        return VENTAS_ESPERAR
    except Exception:
        log.exception("Error leyendo archivo de ventas")
        await update.message.reply_text("❌ No pude leer el archivo. Revisá que no esté dañado.")
        return VENTAS_ESPERAR
    finally:
        ruta.unlink(missing_ok=True)

    return await _mostrar_vista_previa(update, context, filas, f"archivo {nombre}")


# ▸ Transcribe la foto con IA y muestra vista previa.
async def recibir_foto_cuaderno(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📓 Leyendo tu cuaderno... (puede tardar unos segundos)")
    ruta = Path(tempfile.gettempdir()) / f"cuaderno_{update.effective_user.id}_{uuid.uuid4().hex[:8]}.jpg"
    try:
        foto = await update.message.photo[-1].get_file()
        await foto.download_to_drive(custom_path=str(ruta))
        filas = await asyncio.to_thread(leer_cuaderno, str(ruta))
    except CuadernoNoDisponible:
        await update.message.reply_text(
            "⚠️ La lectura de cuaderno todavía no está activada en este bot "
            "(falta ANTHROPIC_API_KEY). Por ahora subí el archivo .csv/.xlsx."
        )
        return VENTAS_ESPERAR
    except ValueError as exc:
        await update.message.reply_text(f"❌ {exc} Probá con otra foto más nítida.")
        return VENTAS_ESPERAR
    except Exception:
        log.exception("Error leyendo cuaderno")
        await update.message.reply_text("❌ No pude leer la foto en este momento. Probá de nuevo.")
        return VENTAS_ESPERAR
    finally:
        ruta.unlink(missing_ok=True)

    return await _mostrar_vista_previa(update, context, filas, "foto del cuaderno")


# ▸ Calcula el plan (sin escribir) y pide confirmación.
async def _mostrar_vista_previa(update, context, filas, origen):
    """Cruza las ventas con el stock y muestra qué se va a cambiar ANTES de escribir nada."""
    telegram_id = str(update.effective_user.id)
    try:
        lotes = await asyncio.to_thread(sheets_lotes.leer_lotes)
    except sheets_lotes.SheetsError as exc:
        log.error("Sheets: %s", exc)
        await update.message.reply_text("❌ No pude conectar con Google Sheets. Avisá al administrador.")
        return VENTAS_ESPERAR

    plan = LV.planificar_ventas(lotes, filas, telegram_id, LV.ahora_local())
    huella = LV.huella_ventas(filas)

    lineas = [f"📋 VENTAS A CARGAR ({origen})", ""]
    if plan["cambios"]:
        lineas.append(f"✅ Se van a actualizar {len(plan['cambios'])} lote(s):")
        for c in plan["cambios"]:
            lineas.append(
                f"• {c['id_lote']} — {c['producto']} ({c['marca']})\n"
                f"  vendidas: {c['vendidas']} → stock {c['cantidad_anterior']} ➜ {c['cantidad']}"
            )
    if plan["errores"]:
        lineas += ["", f"⚠️ {len(plan['errores'])} renglón(es) NO se pueden usar:"]
        lineas += [f"• {e}" for e in plan["errores"]]

    if not plan["cambios"]:
        lineas += ["", "No hay nada para actualizar. Corregí y mandá de nuevo el archivo/foto, o /cancelar."]
        for bloque in dividir_mensaje(lineas):
            await update.message.reply_text(bloque)
        return VENTAS_ESPERAR

    previa = registro_local.ya_cargado(telegram_id, huella)
    if previa:
        lineas += ["", f"⚠️ OJO: estas mismas ventas ya se cargaron el {previa}. "
                       "Si confirmás, se descontarán OTRA VEZ."]
    lineas += ["", "¿Confirmás la carga?"]

    context.user_data["ventas_filas"] = filas
    context.user_data["ventas_huella"] = huella
    context.user_data["ventas_origen"] = origen

    teclado = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Confirmar y actualizar stock", callback_data="VENTAS_OK")],
        [InlineKeyboardButton("❌ Cancelar", callback_data="VENTAS_NO")],
    ])
    bloques = dividir_mensaje(lineas)
    for bloque in bloques[:-1]:
        await update.message.reply_text(bloque)
    await update.message.reply_text(bloques[-1], reply_markup=teclado)
    return VENTAS_CONFIRMAR


# ▸ Escribe en Sheets, registra historial (v02.7) y marca la huella.
async def confirmar_ventas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "VENTAS_NO":
        _limpiar(context)
        await query.edit_message_text("❌ Carga de ventas cancelada. No se modificó el stock.")
        await enviar_menu_principal(query.message, context)
        return ConversationHandler.END

    filas = context.user_data.get("ventas_filas")
    huella = context.user_data.get("ventas_huella")
    if not filas:
        await query.edit_message_text("❌ Se perdieron los datos de la carga. Volvé a subir el archivo.")
        return ConversationHandler.END

    await query.edit_message_text("⏳ Actualizando el stock en Google Sheets...")
    telegram_id = str(query.from_user.id)
    try:
        # Se vuelve a leer y planificar: el stock pudo cambiar entre la vista previa y el "Confirmar".
        lotes = await asyncio.to_thread(sheets_lotes.leer_lotes)
        ahora = LV.ahora_local()
        plan = LV.planificar_ventas(lotes, filas, telegram_id, ahora)
        if not plan["cambios"]:
            await query.message.reply_text("⚠️ El stock cambió y ya no hay nada para actualizar. Revisá y reintentá.")
            return ConversationHandler.END
        await asyncio.to_thread(sheets_lotes.aplicar_cambios, plan["cambios"])
    except sheets_lotes.SheetsError as exc:
        log.error("Sheets: %s", exc)
        await query.message.reply_text("❌ No pude escribir en Google Sheets. No se modificó nada. Avisá al administrador.")
        return ConversationHandler.END

    registro_local.marcar_cargado(telegram_id, huella, fecha_hora_ar(ahora))

    # v02.7: guardar el historial de ventas (alimenta el ritmo de venta del Score y el ROI).
    # Es "mejor esfuerzo": si falla, el stock YA quedó actualizado y solo se avisa en el log.
    if config.REGISTRAR_HISTORIAL_VENTAS:
        try:
            await asyncio.to_thread(
                sheets_ventas.registrar_ventas, plan["cambios"], ahora,
                context.user_data.get("ventas_origen", "")
            )
        except sheets_lotes.SheetsError as exc:
            log.warning("No se pudo guardar el historial de ventas: %s", exc)
    lineas = [f"🎉 ¡Ventas cargadas con éxito!\n🕒 Actualizado: {fecha_hora_ar(ahora)}", ""]
    for c in plan["cambios"]:
        lineas.append(
            f"✅ {c['id_lote']} — {c['producto']} ({c['marca']})\n"
            f"   Stock: {c['cantidad_anterior']} ➜ {c['cantidad']} | vence en: {c['tiempo_restante']}"
        )
    if plan["errores"]:
        lineas += ["", f"⚠️ {len(plan['errores'])} renglón(es) no se cargaron:"] + [f"• {e}" for e in plan["errores"]]

    _limpiar(context)
    for bloque in dividir_mensaje(lineas):
        await query.message.reply_text(bloque)
    await enviar_menu_principal(query.message, context)
    return ConversationHandler.END


# ▸ Cancela sin tocar nada.
async def cancelar_ventas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _limpiar(context)
    await update.effective_message.reply_text("❌ Carga de ventas cancelada.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


# ▸ Define estados de la conversación.
def crear_handler_ventas():
    return ConversationHandler(
        entry_points=[CallbackQueryHandler(iniciar_ventas, pattern=r"^VENTAS_CARGAR$")],
        states={
            VENTAS_ESPERAR: [
                CallbackQueryHandler(info_archivo, pattern=r"^VENTAS_INFO_ARCHIVO$"),
                CallbackQueryHandler(info_cuaderno, pattern=r"^VENTAS_INFO_CUADERNO$"),
                CallbackQueryHandler(volver_menu, pattern=r"^VENTAS_VOLVER$"),
                MessageHandler(filters.Document.ALL, recibir_archivo_ventas),
                MessageHandler(filters.PHOTO, recibir_foto_cuaderno),
                MessageHandler(~filters.COMMAND, pedir_ventas),
            ],
            VENTAS_CONFIRMAR: [CallbackQueryHandler(confirmar_ventas, pattern=r"^VENTAS_(OK|NO)$")],
        },
        fallbacks=[CommandHandler("cancelar", cancelar_ventas)],
        name="ventas_handler",
        persistent=False,
    )


# ---------------------------------------------------------------------------
# 2. VER STOCK ACTUAL
# ---------------------------------------------------------------------------
# ▸ Genera Stock_Actual_<fecha>.csv con semáforo.
async def ver_stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Arma y envía Stock_Actual_<fecha>.csv con los lotes del telegram_id que lo pide."""
    query = update.callback_query
    await query.answer()
    await query.message.reply_text("⏳ Armando tu stock actual...")
    try:
        lotes = await asyncio.to_thread(sheets_lotes.leer_lotes)
    except sheets_lotes.SheetsError as exc:
        log.error("Sheets: %s", exc)
        await query.message.reply_text("❌ No pude conectar con Google Sheets. Avisá al administrador.")
        return

    ahora = LV.ahora_local()
    filas = LV.construir_stock(lotes, str(query.from_user.id), ahora)
    if not filas:
        await query.message.reply_text("📭 No tenés lotes con stock cargados todavía.")
        await enviar_menu_principal(query.message, context)
        return

    cuenta = LV.resumen_semaforo(filas)
    nombre = f"Stock_Actual_{ahora:%Y-%m-%d_%H-%M-%S}.csv"
    await query.message.reply_document(
        document=LV.csv_stock(filas),
        filename=nombre,
        caption=(
            f"📊 Tu stock actual: {len(filas)} lote(s)\n"
            f"🔴 {cuenta['ROJO']} bajar precio ya · 🟠 {cuenta['NARANJA']} bajar un poco · "
            f"🟢 {cuenta['VERDE']} con tiempo"
        ),
    )
    await enviar_menu_principal(query.message, context)


# ▸ Handler del botón Ver Stock.
def crear_handler_stock():
    return CallbackQueryHandler(ver_stock, pattern=r"^STOCK_VER$")
