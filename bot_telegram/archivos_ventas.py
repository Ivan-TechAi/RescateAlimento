# =============================================================================
# archivos_ventas.py — LECTURA DE VENTAS (.csv / .xlsx)
# =============================================================================
# CAPSTONE: Etapa 1-2: ingesta de datos de ventas.
# Lee el archivo del sistema externo, tolera nombres de columna distintos y descarta filas inválidas.
# (Explicación del proyecto completo y del modelo en README.md y docs/ARQUITECTURA.md)
# =============================================================================

"""Lectura del archivo de ventas del sistema externo (.csv / .xlsx) (v02.6).

Formato esperado (ventas_sistema-externo.csv):
    ean, producto, marca, cantidad_unitarias, precio_unidad, fecha_vendio, id_lote
De todo eso solo se USA: id_lote (clave de búsqueda), ean (control), cantidad_unitarias,
precio_unidad y fecha_vendido. producto y marca salen del propio Sheet.
"""
import csv
import datetime
import io
import re
import unicodedata
from pathlib import Path

from utils import a_float

# Nombre de columna (normalizado) -> campo interno. Acepta variantes comunes.
ALIAS = {
    "ean": "ean", "codigo": "ean", "codigo_de_barras": "ean",
    "id_lote": "id_lote", "lote": "id_lote", "idlote": "id_lote",
    "producto": "producto",
    "marca": "marca",
    "cantidad_unitarias": "cantidad_unitarias", "cantidad_unitaria": "cantidad_unitarias",
    "cantidad": "cantidad_unitarias", "unidades": "cantidad_unitarias",
    "precio_unidad": "precio_unidad", "precio_unitario": "precio_unidad", "precio": "precio_unidad",
    "fecha_vendio": "fecha_vendido", "fecha_vendido": "fecha_vendido", "fecha": "fecha_vendido",
}


# ▸ Normaliza nombres de columna (mayúsculas, tildes, espacios).
def _clave_columna(nombre) -> str:
    """'  Cantidad Unitarias ' -> 'cantidad_unitarias' (sin tildes, minúsculas)."""
    t = unicodedata.normalize("NFKD", str(nombre or "")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", t.lower()).strip("_")


# ▸ Convierte cualquier celda a texto limpio.
def _texto(valor) -> str:
    """EAN/IDs como texto limpio (Excel suele entregar el EAN como número decimal)."""
    if valor is None:
        return ""
    if isinstance(valor, float) and valor.is_integer():
        valor = int(valor)
    return str(valor).strip()


# ▸ Valida y estandariza filas; acumula motivos de descarte.
def normalizar_filas(filas_crudas: list) -> list:
    """Convierte filas con encabezados libres en filas con los campos internos.

    Lanza ValueError si faltan las columnas imprescindibles. Se ignoran renglones vacíos.
    """
    presentes = {ALIAS[_clave_columna(k)] for fila in filas_crudas for k in fila if _clave_columna(k) in ALIAS}
    if "cantidad_unitarias" not in presentes or not ({"id_lote", "ean"} & presentes):
        raise ValueError(
            "No encuentro las columnas necesarias. El archivo debe tener al menos "
            "cantidad_unitarias y id_lote (o ean)."
        )

    filas = []
    for n, cruda in enumerate(filas_crudas, start=2):   # renglón 1 = encabezado
        fila = {}
        for k, v in cruda.items():
            campo = ALIAS.get(_clave_columna(k))
            if campo:
                fila[campo] = v
        if all(v is None or str(v).strip() == "" for v in fila.values()):
            continue
        fecha = fila.get("fecha_vendido")
        if isinstance(fecha, (datetime.datetime, datetime.date)):
            fecha = fecha.strftime("%Y-%m-%d")
        filas.append({
            "_n": n,
            "ean": _texto(fila.get("ean")),
            "id_lote": _texto(fila.get("id_lote")).upper(),
            "cantidad_unitarias": a_float(fila.get("cantidad_unitarias")),
            "precio_unidad": a_float(fila.get("precio_unidad")),
            "fecha_vendido": _texto(fecha),
        })
    if not filas:
        raise ValueError("El archivo no tiene renglones de ventas.")
    return filas


# ▸ Lee CSV con detección de separador.
def _leer_csv(ruta: str) -> list:
    datos = Path(ruta).read_bytes()
    try:
        texto = datos.decode("utf-8-sig")
    except UnicodeDecodeError:
        texto = datos.decode("latin-1")     # CSV viejos de Excel
    lineas = texto.splitlines()
    if not lineas:
        raise ValueError("El archivo está vacío.")
    # El Excel argentino guarda con ';'; se elige el separador que más aparece en el encabezado.
    separador = max(",;\t", key=lineas[0].count)
    return list(csv.DictReader(io.StringIO(texto), delimiter=separador))


# ▸ Lee la primera hoja de un Excel.
def _leer_xlsx(ruta: str) -> list:
    from openpyxl import load_workbook
    libro = load_workbook(ruta, read_only=True, data_only=True)
    try:
        renglones = libro.active.iter_rows(values_only=True)
        encabezado = next(renglones, None)
        if not encabezado:
            raise ValueError("La planilla está vacía.")
        return [
            {h: v for h, v in zip(encabezado, fila) if h is not None}
            for fila in renglones
        ]
    finally:
        libro.close()


# ▸ Elige lector según la extensión.
def leer_archivo_ventas(ruta: str) -> list:
    """Lee un .csv o .xlsx y devuelve las filas normalizadas."""
    extension = Path(ruta).suffix.lower()
    if extension == ".csv":
        crudas = _leer_csv(ruta)
    elif extension == ".xlsx":
        crudas = _leer_xlsx(ruta)
    else:
        raise ValueError("Formato no soportado. Subí un archivo .csv o .xlsx.")
    return normalizar_filas(crudas)
