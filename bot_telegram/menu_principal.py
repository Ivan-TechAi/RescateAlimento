# =============================================================================
# menu_principal.py — MENÚS DE TELEGRAM
# =============================================================================
# CAPSTONE: Interfaz del comerciante.
# Menú principal: 1 Cargar productos, 2 Stock y Ventas, 3 Score de Rescate (v02.7), 4 Notificaciones (pendiente).
# (Explicación del proyecto completo y del modelo en README.md y docs/ARQUITECTURA.md)
# =============================================================================

"""Menús de Telegram para DataByte."""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackQueryHandler

# Patrón de saludos reconocidos (lo usa registro_usuario como punto de entrada).
SALUDOS = r"(?i)^\s*(hola+|holi+|buenas?\b.*|buenos?\s+d[ií]as\b.*|buenas?\s+tardes\b.*|buenas?\s+noches\b.*|qué tal\b.*|que tal\b.*|hey\b.*|hello\b.*)\s*$"


# ▸ Muestra el menú principal.
async def enviar_menu_principal(mensaje, context: ContextTypes.DEFAULT_TYPE):
    """Muestra las funciones principales disponibles."""
    teclado = InlineKeyboardMarkup([
        [InlineKeyboardButton("📦 1. Cargar productos", callback_data="MENU_CARGAR")],
        # v02.6: "Ver stock" pasó a ser "Stock y Ventas" (submenú con 2 opciones)
        [InlineKeyboardButton("📊 2. Stock y Ventas", callback_data="MENU_STOCK")],
        # v02.7: "Score" ahora es el modelo de decisión (score_bot.py): ranking de lotes + acción recomendada
        [InlineKeyboardButton("🎯 3. Score de Rescate", callback_data="SCORE_VER")],
        [InlineKeyboardButton("🔔 4. Notificaciones", callback_data="MENU_NOTIFICACIONES")],
    ])
    await mensaje.reply_text("¿Qué querés hacer? Elegí una opción:", reply_markup=teclado)


# ▸ Enruta los botones del menú y submenú.
async def procesar_menu(update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "MENU_CARGAR":
        teclado = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔎 1. Ingresar producto por EAN", callback_data="CARGA_EAN")],
            [InlineKeyboardButton("🧾 2. Cargar factura de compra (PDF)", callback_data="CARGA_FACTURA")],
            [InlineKeyboardButton("⬅️ Volver al menú principal", callback_data="VOLVER_MENU")],
        ])
        await query.message.reply_text(
            "📦 *CARGAR PRODUCTOS*\nElegí cómo querés ingresar la mercadería:",
            reply_markup=teclado,
            parse_mode="Markdown",
        )
    elif query.data == "MENU_STOCK":
        # Los botones abren: VENTAS_CARGAR -> stock_ventas.crear_handler_ventas()
        #                    STOCK_VER     -> stock_ventas.crear_handler_stock()
        teclado = InlineKeyboardMarkup([
            [InlineKeyboardButton("🧾 1. Cargar Ventas de Hoy", callback_data="VENTAS_CARGAR")],
            [InlineKeyboardButton("📋 2. Ver Stock Actual", callback_data="STOCK_VER")],
            [InlineKeyboardButton("⬅️ Volver al menú principal", callback_data="VOLVER_MENU")],
        ])
        await query.message.reply_text(
            "📊 *STOCK Y VENTAS*\nElegí una opción:",
            reply_markup=teclado,
            parse_mode="Markdown",
        )
    elif query.data == "VOLVER_MENU":
        await enviar_menu_principal(query.message, context)
    elif query.data == "MENU_NOTIFICACIONES":
        # Sigue siendo un marcador de posición (próxima versión).
        await query.message.reply_text(
            "La opción *Notificaciones* todavía no está conectada. "
            "Está prevista para una próxima versión.",
            parse_mode="Markdown",
        )


# ▸ Registra el handler del menú.
def crear_handler_menu():
    return CallbackQueryHandler(
        procesar_menu,
        pattern=r"^(MENU_CARGAR|MENU_STOCK|MENU_NOTIFICACIONES|VOLVER_MENU)$",
    )
