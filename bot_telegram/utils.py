# =============================================================================
# utils.py — FUNCIONES COMPARTIDAS
# =============================================================================
# CAPSTONE: Soporte de todas las etapas.
# Escapado de texto, fechas (acepta varios formatos), números en formato argentino, ids normalizados y división de mensajes largos de Telegram.
# (Explicación del proyecto completo y del modelo en README.md y docs/ARQUITECTURA.md)
# =============================================================================

"""Utilidades compartidas por los módulos de DataByte."""
import datetime
import html
import re


# ▸ Escapa HTML para que nombres de productos no rompan el mensaje.
def esc(texto) -> str:
    """Escapa texto dinámico para usarlo con parse_mode='HTML'."""
    return html.escape(str(texto if texto is not None else ""))


# ▸ Acepta AAAA-MM-DD, DD/MM/AAAA, etc.
def parsear_fecha(texto):
    """Acepta DD/MM/AAAA o AAAA-MM-DD (con o sin hora). Devuelve date o None.

    v02.6: también tolera '2026-12-31 00:00:00' o '6/11/2026 22:00:09' y objetos date/datetime,
    porque Google Sheets puede devolver la fecha con hora.
    """
    if isinstance(texto, datetime.datetime):
        return texto.date()
    if isinstance(texto, datetime.date):
        return texto
    texto = re.split(r"[ T]", str(texto or "").strip())[0]
    for formato in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.datetime.strptime(texto, formato).date()
        except ValueError:
            continue
    return None


# ▸ Fecha válida y no vencida.
def fecha_vigente(texto: str):
    """Devuelve la fecha (date) si es válida y no está vencida; si no, None."""
    fecha = parsear_fecha(texto)
    if fecha is None or fecha < datetime.date.today():
        return None
    return fecha


# ▸ Convierte '7.101,00' o '$7101' a número.
def a_float(valor) -> float:
    """Convierte números/textos ('1500', '1.500,50', '$ 1500.5') a float. 0.0 si no puede."""
    if valor is None or valor == "":
        return 0.0
    if isinstance(valor, bool):
        return 0.0
    if isinstance(valor, (int, float)):
        return float(valor)
    t = str(valor).strip().replace("$", "").replace(" ", "")
    if "," in t and "." in t:
        t = t.replace(".", "").replace(",", ".")
    elif "," in t:
        t = t.replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return 0.0


# ▸ Normaliza ids (evita '123.0' de Excel/Sheets).
def norm_id(valor) -> str:
    """Normaliza identificadores (telegram_id, id_lote) que Sheets puede devolver como número."""
    if isinstance(valor, float) and valor.is_integer():
        valor = int(valor)
    return str(valor if valor is not None else "").strip()


# ▸ Formato D/M/AAAA HH:MM:SS (como pidió el proyecto).
def fecha_hora_ar(dt: datetime.datetime) -> str:
    """Formato pedido para fecha_actualizacion: 6/11/2026 22:00:09 (día y mes sin ceros)."""
    return f"{dt.day}/{dt.month}/{dt.year} {dt:%H:%M:%S}"


# ▸ Parte textos largos (Telegram limita a 4096 caracteres).
def dividir_mensaje(lineas, limite=3500):
    """Agrupa líneas en bloques que entren en un mensaje de Telegram (máx. 4096)."""
    bloques, actual, largo = [], [], 0
    for linea in lineas:
        if actual and largo + len(linea) + 1 > limite:
            bloques.append("\n".join(actual))
            actual, largo = [], 0
        actual.append(linea)
        largo += len(linea) + 1
    if actual:
        bloques.append("\n".join(actual))
    return bloques
