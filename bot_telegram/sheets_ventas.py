# =============================================================================
# sheets_ventas.py — PESTAÑAS NUEVAS DEL GOOGLE SHEET (v02.7)
# =============================================================================
# QUÉ HACE
#   Maneja dos pestañas que NO existían y que no tocan Lotes_Registrados:
#     • Ventas_Registradas : historial de ventas (una fila por lote vendido en cada carga).
#                            Es la materia prima del "ritmo de venta" del modelo de decisión
#                            y de la medición del ROI. Python solo AGREGA filas (append).
#     • Score_Rescate      : resultado del modelo para todos los comercios; la publica
#                            exportar_dashboard.py y es la fuente del dashboard (Looker Studio).
#
# CAPSTONE
#   Etapa 2 (almacenamiento en base de datos) y Etapa 3 (datos listos para visualizar).
#
# Las funciones aceptan un parámetro `hoja` para poder probarse con una hoja falsa.
# =============================================================================
import datetime

import config
import sheets_lotes
from sheets_lotes import SheetsError
from utils import fecha_hora_ar

# Columnas de la pestaña Ventas_Registradas.
COLUMNAS_VENTAS = [
    "fecha_hora", "telegram_id", "id_lote", "ean", "producto", "marca",
    "cantidad_unitarias", "precio_unidad", "fecha_vendido", "origen",
]


def _hoja_ventas(crear: bool):
    """Devuelve la pestaña Ventas_Registradas. Si no existe: la crea (crear=True) o None."""
    import gspread
    libro = sheets_lotes._libro()
    try:
        return libro.worksheet(config.HOJA_VENTAS)
    except gspread.WorksheetNotFound:
        if not crear:
            return None
        hoja = libro.add_worksheet(title=config.HOJA_VENTAS, rows=1000, cols=len(COLUMNAS_VENTAS))
        hoja.append_row(COLUMNAS_VENTAS, value_input_option="RAW")  # encabezado
        return hoja


def registrar_ventas(cambios: list, ahora: datetime.datetime, origen: str, hoja=None) -> int:
    """Agrega al historial una fila por cada lote vendido en la carga. Devuelve cuántas.

    `cambios` es la lista que produce logica_ventas.planificar_ventas (ya validada).
    Es "mejor esfuerzo": quien la llama debe tolerar SheetsError sin deshacer el stock.
    """
    if not cambios:
        return 0
    try:
        ws = hoja or _hoja_ventas(crear=True)
        filas = [[
            fecha_hora_ar(ahora), c["telegram_id"], c["id_lote"], c["ean"], c["producto"],
            c["marca"], c["vendidas"], c.get("precio_unidad") or "",
            c.get("fecha_vendido") or "", origen,
        ] for c in cambios]
        # RAW: se guarda tal cual, sin que Sheets reinterprete fechas ni números.
        ws.append_rows(filas, value_input_option="RAW")
        return len(filas)
    except SheetsError:
        raise
    except Exception as exc:
        raise SheetsError(f"No pude registrar el historial de ventas: {exc}") from exc


def leer_historial(hoja=None) -> list:
    """Lee Ventas_Registradas como lista de dicts. Si la pestaña no existe: lista vacía."""
    try:
        ws = hoja or _hoja_ventas(crear=False)
        if ws is None:
            return []
        valores = ws.get_all_values(
            value_render_option="UNFORMATTED_VALUE",
            date_time_render_option="FORMATTED_STRING",
        )
    except SheetsError:
        raise
    except Exception as exc:
        raise SheetsError(f"No pude leer el historial de ventas: {exc}") from exc
    if not valores:
        return []
    encabezados = [str(h).strip().lower() for h in valores[0]]
    return [
        {h: (fila[i] if i < len(fila) else "") for i, h in enumerate(encabezados) if h}
        for fila in valores[1:] if any(str(c).strip() for c in fila)
    ]


def publicar_score(filas: list, hoja=None) -> int:
    """Reemplaza el contenido de la pestaña Score_Rescate con `filas` (lista de dicts).

    Es una pestaña de SALIDA (se recalcula entera cada vez), pensada para conectar
    Looker Studio. Devuelve la cantidad de filas escritas.
    """
    import modelo_score as MS
    columnas = ["fecha_calculo", "telegram_id"] + MS.COLUMNAS_SCORE
    try:
        ws = hoja
        if ws is None:
            import gspread
            libro = sheets_lotes._libro()
            try:
                ws = libro.worksheet(config.HOJA_SCORE)
            except gspread.WorksheetNotFound:
                ws = libro.add_worksheet(title=config.HOJA_SCORE, rows=1000, cols=len(columnas))
        datos = [columnas] + [
            ["" if f.get(c) is None else f.get(c) for c in columnas] for f in filas
        ]
        ws.clear()
        ws.update(values=datos, range_name="A1", value_input_option="RAW")
        return len(filas)
    except SheetsError:
        raise
    except Exception as exc:
        raise SheetsError(f"No pude publicar Score_Rescate: {exc}") from exc
