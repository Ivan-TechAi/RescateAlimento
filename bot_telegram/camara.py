# =============================================================================
# camara.py — LECTURA DE CÓDIGOS DE BARRAS EN FOTOS
# =============================================================================
# CAPSTONE: Etapa 1: captura de datos (EAN del producto).
# Prueba varias versiones de la imagen (gris, contraste, rotada) hasta que pyzbar decodifica el EAN.
# (Explicación del proyecto completo y del modelo en README.md y docs/ARQUITECTURA.md)
# =============================================================================

"""Lectura de códigos de barras desde fotos."""
import cv2
from pyzbar.pyzbar import decode, ZBarSymbol

_SIMBOLOGIAS = [ZBarSymbol.EAN13, ZBarSymbol.EAN8, ZBarSymbol.UPCA, ZBarSymbol.UPCE]


# ▸ Genera versiones alternativas de la imagen para mejorar la lectura.
def _variantes(imagen):
    """Genera versiones de la imagen para mejorar la detección en fotos de celular."""
    yield imagen
    gris = cv2.cvtColor(imagen, cv2.COLOR_BGR2GRAY)
    yield gris
    yield cv2.resize(gris, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    yield cv2.adaptiveThreshold(
        gris, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 10
    )
    alto = gris.shape[0]
    if alto > 1600:  # fotos enormes: a veces leen mejor reducidas
        escala = 1600 / alto
        yield cv2.resize(gris, None, fx=escala, fy=escala, interpolation=cv2.INTER_AREA)


# ▸ Devuelve el primer código de barras legible de la foto (o None).
def escanear_foto_bytes(ruta_imagen):
    """Decodifica el primer código de barras (EAN/UPC) de la imagen. None si no hay."""
    imagen = cv2.imread(ruta_imagen)
    if imagen is None:
        return None

    for variante in _variantes(imagen):
        codigos = decode(variante, symbols=_SIMBOLOGIAS)
        if codigos:
            valor = codigos[0].data.decode("utf-8")
            # UPC-A (12 dígitos) es un EAN-13 con cero inicial
            if len(valor) == 12:
                valor = "0" + valor
            return valor
    return None
