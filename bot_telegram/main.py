# =============================================================================
# main.py — PUNTO DE ENTRADA DEL BOT
# =============================================================================
# CAPSTONE: Integra todas las etapas.
# Arma la aplicación, registra las conversaciones y el menú, y captura errores sin tirar el bot.
# (Explicación del proyecto completo y del modelo en README.md y docs/ARQUITECTURA.md)
# =============================================================================

"""Punto de entrada del bot DataByte v02.7."""
import logging
import sys

from telegram.ext import Application

import config
from menu_principal import crear_handler_menu
from registro_factura import crear_handler_registro_factura
from registro_lote import crear_handler_registro_lote
from registro_usuario import crear_handler_registro_usuario
from score_bot import crear_handler_score
from stock_ventas import crear_handler_stock, crear_handler_ventas

logging.basicConfig(
    format="%(asctime)s %(name)s %(levelname)s: %(message)s", level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("databyte")


# ▸ Registra el error y avisa al usuario sin caerse.
async def manejar_error(update, context):
    """Evita que una excepción deje al usuario sin respuesta."""
    log.error("Error no controlado", exc_info=context.error)
    if update is not None and getattr(update, "effective_message", None):
        try:
            await update.effective_message.reply_text(
                "⚠️ Ocurrió un error inesperado. Probá de nuevo o escribí /start."
            )
        except Exception:
            pass


# ▸ Construye la app y arranca el polling.
def main():
    if not config.TOKEN_TELEGRAM:
        sys.exit(
            "Falta el token de Telegram. Copiá .env.example a .env y completá TOKEN_TELEGRAM."
        )

    app = Application.builder().token(config.TOKEN_TELEGRAM).build()

    # 1. Conversaciones (tienen prioridad sobre mensajes de texto o botones de entrada)
    app.add_handler(crear_handler_registro_usuario())   # captura /start y los saludos
    app.add_handler(crear_handler_registro_lote())
    app.add_handler(crear_handler_registro_factura())
    app.add_handler(crear_handler_ventas())             # v02.6: Stock y Ventas -> Cargar ventas

    # 2. Botones sueltos (sin conversación)
    app.add_handler(crear_handler_stock())              # v02.6: Stock y Ventas -> Ver stock (CSV)
    app.add_handler(crear_handler_score())              # v02.7: Score de Rescate (modelo de decisión)
    app.add_handler(crear_handler_menu())               # menús

    app.add_error_handler(manejar_error)

    print("🤖 DataByte v02.7: menú, EAN, factura PDF, ventas, stock y Score de Rescate activos.")
    app.run_polling()


if __name__ == "__main__":
    main()