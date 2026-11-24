# =============================================================================
# registro_lote.py — CARGA DE UN LOTE POR FOTO DEL CÓDIGO DE BARRAS
# =============================================================================
# CAPSTONE: Etapa 1-2: captura manual de lotes.
# Foto del EAN -> catálogo (n8n) -> precio -> cantidad -> vencimiento -> guardado del lote.
# El precio puede elegirse entre niveles sugeridos o escribirse a mano.
# (Explicación del proyecto completo y del modelo en README.md y docs/ARQUITECTURA.md)
# =============================================================================

"""Flujo de escaneo de productos (foto del EAN) y registro de un lote."""
import asyncio
import tempfile
import uuid
from pathlib import Path

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    ContextTypes, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, filters,
)

from backend import consultar_competencia, guardar_lote_sheets, construir_payload_lote
from camara import escanear_foto_bytes
from menu_principal import enviar_menu_principal
from utils import a_float, esc, fecha_vigente

(ESPERAR_FOTO_EAN, ELEGIR_PRECIO, PRECIO_MANUAL,
 INGRESAR_CANTIDAD, INGRESAR_VENCIMIENTO) = range(20, 25)

_CLAVES_LOTE = ("producto_data", "ean", "precio_venta", "cantidad")


# ▸ Entrada desde el menú.
async def iniciar_carga_ean(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Abre la opción de ingresar un producto mediante una foto del EAN."""
    query = update.callback_query
    await query.answer()
    for clave in _CLAVES_LOTE:
        context.user_data.pop(clave, None)
    await query.message.reply_text(
        "📷 Enviá una foto nítida del código de barras del producto.\n"
        "También podés cancelar con /cancelar."
    )
    return ESPERAR_FOTO_EAN


# ▸ Pide la foto del código de barras.
async def pedir_foto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Respuesta cuando en este paso llega algo que no es una imagen."""
    await update.message.reply_text(
        "📷 Necesito una *foto* del código de barras (o /cancelar).",
        parse_mode="Markdown",
    )
    return ESPERAR_FOTO_EAN


# ▸ Lee el EAN, consulta catálogo y ofrece niveles de precio.
async def recibir_foto_lote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Procesa la foto: detecta el EAN, consulta el producto y ofrece precios."""
    telegram_id = str(update.effective_user.id)
    for clave in _CLAVES_LOTE:
        context.user_data.pop(clave, None)
    context.user_data["telegram_id"] = telegram_id

    await update.message.reply_text("📥 Imagen recibida. Buscando el código de barras...")

    mensaje = update.message
    archivo = await (mensaje.photo[-1].get_file() if mensaje.photo else mensaje.document.get_file())
    ruta = Path(tempfile.gettempdir()) / f"lote_{telegram_id}_{uuid.uuid4().hex[:8]}.jpg"
    try:
        await archivo.download_to_drive(custom_path=str(ruta))
        ean_detectado = await asyncio.to_thread(escanear_foto_bytes, str(ruta))
    finally:
        ruta.unlink(missing_ok=True)

    if not ean_detectado:
        await update.message.reply_text(
            "No se encontró ningún código de barras legible. "
            "Enfocá bien las líneas y probá con otra foto (o /cancelar)."
        )
        return ESPERAR_FOTO_EAN

    await update.message.reply_text(
        f"Código detectado: `{ean_detectado}`. Consultando base de datos...",
        parse_mode="Markdown",
    )

    producto_data = await asyncio.to_thread(consultar_competencia, ean_detectado)
    if not producto_data or "producto" not in producto_data:
        await update.message.reply_text(
            f"El código `{ean_detectado}` no figura en los registros de la competencia.",
            parse_mode="Markdown",
        )
        await enviar_menu_principal(update.message, context)
        return ConversationHandler.END

    context.user_data["producto_data"] = producto_data
    context.user_data["ean"] = ean_detectado

    nombre = esc(producto_data.get("producto", "Sin Nombre"))
    marca = esc(producto_data.get("marca", "Genérica"))

    precio_lista = a_float(producto_data.get("precio_lista"))
    precio_min = a_float(producto_data.get("precio_min_producto"))
    precio_base = precio_lista if precio_lista > 0 else precio_min

    # Sin precios de referencia: el comerciante fija el precio a mano.
    if precio_base == 0:
        await update.message.reply_text(
            f"🔎 <b>Producto:</b> {nombre} ({marca})\n"
            "⚠️ El artículo existe pero no tiene precios de referencia.\n\n"
            "✍️ Ingresá el <b>precio de venta</b> por unidad (Ej: <code>1500</code>):",
            parse_mode="HTML",
        )
        return PRECIO_MANUAL

    precio_n1 = precio_base * 0.90
    precio_n2 = precio_base * 0.70
    precio_n3 = precio_min if precio_min > 0 else precio_base * 0.50

    teclado = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🟢 Nivel 1 (10% OFF): ${precio_n1:,.2f}", callback_data=f"LOTE_P_{precio_n1:.2f}")],
        [InlineKeyboardButton(f"🟡 Nivel 2 (30% OFF): ${precio_n2:,.2f}", callback_data=f"LOTE_P_{precio_n2:.2f}")],
        [InlineKeyboardButton(f"🔴 Nivel 3 (Al Costo): ${precio_n3:,.2f}", callback_data=f"LOTE_P_{precio_n3:.2f}")],
    ])
    await update.message.reply_text(
        f"<b>Producto:</b> {nombre} ({marca})\n"
        f"Referencia Súper: ${precio_base:,.2f} ({esc(producto_data.get('comercio', 'Súper'))})\n\n"
        "Elegí el precio sugerido para la venta de este lote:",
        reply_markup=teclado,
        parse_mode="HTML",
    )
    return ELEGIR_PRECIO


# ▸ Recibe el nivel de precio elegido.
async def capturar_precio_lote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    precio = a_float(query.data.replace("LOTE_P_", ""))
    context.user_data["precio_venta"] = precio

    await query.edit_message_text(f"✅ Precio de venta fijado: ${precio:,.2f}")
    await query.message.reply_text("🔢 Ahora ingresá la cantidad de unidades del lote:")
    return INGRESAR_CANTIDAD


# ▸ Valida un precio escrito a mano.
async def procesar_precio_manual(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Precio escrito a mano cuando no hay referencia en el sistema."""
    precio = a_float(update.message.text)
    if precio <= 0:
        await update.message.reply_text("❌ Ingresá un precio numérico mayor a 0 (Ej: 1500):")
        return PRECIO_MANUAL

    context.user_data["precio_venta"] = precio
    await update.message.reply_text(
        f"✅ Precio fijado en ${precio:,.2f}.\n\n🔢 Ahora ingresá la cantidad de unidades del lote:"
    )
    return INGRESAR_CANTIDAD


# ▸ Valida la cantidad (entero positivo).
async def capturar_cantidad_lote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = update.message.text.strip()
    if not texto.isdigit() or int(texto) < 1:
        await update.message.reply_text("❌ Entrada inválida. Ingresá un número entero mayor a 0 (Ej: 24):")
        return INGRESAR_CANTIDAD

    context.user_data["cantidad"] = int(texto)
    await update.message.reply_text(
        "📅 Ingresá la fecha de caducidad del lote (Ej: 31/12/2026 o 2026-12-31):"
    )
    return INGRESAR_VENCIMIENTO


# ▸ Valida la fecha, arma el lote y lo guarda.
async def capturar_vencimiento_lote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    fecha = fecha_vigente(update.message.text)
    if fecha is None:
        await update.message.reply_text(
            "❌ Fecha no válida o ya vencida. Usá DD/MM/AAAA o AAAA-MM-DD (Ej: 31/12/2026):"
        )
        return INGRESAR_VENCIMIENTO

    ud = context.user_data
    if not all(k in ud for k in _CLAVES_LOTE):
        await update.message.reply_text("❌ Se perdieron los datos del lote. Empezá de nuevo desde el menú.")
        await enviar_menu_principal(update.message, context)
        return ConversationHandler.END

    await update.message.reply_text("⏳ Guardando lote en Google Sheets...")

    prod = ud["producto_data"]
    payload = construir_payload_lote(
        telegram_id=update.effective_user.id,
        ean=ud["ean"],
        producto=prod.get("producto", "Producto Sin Nombre"),
        marca=prod.get("marca", "Genérico"),
        precio_venta=ud["precio_venta"],
        cantidad=ud["cantidad"],
        fecha_caducidad=fecha.isoformat(),
    )

    exito = await asyncio.to_thread(guardar_lote_sheets, payload)

    if exito:
        await update.message.reply_text(
            "✅ ¡LOTE REGISTRADO!\n\n"
            f"🆔 ID Lote: {payload['id_lote']}\n"
            f"📦 Producto: {payload['producto']} ({payload['marca']})\n"
            f"💵 Precio unitario: ${payload['precio_venta']:,.2f}\n"
            f"🔢 Cantidad: {payload['cantidad']} unidades\n"
            f"📅 Vencimiento: {payload['fecha_caducidad']}\n\n"
            "El lote quedó vinculado a tu cuenta de comercio."
        )
    else:
        await update.message.reply_text("❌ Ocurrió un error al registrar el lote en n8n. Revisá el workflow.")

    for clave in _CLAVES_LOTE:
        ud.pop(clave, None)
    await enviar_menu_principal(update.message, context)
    return ConversationHandler.END


# ▸ Cancela la carga.
async def cancelar_lote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancela el registro del lote."""
    for clave in _CLAVES_LOTE:
        context.user_data.pop(clave, None)
    await update.message.reply_text(
        "❌ Operación cancelada.",
        reply_markup=ReplyKeyboardRemove(),
    )
    return ConversationHandler.END


# ▸ Define estados de la conversación.
def crear_handler_registro_lote():
    """Construye y devuelve el controlador de la conversación de lotes."""
    texto = filters.TEXT & ~filters.COMMAND
    return ConversationHandler(
        entry_points=[CallbackQueryHandler(iniciar_carga_ean, pattern=r"^CARGA_EAN$")],
        states={
            ESPERAR_FOTO_EAN: [
                MessageHandler(filters.PHOTO | filters.Document.IMAGE, recibir_foto_lote),
                MessageHandler(~filters.COMMAND, pedir_foto),
            ],
            ELEGIR_PRECIO: [CallbackQueryHandler(capturar_precio_lote, pattern=r"^LOTE_P_")],
            PRECIO_MANUAL: [MessageHandler(texto, procesar_precio_manual)],
            INGRESAR_CANTIDAD: [MessageHandler(texto, capturar_cantidad_lote)],
            INGRESAR_VENCIMIENTO: [MessageHandler(texto, capturar_vencimiento_lote)],
        },
        fallbacks=[CommandHandler("cancelar", cancelar_lote)],
        name="stock_handler",
        persistent=False,
    )
