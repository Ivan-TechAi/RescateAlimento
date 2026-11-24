# =============================================================================
# sheets_lotes.py — ACCESO A Lotes_Registrados (GOOGLE SHEETS)
# =============================================================================
# CAPSTONE: Etapa 2: almacenamiento.
# Lee todos los lotes y SOLO escribe cantidad, fecha_actualizacion y tiempo_restante (regla del proyecto: el resto no se toca).
# (Explicación del proyecto completo y del modelo en README.md y docs/ARQUITECTURA.md)
# =============================================================================

"""Acceso a la pestaña Lotes_Registrados de Google Sheets (v02.6).

- LEER: devuelve todas las filas como dicts (+ "_fila" = número de fila real en la hoja).
- ESCRIBIR: SOLO las columnas cantidad, fecha_actualizacion y tiempo_restante. Las demás
  columnas no se tocan nunca (se escribe celda por celda con batch_update, no se reemplaza la hoja).

Requiere una cuenta de servicio de Google (ver README). Las llamadas son bloqueantes:
el bot las ejecuta con asyncio.to_thread.
"""
import logging
import threading

import config

log = logging.getLogger(__name__)

# Única lista de columnas que Python puede modificar.
COLS_ESCRIBIBLES = ("cantidad", "fecha_actualizacion", "tiempo_restante")

_lock = threading.Lock()
_hoja_cache = None     # pestaña Lotes_Registrados ya abierta
_libro_cache = None    # libro completo (lo comparten las pestañas nuevas de v02.7)


class SheetsError(Exception):
    """Problema al leer/escribir Google Sheets (credenciales, permisos, red, hoja inexistente)."""


# ▸ Abre el libro de Google (cacheado) con la cuenta de servicio.
def _libro():
    """Abre (una sola vez) el Google Sheet completo con la cuenta de servicio.

    v02.7: se separó de _hoja() para que sheets_ventas.py pueda abrir OTRAS pestañas
    (Ventas_Registradas, Score_Rescate) sin autenticarse de nuevo.
    """
    global _libro_cache
    if _libro_cache is None:
        try:
            import gspread
            cliente = gspread.service_account(filename=config.GOOGLE_CREDENTIALS_FILE)
            _libro_cache = cliente.open_by_key(config.GOOGLE_SHEET_ID)
        except FileNotFoundError as exc:
            raise SheetsError(
                f"No encuentro el archivo de credenciales de Google: {config.GOOGLE_CREDENTIALS_FILE}"
            ) from exc
        except Exception as exc:  # gspread lanza varios tipos (permisos, hoja inexistente, red)
            raise SheetsError(f"No pude abrir el Google Sheet: {exc}") from exc
    return _libro_cache


# ▸ Devuelve la pestaña Lotes_Registrados.
def _hoja():
    """Abre (una sola vez) la pestaña Lotes_Registrados."""
    global _hoja_cache
    if _hoja_cache is None:
        try:
            _hoja_cache = _libro().worksheet(config.HOJA_LOTES)
        except SheetsError:
            raise
        except Exception as exc:
            raise SheetsError(f"No pude abrir la pestaña {config.HOJA_LOTES}: {exc}") from exc
    return _hoja_cache


# ▸ Convierte fila/columna a notación A1.
def _a1(fila: int, columna: int) -> str:
    """(fila, columna) con base 1 -> 'C7'. Soporta más de 26 columnas."""
    letras = ""
    while columna:
        columna, resto = divmod(columna - 1, 26)
        letras = chr(65 + resto) + letras
    return f"{letras}{fila}"


# ▸ Lee todos los lotes (+ _fila real).
def leer_lotes(hoja=None) -> list:
    """Lee Lotes_Registrados. Cada lote es un dict con las columnas del encabezado en minúsculas.

    Se piden valores SIN formato (números reales) y fechas como texto formateado, para no
    depender de cómo muestre Sheets los precios o el EAN.
    """
    try:
        ws = hoja or _hoja()
        valores = ws.get_all_values(
            value_render_option="UNFORMATTED_VALUE",
            date_time_render_option="FORMATTED_STRING",
        )
    except SheetsError:
        raise
    except Exception as exc:
        raise SheetsError(f"No pude leer Lotes_Registrados: {exc}") from exc

    if not valores:
        return []
    encabezados = [str(h).strip().lower() for h in valores[0]]
    lotes = []
    for numero, fila in enumerate(valores[1:], start=2):
        lote = {h: (fila[i] if i < len(fila) else "") for i, h in enumerate(encabezados) if h}
        if not str(lote.get("id_lote", "")).strip():
            continue  # fila vacía
        lote["_fila"] = numero
        lotes.append(lote)
    return lotes


# ▸ Escribe SOLO las 3 columnas permitidas, en un único batch_update.
def aplicar_cambios(cambios: list, hoja=None) -> int:
    """Escribe cantidad / fecha_actualizacion / tiempo_restante de cada lote cambiado.

    `cambios` = [{"_fila": 7, "cantidad": 58, "fecha_actualizacion": "...", "tiempo_restante": "..."}]
    Devuelve la cantidad de celdas escritas. Un solo batch_update = todo o nada.
    """
    if not cambios:
        return 0
    with _lock:
        try:
            ws = hoja or _hoja()
            encabezados = [str(h).strip().lower() for h in ws.row_values(1)]

            # Si la hoja todavía no tiene las columnas nuevas, se agregan al final (solo el título).
            faltantes = [c for c in COLS_ESCRIBIBLES if c not in encabezados]
            if faltantes:
                if len(encabezados) + len(faltantes) > ws.col_count:
                    ws.add_cols(len(encabezados) + len(faltantes) - ws.col_count)
                for nombre in faltantes:
                    encabezados.append(nombre)
                    ws.update_cell(1, len(encabezados), nombre)

            datos = []
            for cambio in cambios:
                for columna in COLS_ESCRIBIBLES:
                    datos.append({
                        "range": _a1(cambio["_fila"], encabezados.index(columna) + 1),
                        "values": [[cambio[columna]]],
                    })
            # RAW: se guarda tal cual (no deja que Sheets reinterprete "6/11/2026" según su idioma).
            ws.batch_update(datos, value_input_option="RAW")
            return len(datos)
        except SheetsError:
            raise
        except Exception as exc:
            raise SheetsError(f"No pude escribir en Lotes_Registrados: {exc}") from exc
