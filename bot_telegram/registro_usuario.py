# =============================================================================
# registro_usuario.py — REGISTRO DE USUARIOS Y COMERCIOS (/start)
# =============================================================================
# CAPSTONE: Etapa 1-2: alta del comerciante (su telegram_id es la llave de todo).
# Conversación paso a paso: nombre, apellido, email, teléfono, documento, negocio y ubicación.
# Valida cada dato antes de pasar al siguiente y muestra un resumen para confirmar.
# El telegram_id guardado acá es lo que luego aísla los lotes de cada comerciante.
# (Explicación del proyecto completo y del modelo en README.md y docs/ARQUITECTURA.md)
# =============================================================================

"""Flujo de registro inicial de usuarios y comercios."""
import asyncio
import datetime
import re
import uuid

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove,
)
from telegram.ext import (
    ContextTypes, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, filters,
)

from backend import guardar_usuario_sheets
from menu_principal import enviar_menu_principal, SALUDOS
from usuarios_backend import buscar_usuario_por_telegram
from utils import esc

(REG_NOMBRE, REG_APELLIDO, REG_EMAIL, REG_TELEFONO,
 REG_DOCUMENTO, REG_NEGOCIO, REG_UBICACION, CONFIRMACION) = range(8)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# ▸ Entrada del bot: si el usuario ya existe muestra el menú; si no, inicia el registro.
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Responde a /start o a un saludo y decide si corresponde registrar."""
    telegram_id = str(update.effective_user.id)

    try:
        usuario = await buscar_usuario_por_telegram(telegram_id)
    except Exception as exc:
        print(f"❌ Respuesta inesperada al buscar usuario: {exc}")
        usuario = "ERROR_CONSULTA"

    if usuario == "ERROR_CONSULTA":
        await update.effective_message.reply_text(
            "⚠️ No pude verificar tu registro en este momento.\n"
            "Intentá nuevamente en unos minutos o contactá al administrador."
        )
        return ConversationHandler.END

    if usuario:
        context.user_data["id_usuario_oficial"] = usuario.get("id_usuario")
        nombre = usuario.get("nombre") or update.effective_user.first_name or ""
        await update.effective_message.reply_text(f"👋 ¡Hola, {nombre}! Ya estás registrado en DataByte.")
        await enviar_menu_principal(update.effective_message, context)
        return ConversationHandler.END

    # Usuario no encontrado: comenzar el registro.
    context.user_data.clear()
    await update.effective_message.reply_text(
        "👋 ¡Hola! Bienvenido/a a *DataByte / RescateAlimento*.\n\n"
        "Veo que todavía no estás registrado. Vamos a registrar tu comercio.\n\n"
        "✍️ Ingresá tu *Nombre* (Ej.: Pepe):",
        parse_mode="Markdown",
    )
    return REG_NOMBRE


# ▸ Paso 1: nombre.
async def recibir_nombre(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["nombre"] = update.message.text.strip()
    await update.message.reply_text("Ahora ingresá tu *Apellido*:", parse_mode="Markdown")
    return REG_APELLIDO


# ▸ Paso 2: apellido.
async def recibir_apellido(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["apellido"] = update.message.text.strip()
    await update.message.reply_text(
        "📧 Ingresá tu dirección de *Correo Electrónico*:", parse_mode="Markdown"
    )
    return REG_EMAIL


# ▸ Paso 3: email (se valida el formato).
async def recibir_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    email = update.message.text.strip()
    if not EMAIL_RE.match(email):
        await update.message.reply_text("❌ Correo inválido. Ingresá un email real:")
        return REG_EMAIL

    context.user_data["email"] = email
    await update.message.reply_text(
        "📞 Ingresá tu número de *Teléfono Celular* (solo números):", parse_mode="Markdown"
    )
    return REG_TELEFONO


# ▸ Paso 4: teléfono.
async def recibir_telefono(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tel = update.message.text.strip()
    if not tel.isdigit() or not 8 <= len(tel) <= 15:
        await update.message.reply_text("❌ Ingresá solo números (entre 8 y 15 dígitos):")
        return REG_TELEFONO

    context.user_data["telefono"] = tel

    # Si venía de "Cambiar Teléfono", volvemos al resumen en vez de repetir todo el registro.
    if context.user_data.pop("editando_telefono", False):
        return await mostrar_resumen(update, context)

    await update.message.reply_text(
        "🪪 Ingresá tu número de *Documento de Identidad (DNI)*:", parse_mode="Markdown"
    )
    return REG_DOCUMENTO


# ▸ Paso 5: documento.
async def recibir_documento(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["documento"] = update.message.text.strip()
    await update.message.reply_text(
        "🏪 ¿Cuál es el *Nombre de tu Comercio*? (Ej: Almacén Don Pepe):", parse_mode="Markdown"
    )
    return REG_NEGOCIO


# ▸ Teclado con botón para compartir ubicación.
def _teclado_gps(texto: str) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [[KeyboardButton(texto, request_location=True)]],
        one_time_keyboard=True,
        resize_keyboard=True,
    )


# ▸ Paso 6: nombre del negocio.
async def recibir_negocio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["nombre_negocio"] = update.message.text.strip()
    await update.message.reply_text(
        "📍 Compartí tu *Ubicación Comercial* presionando el botón de abajo:",
        reply_markup=_teclado_gps("📍 Compartir Ubicación Actual"),
        parse_mode="Markdown",
    )
    return REG_UBICACION


# ▸ Paso 7: pide ubicación.
async def pedir_ubicacion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Se llega acá si en el paso de ubicación el usuario escribe texto en vez de compartirla."""
    await update.message.reply_text(
        "📍 Necesito que uses el botón *Compartir Ubicación* de abajo.",
        reply_markup=_teclado_gps("📍 Compartir Ubicación Actual"),
        parse_mode="Markdown",
    )
    return REG_UBICACION


# ▸ Recibe la ubicación enviada desde el mapa.
async def recibir_ubicacion_mapa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    localizacion = update.message.location
    context.user_data["latitud"] = localizacion.latitude
    context.user_data["longitud"] = localizacion.longitude
    # Descripción por coordenadas; no es geocodificación inversa.
    context.user_data["direccion"] = (
        f"Zona Georreferenciada (Lat: {localizacion.latitude:.4f}, Lon: {localizacion.longitude:.4f})"
    )

    await update.message.reply_text("🔄 Procesando coordenadas...", reply_markup=ReplyKeyboardRemove())
    return await mostrar_resumen(update, context)


# ▸ Botones Confirmar / Editar / Cancelar.
def _teclado_resumen() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ Cambiar Teléfono", callback_data="MOD_TEL")],
        [InlineKeyboardButton("📍 Cambiar Ubicación", callback_data="MOD_UBI")],
        [InlineKeyboardButton("✅ Confirmar y Registrar", callback_data="REGISTRAR_OK")],
    ])


# ▸ Muestra los datos para que el usuario los revise.
async def mostrar_resumen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ud = context.user_data
    resumen = (
        "📋 <b>VERIFICACIÓN DE DATOS DE REGISTRO</b>\n\n"
        f"👤 <b>Nombre:</b> {esc(ud['nombre'])} {esc(ud['apellido'])}\n"
        f"📧 <b>Email:</b> {esc(ud['email'])}\n"
        f"📞 <b>Teléfono:</b> {esc(ud['telefono'])}\n"
        f"🪪 <b>Documento:</b> {esc(ud['documento'])}\n"
        f"🏪 <b>Negocio:</b> {esc(ud['nombre_negocio'])}\n"
        f"📍 <b>Coordenadas:</b> {ud['latitud']:.4f}, {ud['longitud']:.4f}\n\n"
        "<i>¿Los datos son correctos o querés corregir algo antes de guardar?</i>"
    )
    await update.effective_message.reply_text(resumen, reply_markup=_teclado_resumen(), parse_mode="HTML")
    return CONFIRMACION


# ▸ Maneja confirmar/editar y guarda el usuario con su telegram_id.
async def procesar_botones_onboarding(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    accion = query.data

    if accion == "MOD_TEL":
        context.user_data["editando_telefono"] = True
        await query.edit_message_text(
            "Escribí tu *nuevo número de teléfono celular*:", parse_mode="Markdown"
        )
        return REG_TELEFONO

    if accion == "MOD_UBI":
        await query.message.reply_text(
            "📍 Enviame tu *nueva ubicación*:",
            reply_markup=_teclado_gps("📍 Compartir Nueva Ubicación"),
            parse_mode="Markdown",
        )
        return REG_UBICACION

    # REGISTRAR_OK
    await query.edit_message_text("⏳ Procesando alta en Google Sheets...")

    ud = context.user_data
    id_usuario = f"USR-{uuid.uuid4().hex[:8].upper()}"
    payload_usuario = {
        "id_usuario": id_usuario,
        "telegram_id": str(query.from_user.id),
        "nombre": ud["nombre"],
        "apellido": ud["apellido"],
        "email": ud["email"],
        "telefono": ud["telefono"],
        "documento": ud["documento"],
        "nombre_negocio": ud["nombre_negocio"],
        "latitud": float(ud["latitud"]),
        "longitud": float(ud["longitud"]),
        "direccion": ud["direccion"],
        "fecha_registro": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    exito = await asyncio.to_thread(guardar_usuario_sheets, payload_usuario)

    if exito:
        await query.message.reply_text(
            f"🎉 *¡REGISTRO COMERCIAL COMPLETADO!*\n\n"
            f"🆔 *ID:* `{id_usuario}`\n"
            "Tu comercio quedó registrado correctamente.",
            parse_mode="Markdown",
        )
        context.user_data.clear()
        context.user_data["id_usuario_oficial"] = id_usuario
        await enviar_menu_principal(query.message, context)
        return ConversationHandler.END

    # Falló el guardado: no perdemos lo cargado, dejamos reintentar.
    await query.message.reply_text(
        "❌ No pude guardar el registro (revisá el nodo de n8n). Podés tocar «Confirmar» para reintentar.",
        reply_markup=_teclado_resumen(),
    )
    return CONFIRMACION


# ▸ Sale del registro con /cancelar.
async def cancelar_registro(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancela el registro inicial."""
    await update.message.reply_text("❌ Registro cancelado.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


# ▸ Define estados y transiciones de la conversación.
def crear_handler_registro_usuario():
    """Construye y devuelve el controlador de la conversación de registro."""
    texto = filters.TEXT & ~filters.COMMAND
    return ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            MessageHandler(filters.TEXT & filters.Regex(SALUDOS), start),
        ],
        states={
            REG_NOMBRE: [MessageHandler(texto, recibir_nombre)],
            REG_APELLIDO: [MessageHandler(texto, recibir_apellido)],
            REG_EMAIL: [MessageHandler(texto, recibir_email)],
            REG_TELEFONO: [MessageHandler(texto, recibir_telefono)],
            REG_DOCUMENTO: [MessageHandler(texto, recibir_documento)],
            REG_NEGOCIO: [MessageHandler(texto, recibir_negocio)],
            REG_UBICACION: [
                MessageHandler(filters.LOCATION, recibir_ubicacion_mapa),
                MessageHandler(texto, pedir_ubicacion),
            ],
            CONFIRMACION: [
                CallbackQueryHandler(procesar_botones_onboarding, pattern=r"^(MOD_TEL|MOD_UBI|REGISTRAR_OK)$")
            ],
        },
        fallbacks=[
            CommandHandler("cancelar", cancelar_registro),
            CommandHandler("start", start),   # permite reiniciar si el usuario queda a mitad de camino
        ],
        name="onboarding_handler",
        persistent=False,
    )
