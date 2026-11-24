"""Configuración de DataByte v02.7.

Los secretos (token de Telegram, claves) NO van en el código: se leen de variables
de entorno o del archivo .env (copiá .env.example a .env y completalo).
"""
import os
from pathlib import Path
from zoneinfo import ZoneInfo

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).with_name(".env"))
except ImportError:  # python-dotenv es opcional si usás variables de entorno reales
    pass

_AQUI = Path(__file__).resolve().parent

# --- Credenciales -----------------------------------------------------------
# Sin valor por defecto: si falta, main.py avisa y no arranca.
TOKEN_TELEGRAM = os.getenv("TOKEN_TELEGRAM", "").strip()

# --- Endpoints de n8n (se definen en .env) -----------------------------------
# OJO: las URL /webhook-test/ solo responden mientras n8n está "escuchando" un
# evento de prueba. Para uso real, activá el workflow y usá /webhook/.
_N8N = "https://TU-INSTANCIA.app.n8n.cloud/webhook"
URL_BUSCAR = os.getenv("URL_BUSCAR", f"{_N8N}/buscar-producto")
URL_REGISTRAR_LOTE = os.getenv("URL_REGISTRAR_LOTE", f"{_N8N}/registrar-lote")
URL_REGISTRAR_USUARIO = os.getenv("URL_REGISTRAR_USUARIO", f"{_N8N}/registrar-usuario")
URL_BUSCAR_USUARIO = os.getenv("URL_BUSCAR_USUARIO", f"{_N8N}/buscar-usuario")
URL_BUSCAR_FACTURA_MASIVA = os.getenv("URL_BUSCAR_FACTURA_MASIVA", f"{_N8N}/buscar-productos-factura")

# --- Comportamiento de la factura -------------------------------------------
# True  -> la factura se guarda con UN solo POST {"lotes": [ ... ]} (n8n debe separar los items)
# False -> un POST por lote (compatible con el webhook de registro individual)
GUARDADO_MASIVO = os.getenv("GUARDADO_MASIVO", "1") == "1"

# Niveles de precio que se ofrecen por producto al cargar una factura (v02.6).
# Se calculan sobre el precio de referencia del catálogo (precio_lista, o precio_min si no hay lista).
DESCUENTO_NIVEL_1 = 0.10            # Nivel 1: 10% OFF
DESCUENTO_NIVEL_2 = 0.30            # Nivel 2: 30% OFF
# Nivel 3 = precio mínimo del catálogo (o 50% OFF si el catálogo no trae mínimo).
# Si el producto NO tiene referencia, se sugiere costo + este margen (y se puede escribir otro precio).
MARGEN_SIN_REFERENCIA = 0.20

TIMEOUT_HTTP = 20

# --- Parte 2: Stock y Ventas (v02.6) ----------------------------------------
# ID del Google Sheet (la parte larga del link de compartir). Se define en .env.
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID", "").strip()
HOJA_LOTES = os.getenv("HOJA_LOTES", "Lotes_Registrados")
# Cuenta de servicio de Google (JSON). Hay que COMPARTIR el Sheet con el mail de esa cuenta como Editor.
GOOGLE_CREDENTIALS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE", str(_AQUI / "credenciales_google.json"))

# Semáforo del stock según los días que faltan para vencer (se puede ajustar en .env).
DIAS_ROJO = int(os.getenv("DIAS_ROJO", "3"))        # faltan <= 3 días  -> ROJO: bajar precio ya
DIAS_NARANJA = int(os.getenv("DIAS_NARANJA", "10")) # faltan <= 10 días -> NARANJA: bajar un poco
                                                    # más que eso       -> VERDE

# True: un lote que vence el 31/12 se considera vigente hasta las 23:59:59 de ese día.
# False: se considera vencido a las 00:00 del 31/12.
VENCE_AL_FINAL_DEL_DIA = os.getenv("VENCE_AL_FINAL_DEL_DIA", "1") == "1"

# Zona horaria para fecha_actualizacion y tiempo_restante.
ZONA_HORARIA = ZoneInfo(os.getenv("ZONA_HORARIA", "America/Argentina/Buenos_Aires"))

# Historial local para avisar si se sube dos veces el mismo archivo de ventas.
HISTORIAL_VENTAS_FILE = os.getenv("HISTORIAL_VENTAS_FILE", str(_AQUI / "ventas_procesadas.json"))

# Lectura del cuaderno (foto manuscrita) con visión de Claude. Sin clave, esa opción queda desactivada.
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5-5")


# =============================================================================
# v02.7 — ETAPA 4 DEL CAPSTONE: MODELO DE DECISIÓN (Score de Rescate)
# =============================================================================
# Modelo ESTADÍSTICO (índice compuesto + reglas de negocio + forecast simple).
# Se eligió sobre Machine Learning porque hoy hay pocos datos por comercio y el
# comerciante necesita entender POR QUÉ se le recomienda algo (explicabilidad).
#
# Score de Rescate (0-100) = 40% Urgencia + 25% Ritmo + 20% Valor + 15% Precio
# Los pesos deben sumar 1.0; si cambian en .env el modelo los normaliza igual.
PESO_URGENCIA = float(os.getenv("PESO_URGENCIA", "0.40"))  # cuánto falta para vencer
PESO_RITMO = float(os.getenv("PESO_RITMO", "0.25"))        # ¿alcanza a venderse al ritmo actual?
PESO_VALOR = float(os.getenv("PESO_VALOR", "0.20"))        # plata inmovilizada en el lote
PESO_PRECIO = float(os.getenv("PESO_PRECIO", "0.15"))      # precio propio vs competencia (catálogo)

# Forecast simple: ritmo de venta = media móvil de unidades/día de los últimos N días.
VENTANA_RITMO_DIAS = int(os.getenv("VENTANA_RITMO_DIAS", "7"))

# Un lote que inmoviliza este valor (en $) o más recibe el máximo en el componente Valor.
VALOR_LOTE_ALTO = float(os.getenv("VALOR_LOTE_ALTO", "150000"))

# Regla de descuento: con urgencia 100 se recomienda este descuento sobre el precio de
# referencia de la competencia; se suma hasta +15% extra si se proyecta merma.
DESCUENTO_MAXIMO = float(os.getenv("DESCUENTO_MAXIMO", "0.50"))
DESCUENTO_TOPE = 0.65   # nunca se recomienda más que esto

# Umbrales del Score para clasificar la prioridad.
UMBRAL_SCORE_ROJO = float(os.getenv("UMBRAL_SCORE_ROJO", "70"))
UMBRAL_SCORE_NARANJA = float(os.getenv("UMBRAL_SCORE_NARANJA", "40"))

# Si falta esto o menos para vencer y no alcanza a venderse, se sugiere liquidar/donar.
DIAS_LIQUIDAR_DONAR = int(os.getenv("DIAS_LIQUIDAR_DONAR", "1"))

# Historial de ventas (alimenta el ritmo y el ROI). Se guarda en una PESTAÑA NUEVA del
# mismo Sheet; no toca Lotes_Registrados. Poner 0 para desactivarlo.
REGISTRAR_HISTORIAL_VENTAS = os.getenv("REGISTRAR_HISTORIAL_VENTAS", "1") == "1"
HOJA_VENTAS = os.getenv("HOJA_VENTAS", "Ventas_Registradas")
# Pestaña que publica exportar_dashboard.py para conectar Looker Studio.
HOJA_SCORE = os.getenv("HOJA_SCORE", "Score_Rescate")
