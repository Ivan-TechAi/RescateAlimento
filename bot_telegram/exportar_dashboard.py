# =============================================================================
# exportar_dashboard.py — FUENTE DE DATOS DEL DASHBOARD (v02.7)
# =============================================================================
# QUÉ HACE
#   Script independiente (no es parte del bot): calcula el Score de Rescate de TODOS los
#   comercios y lo publica en la pestaña "Score_Rescate" del Google Sheet. Esa pestaña es
#   la fuente que se conecta a Looker Studio para el DASHBOARD del Capstone.
#
# CÓMO USARLO
#       python exportar_dashboard.py
#   Se puede programar (cron / Programador de tareas de Windows / un workflow de n8n que
#   ejecute el comando) para que el dashboard se actualice solo, por ejemplo cada hora.
#
# CAPSTONE
#   Etapa 2 (automatización) + Etapa 3 (organizar y visualizar) + Etapa 4 (modelo).
# =============================================================================
import asyncio
import logging

import logica_ventas as LV
import modelo_score as MS
import sheets_lotes
import sheets_ventas
from backend import consultar_multiples_ean
from utils import norm_id

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
log = logging.getLogger("exportar_dashboard")


def main() -> None:
    lotes = sheets_lotes.leer_lotes()
    try:
        historial = MS.normalizar_historial(sheets_ventas.leer_historial())
    except sheets_lotes.SheetsError as exc:      # sin historial el modelo igual funciona
        log.warning("Sin historial de ventas: %s", exc)
        historial = []

    # Una sola consulta de catálogo con todos los EAN de todos los comercios.
    eans = sorted({norm_id(l.get("ean")) for l in lotes if norm_id(l.get("ean"))})
    maestro = asyncio.run(consultar_multiples_ean(eans)) if eans else {}

    ahora = LV.ahora_local()
    marca_tiempo = f"{ahora:%Y-%m-%d %H:%M:%S}"
    salida = []
    for telegram_id in sorted({norm_id(l.get("telegram_id")) for l in lotes}):
        # Se usa el mismo ranking() que el bot: el dashboard y el chat nunca se contradicen.
        for fila in MS.ranking(lotes, telegram_id, maestro, historial, ahora):
            salida.append({**fila, "telegram_id": telegram_id, "fecha_calculo": marca_tiempo,
                           "accion": MS.ACCIONES[fila["accion"]]})

    escritas = sheets_ventas.publicar_score(salida)
    log.info("Score_Rescate actualizado: %s filas.", escritas)


if __name__ == "__main__":
    main()
