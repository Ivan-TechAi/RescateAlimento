# =============================================================================
# registro_factura.py — CARGA DE LOTES DESDE FACTURA PDF
# =============================================================================
# CAPSTONE: Etapa 1-2: ingesta masiva.
# Extrae productos del PDF, cruza con catálogo, deja elegir precio por producto y guarda todos los lotes.
# (Explicación del proyecto completo y del modelo en README.md y docs/ARQUITECTURA.md)
# =============================================================================

"""Carga de factura PDF: extracción de EAN/lotes/unidades/costo, precio por producto y registro.

Flujo v02.6:
  PDF -> catálogo (n8n) -> PRECIO de cada producto (botones de nivel o escrito a mano)
      -> VENCIMIENTO de cada lote -> confirmación -> guardado -> resumen lote por lote.
"""
import asyncio
import re
import tempfile
import uuid
from pathlib import Path

import pdfplumber
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes, ConversationHandler, CallbackQueryHandler,
    MessageHandler, CommandHandler, filters,
)

import config
from backend import (
    buscar_en_maestro, consultar_multiples_ean,
    construir_payload_lote, guardar_lotes_sheets,
)
from menu_principal import enviar_menu_principal
from utils import a_float, dividir_mensaje, esc, fecha_vigente

# v02.6: se agregaron los estados del precio (ELEGIR_PRECIO_ITEM / PRECIO_MANUAL_ITEM)
(ESPERAR_PDF, ELEGIR_PRECIO_ITEM, PRECIO_MANUAL_ITEM,
 FECHA_VENCIMIENTO, CONFIRMAR_FACTURA) = range(40, 45)

_CLAVES_FACTURA = (
    "factura_items", "factura_item_idx",
    "factura_lotes_pendientes", "factura_vencimientos", "factura_telegram_id",
)

# Ejemplo de fila: EAN ... SWIFT 2 60 $ 2.900,00 21% $ 174.000,00
FILA_RE = re.compile(
    r"^\s*(\d{8,14})\s+.*?\b([A-ZÁÉÍÓÚÜÑ][A-ZÁÉÍÓÚÜÑ0-9.-]{1,})\s+"
    r"(\d+)\s+(\d+)\s+\$\s*([\d.]+,\d{2})\s+\d{1,2}%",
    re.IGNORECASE,
)


# ▸ Convierte números con formato argentino.
def _numero_argentino(texto: str) -> float:
    return float(texto.replace(".", "").replace(",", "."))


# ▸ Lee el PDF (pdfplumber) y extrae EAN, lotes, unidades y costo.
def extraer_items_factura(ruta_pdf: str) -> dict:
    """Extrae las columnas operativas de un PDF con texto seleccionable.

    No procesa imágenes escaneadas sin OCR. Solo lee el PDF: no llama a n8n.
    """
    paginas = []
    with pdfplumber.open(ruta_pdf) as pdf:
        for pagina in pdf.pages:
            paginas.append(pagina.extract_text(layout=True) or "")
    texto = "\n".join(paginas)
    if not texto.strip():
        raise ValueError("El PDF no contiene texto seleccionable; hace falta OCR.")

    items = []
    for linea in texto.splitlines():
        coincidencia = FILA_RE.search(linea)
        if not coincidencia:
            continue
        ean, marca_factura, lotes, unidades, costo = coincidencia.groups()

        try:
            costo_unitario = _numero_argentino(costo)
        except ValueError as exc:
            raise ValueError(f"No pude interpretar el costo del EAN {ean}.") from exc
        cantidad_lotes, unidades_por_lote = int(lotes), int(unidades)
        if cantidad_lotes < 1 or unidades_por_lote < 1:
            raise ValueError(f"El EAN {ean} tiene cantidades no válidas.")

        items.append({
            "ean": str(ean),
            "producto": f"Producto EAN {ean}",   # se reemplaza con el nombre del catálogo
            "marca": marca_factura,
            "cantidad_lotes": cantidad_lotes,
            "unidades_por_lote": unidades_por_lote,
            "costo_unitario": costo_unitario,
        })

    if not items:
        raise ValueError("No encontré filas de productos reconocibles en el PDF. Revisá el formato de la factura.")
    return {"items": items, "texto": texto[:5000]}


# ▸ Completa nombre/marca/precios con el catálogo.
def _aplicar_catalogo(item: dict, info) -> None:
    """Completa nombre, marca y precios de referencia del item con los datos del catálogo.

    v02.6: ya NO fija precio_venta acá; el comerciante lo elige para cada producto.
    """
    item["en_catalogo"] = bool(info)
    item["precio_lista"] = 0.0
    item["precio_min"] = 0.0
    if info:
        item["producto"] = info["producto"]
        item["marca"] = info["marca"]
        item["precio_lista"] = info["precio_lista"]
        item["precio_min"] = info["precio_min"]
    # Referencia: el precio de lista; si no hay, el mínimo.
    item["precio_referencia"] = item["precio_lista"] or item["precio_min"]


# ▸ Calcula los niveles de precio ofrecidos por producto.
def niveles_precio(item: dict) -> list:
    """Opciones de precio sugeridas para un producto: [(etiqueta, valor), ...].

    Con referencia del catálogo: Nivel 1 (10% OFF), Nivel 2 (30% OFF) y Nivel 3 (mínimo).
    Sin referencia: una sola sugerencia, costo + margen. Siempre se puede escribir otro precio.
    """
    base = item["precio_referencia"]
    if base > 0:
        n3 = item["precio_min"] if item["precio_min"] > 0 else base * 0.50
        return [
            (f"🟢 Nivel 1 ({int(config.DESCUENTO_NIVEL_1 * 100)}% OFF)", base * (1 - config.DESCUENTO_NIVEL_1)),
            (f"🟡 Nivel 2 ({int(config.DESCUENTO_NIVEL_2 * 100)}% OFF)", base * (1 - config.DESCUENTO_NIVEL_2)),
            ("🔴 Nivel 3 (Al Costo)", n3),
        ]
    margen = int(config.MARGEN_SIN_REFERENCIA * 100)
    return [(f"💡 Sugerido (costo +{margen}%)", item["costo_unitario"] * (1 + config.MARGEN_SIN_REFERENCIA))]


# ---------------------------------------------------------------------------
# Paso 1: recibir el PDF
# ---------------------------------------------------------------------------
# ▸ Entrada desde el menú.
async def iniciar_carga_factura(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    for clave in _CLAVES_FACTURA:
        context.user_data.pop(clave, None)
    await query.message.reply_text(
        "🧾 Adjuntá la factura de compra en PDF como *archivo/documento* (no como foto).\n"
        "Voy a leer EAN, cantidad de lotes, unidades por lote y costo unitario.\n"
        "Podés cancelar con /cancelar.",
        parse_mode="Markdown",
    )
    return ESPERAR_PDF


# ▸ Pide el PDF.
async def pedir_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Respuesta cuando en este paso llega algo que no es un documento."""
    await update.message.reply_text("❌ Enviá la factura como archivo PDF (adjuntar → archivo), o /cancelar.")
    return ESPERAR_PDF


# ▸ Procesa el PDF y arranca la elección de precios.
async def recibir_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    documento = update.message.document
    if (not documento
            or not (documento.file_name or "").lower().endswith(".pdf")
            or documento.mime_type not in (None, "application/pdf")):
        await update.message.reply_text("❌ Enviá un archivo PDF válido como documento.")
        return ESPERAR_PDF
    if documento.file_size and documento.file_size > 15 * 1024 * 1024:
        await update.message.reply_text("❌ El PDF supera el límite de 15 MB.")
        return ESPERAR_PDF

    ruta = Path(tempfile.gettempdir()) / f"factura_{update.effective_user.id}_{uuid.uuid4().hex[:8]}.pdf"
    try:
        archivo = await documento.get_file()
        await archivo.download_to_drive(custom_path=str(ruta))
        await update.message.reply_text("⏳ Leyendo el PDF...")
        resultado = await asyncio.to_thread(extraer_items_factura, str(ruta))
    except Exception as exc:
        await update.message.reply_text(f"❌ Error al leer el PDF: {exc}")
        return ConversationHandler.END
    finally:
        ruta.unlink(missing_ok=True)

    await update.message.reply_text("📡 Consultando catálogo en n8n...")
    maestro = await consultar_multiples_ean([i["ean"] for i in resultado["items"]])

    items = resultado["items"]
    for item in items:
        _aplicar_catalogo(item, buscar_en_maestro(maestro, item["ean"]))

    context.user_data["factura_items"] = items
    context.user_data["factura_item_idx"] = 0
    context.user_data["factura_vencimientos"] = []
    context.user_data["factura_telegram_id"] = str(update.effective_user.id)

    resumen = ["📋 <b>Productos detectados en la factura:</b>", ""]
    sin_catalogo = False
    for item in items:
        aviso = "" if item["en_catalogo"] else " ⚠️ <i>no está en el catálogo</i>"
        sin_catalogo = sin_catalogo or not item["en_catalogo"]
        resumen.append(
            f"• <b>{esc(item['producto'])}</b> ({esc(item['marca'])}){aviso}\n"
            f"  EAN: <code>{esc(item['ean'])}</code> | {item['cantidad_lotes']} lote(s) × {item['unidades_por_lote']} un.\n"
            f"  Costo unit.: ${item['costo_unitario']:,.2f}"
        )
    if sin_catalogo:
        resumen.append("\n⚠️ Los productos sin catálogo usan el nombre de la factura.")
    resumen.append("\nAhora elegí el precio de venta de cada producto.")

    for bloque in dividir_mensaje(resumen):
        await update.message.reply_text(bloque, parse_mode="HTML")
    return await pedir_precio_item(update, context)


# ---------------------------------------------------------------------------
# Paso 2 (nuevo en v02.6): precio de venta de cada producto
# ---------------------------------------------------------------------------
# ▸ Muestra botones de precio del producto actual.
async def pedir_precio_item(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Muestra los precios sugeridos del producto actual (o pasa a los vencimientos si ya no quedan)."""
    items = context.user_data.get("factura_items", [])
    idx = context.user_data.get("factura_item_idx", 0)
    if idx >= len(items):
        _armar_lotes_pendientes(context)
        return await pedir_vencimiento(update, context)

    item = items[idx]
    teclado = [
        [InlineKeyboardButton(f"{etiqueta}: ${valor:,.2f}", callback_data=f"FP_{valor:.2f}")]
        for etiqueta, valor in niveles_precio(item)
    ]
    teclado.append([InlineKeyboardButton("✍️ Escribir otro precio", callback_data="FP_MANUAL")])

    referencia = (
        f"Referencia Súper: ${item['precio_referencia']:,.2f}\n"
        if item["precio_referencia"] > 0 else "Sin precio de referencia en el catálogo.\n"
    )
    await update.effective_message.reply_text(
        f"💵 <b>Precio de venta — producto {idx + 1} de {len(items)}</b>\n\n"
        f"<b>{esc(item['producto'])}</b> ({esc(item['marca'])})\n"
        f"Costo unit.: ${item['costo_unitario']:,.2f}\n"
        f"{referencia}\n"
        "Elegí un precio sugerido o escribí el tuyo:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(teclado),
    )
    return ELEGIR_PRECIO_ITEM


# ▸ Guarda el precio y avanza al siguiente producto.
async def _fijar_precio_y_seguir(update, context, precio: float):
    """Guarda el precio elegido para el producto actual y avanza al siguiente."""
    items = context.user_data["factura_items"]
    idx = context.user_data["factura_item_idx"]
    items[idx]["precio_venta"] = round(precio, 2)
    context.user_data["factura_item_idx"] = idx + 1
    return await pedir_precio_item(update, context)


# ▸ Botón de nivel elegido.
async def capturar_precio_item(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Botón de precio sugerido (FP_<valor>) o 'Escribir otro precio' (FP_MANUAL)."""
    query = update.callback_query
    await query.answer()
    items = context.user_data.get("factura_items")
    if not items:
        await query.edit_message_text("❌ Se perdieron los datos de la factura. Volvé a cargarla.")
        return ConversationHandler.END
    item = items[context.user_data["factura_item_idx"]]

    if query.data == "FP_MANUAL":
        await query.edit_message_text(
            f"✍️ Escribí el precio de venta por unidad para {item['producto']} (Ej: 1500):"
        )
        return PRECIO_MANUAL_ITEM

    precio = a_float(query.data.replace("FP_", ""))
    await query.edit_message_text(f"✅ {item['producto']}: ${precio:,.2f} por unidad")
    return await _fijar_precio_y_seguir(update, context, precio)


# ▸ Precio escrito a mano.
async def procesar_precio_manual_item(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Precio escrito a mano por el comerciante."""
    precio = a_float(update.message.text)
    if precio <= 0:
        await update.message.reply_text("❌ Ingresá un precio numérico mayor a 0 (Ej: 1500):")
        return PRECIO_MANUAL_ITEM

    item = context.user_data["factura_items"][context.user_data["factura_item_idx"]]
    aviso = ""
    if precio < item["costo_unitario"]:
        aviso = f"\n⚠️ Ojo: está por debajo del costo (${item['costo_unitario']:,.2f})."
    await update.message.reply_text(f"✅ {item['producto']}: ${precio:,.2f} por unidad{aviso}")
    return await _fijar_precio_y_seguir(update, context, precio)


# ▸ Arma la lista final de lotes a guardar.
def _armar_lotes_pendientes(context):
    """Un lote por cada lote físico de la factura, con el precio elegido para su producto."""
    pendientes = []
    for item in context.user_data["factura_items"]:
        for numero in range(1, item["cantidad_lotes"] + 1):
            pendientes.append({**item, "numero_lote_producto": numero})
    context.user_data["factura_lotes_pendientes"] = pendientes
    context.user_data["factura_vencimientos"] = []


# ---------------------------------------------------------------------------
# Paso 3: vencimiento de cada lote
# ---------------------------------------------------------------------------
# ▸ Pide vencimiento por producto.
async def pedir_vencimiento(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pendientes = context.user_data.get("factura_lotes_pendientes", [])
    indice = len(context.user_data.get("factura_vencimientos", []))
    if indice >= len(pendientes):
        return await mostrar_confirmacion_factura(update, context)
    item = pendientes[indice]
    await update.effective_message.reply_text(
        f"📅 Vencimiento del lote {indice + 1} de {len(pendientes)}\n\n"
        f"Producto: {item['producto']} ({item['marca']})\n"
        f"Lote de compra #{item['numero_lote_producto']} de {item['cantidad_lotes']} para este EAN\n"
        f"Cantidad: {item['unidades_por_lote']} unidades\n\n"
        "Ingresá la fecha en formato DD/MM/AAAA (ejemplo: 31/12/2026)."
    )
    return FECHA_VENCIMIENTO


# ▸ Valida y guarda el vencimiento.
async def recibir_vencimiento(update: Update, context: ContextTypes.DEFAULT_TYPE):
    fecha = fecha_vigente(update.message.text)
    if fecha is None:
        await update.message.reply_text("❌ Fecha no válida o pasada. Usá DD/MM/AAAA, por ejemplo 31/12/2026.")
        return FECHA_VENCIMIENTO
    context.user_data.setdefault("factura_vencimientos", []).append(fecha.isoformat())
    return await pedir_vencimiento(update, context)


# ---------------------------------------------------------------------------
# Paso 4: confirmar y guardar
# ---------------------------------------------------------------------------
# ▸ Resumen previo a guardar.
async def mostrar_confirmacion_factura(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pendientes = context.user_data["factura_lotes_pendientes"]
    vencimientos = context.user_data["factura_vencimientos"]
    lineas = ["🧾 <b>CONFIRMAR CARGA DE FACTURA</b>", ""]
    for i, (item, fecha) in enumerate(zip(pendientes, vencimientos), start=1):
        lineas.append(
            f"{i}. {esc(item['producto'])} — {item['unidades_por_lote']} un. × "
            f"${item['precio_venta']:,.2f} — vence {fecha}"
        )
    lineas.append("\n¿Confirmás que registre estos lotes?")

    teclado = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Confirmar y guardar", callback_data="FACTURA_CONFIRMAR")],
        [InlineKeyboardButton("❌ Cancelar", callback_data="FACTURA_CANCELAR")],
    ])
    bloques = dividir_mensaje(lineas)
    for bloque in bloques[:-1]:
        await update.effective_message.reply_text(bloque, parse_mode="HTML")
    await update.effective_message.reply_text(bloques[-1], parse_mode="HTML", reply_markup=teclado)
    return CONFIRMAR_FACTURA


# ▸ Bloque '✅ ¡LOTE REGISTRADO!' de cada lote.
def texto_lote_registrado(payload: dict) -> str:
    """Comprobante de UN lote (mismo formato que el alta de producto por EAN)."""
    return (
        "✅ ¡LOTE REGISTRADO!\n\n"
        f"🆔 ID Lote: {payload['id_lote']}\n"
        f"📦 Producto: {payload['producto']} ({payload['marca']})\n"
        f"💵 Precio unitario: ${payload['precio_venta']:,.2f}\n"
        f"🔢 Cantidad: {payload['cantidad']} unidades\n"
        f"📅 Vencimiento: {payload['fecha_caducidad']}"
    )


# ▸ Guarda todos los lotes y muestra el mensaje final.
async def procesar_confirmacion_factura(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "FACTURA_CANCELAR":
        for clave in _CLAVES_FACTURA:
            context.user_data.pop(clave, None)
        await query.edit_message_text("❌ Carga de factura cancelada. No se guardaron lotes.")
        return ConversationHandler.END

    pendientes = context.user_data.get("factura_lotes_pendientes", [])
    vencimientos = context.user_data.get("factura_vencimientos", [])
    if not pendientes or len(pendientes) != len(vencimientos):
        await query.edit_message_text("❌ Los datos de la factura están incompletos. Volvé a cargarla.")
        return ConversationHandler.END

    await query.edit_message_text("⏳ Guardando los lotes en Google Sheets...")
    id_comercio = context.user_data.get("factura_telegram_id") or str(query.from_user.id)

    payloads = [
        construir_payload_lote(
            telegram_id=id_comercio,
            ean=item["ean"],
            producto=item["producto"],
            marca=item["marca"],
            precio_venta=item["precio_venta"],
            cantidad=item["unidades_por_lote"],
            fecha_caducidad=vencimiento,
            costo_unitario=item["costo_unitario"],
            numero_lote_factura=item["numero_lote_producto"],
        )
        for item, vencimiento in zip(pendientes, vencimientos)
    ]

    exito, fallidos = await asyncio.to_thread(guardar_lotes_sheets, payloads)
    registrados = [p for p in payloads if p["id_lote"] not in fallidos]

    # v02.6: mensaje final nuevo + un comprobante por cada lote registrado
    if registrados:
        n = len(registrados)
        titulo = (
            "🎉 ¡Se cargó con éxito la Factura!\n"
            f"📦 Se registró {n} lote" if n == 1 else
            "🎉 ¡Se cargó con éxito la Factura!\n"
            f"📦 Se registraron {n} lotes"
        )
        if fallidos:
            titulo = f"⚠️ Factura cargada parcialmente.\n📦 Se registraron {n} de {len(payloads)} lotes"
        await query.message.reply_text(titulo)
        for bloque in dividir_mensaje([texto_lote_registrado(p) + "\n" for p in registrados]):
            await query.message.reply_text(bloque)
        if fallidos:
            await query.message.reply_text(
                f"❌ No se pudieron guardar: {', '.join(fallidos)}.\n"
                "Revisá Sheets antes de reintentar para no duplicar lotes."
            )
    else:
        await query.message.reply_text(
            "❌ Ocurrió un error al enviar los lotes a n8n. No se guardó nada. Revisá tu servidor."
        )

    for clave in _CLAVES_FACTURA:
        context.user_data.pop(clave, None)
    await enviar_menu_principal(query.message, context)
    return ConversationHandler.END


# ▸ Cancela el flujo.
async def cancelar_factura(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for clave in _CLAVES_FACTURA:
        context.user_data.pop(clave, None)
    await update.effective_message.reply_text("❌ Carga de factura cancelada.")
    return ConversationHandler.END


# ▸ Define estados (40-44).
def crear_handler_registro_factura():
    return ConversationHandler(
        entry_points=[CallbackQueryHandler(iniciar_carga_factura, pattern=r"^CARGA_FACTURA$")],
        states={
            ESPERAR_PDF: [
                MessageHandler(filters.Document.ALL, recibir_pdf),
                MessageHandler(~filters.COMMAND, pedir_pdf),
            ],
            ELEGIR_PRECIO_ITEM: [CallbackQueryHandler(capturar_precio_item, pattern=r"^FP_")],
            PRECIO_MANUAL_ITEM: [MessageHandler(filters.TEXT & ~filters.COMMAND, procesar_precio_manual_item)],
            FECHA_VENCIMIENTO: [MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_vencimiento)],
            CONFIRMAR_FACTURA: [
                CallbackQueryHandler(procesar_confirmacion_factura, pattern=r"^FACTURA_(CONFIRMAR|CANCELAR)$")
            ],
        },
        fallbacks=[CommandHandler("cancelar", cancelar_factura)],
        name="factura_handler",
        persistent=False,
    )
