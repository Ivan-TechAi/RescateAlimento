#RescateAlimento · DataByte Bot (v02.7)

> Bot de Telegram que ayuda a comercios de alimentos a **vender antes de que venza la mercadería**, reduciendo el desperdicio y las pérdidas.
> Proyecto **DataByte.io** — Samsung Innovation Campus (Capstone).

## Problema que resolvemos

Los comercios pequeños pierden dinero y desperdician alimentos porque no saben **qué lote bajar de precio, cuándo y cuánto**. RescateAlimento convierte los datos de stock, ventas y precios de la competencia en una **recomendación concreta y explicable**.

## Funcionalidades

| Menú | Qué hace |
|---|---|
| 📦 Cargar productos | Alta de lotes por **foto del código de barras (EAN)** o por **factura PDF**, con precios sugeridos según el catálogo/competencia |
| 📊 Stock y Ventas | Carga de ventas del día (**.csv/.xlsx** o **foto del cuaderno** leída con IA), descuento de stock con vista previa y confirmación; stock actual con **semáforo** 🔴🟠🟢 |
| 🎯 Score de Rescate | Ranking de lotes (0–100) con acción recomendada: bajar precio, reforzar, liquidar/donar o retirar |
| 🔔 Notificaciones | *(próxima versión)* |

## Modelo de decisión

**Score de Rescate = 40 % Urgencia + 25 % Ritmo de venta + 20 % Valor en riesgo + 15 % Precio vs competencia**

Es un modelo **estadístico y explicable** (índice compuesto + media móvil + reglas de negocio), elegido sobre Machine Learning porque hay pocos datos por comercio y el comerciante necesita entender *por qué* se le recomienda algo. Detalle en [`docs/ARQUITECTURA.md`](docs/ARQUITECTURA.md).

## Arquitectura

```
Telegram ⇄ Bot (Python) ⇄ n8n (webhooks) ⇄ Google Sheets
                │                              │
                ├─ Claude (visión): cuaderno   └─► Score_Rescate ─► Looker Studio (dashboard)
                └─ pyzbar/OpenCV: códigos de barras
```

> ⚠️ Este repositorio contiene **solo el bot**. Los workflows de n8n, el dashboard de Looker Studio y el resto del proyecto viven en otros repositorios/carpetas.

## Estructura

```
├── main.py                # Punto de entrada
├── config.py              # Configuración (lee .env)
├── menu_principal.py      # Menús de Telegram
├── registro_usuario.py    # Alta de comercios (/start)
├── registro_lote.py       # Lote por foto de EAN
├── registro_factura.py    # Lotes desde factura PDF
├── stock_ventas.py        # Cargar ventas / ver stock
├── score_bot.py           # Botón Score de Rescate
├── modelo_score.py        # Modelo de decisión (lógica pura)
├── logica_ventas.py       # Stock y semáforo (lógica pura)
├── archivos_ventas.py     # Lectura .csv/.xlsx
├── cuaderno.py            # Lectura de cuaderno con IA
├── camara.py              # Lectura de códigos de barras
├── backend.py             # Conexión con n8n
├── usuarios_backend.py    # Consulta de usuarios en n8n
├── sheets_lotes.py        # Google Sheets: Lotes_Registrados
├── sheets_ventas.py       # Google Sheets: ventas y score
├── registro_local.py      # Anti-duplicados de ventas
├── exportar_dashboard.py  # Publica el score para Looker Studio
└── utils.py               # Utilidades compartidas
```

## Instalación

Requiere **Python 3.10+** (usa `zoneinfo`). En Linux, `pyzbar` necesita `sudo apt install libzbar0`.

```bash
git clone https://github.com/<tu-usuario>/<tu-repo>.git
cd <tu-repo>
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env             # Windows: copy .env.example .env
# Editá .env con tus valores y poné credenciales_google.json junto a main.py
python main.py
```

Para actualizar el dashboard: `python exportar_dashboard.py` (se puede programar cada hora).

## Configuración y secretos

Ningún secreto va en el código. Todo se define en `.env` (ignorado por Git):

| Variable | Descripción |
|---|---|
| `TOKEN_TELEGRAM` | Token del bot (@BotFather) |
| `URL_*` | Webhooks de n8n (usar `/webhook/`, no `/webhook-test/`) |
| `GOOGLE_SHEET_ID` | ID de la hoja de cálculo |
| `GOOGLE_CREDENTIALS_FILE` | JSON de la cuenta de servicio de Google |
| `ANTHROPIC_API_KEY` | Opcional: activa la lectura del cuaderno |

## Formato del archivo de ventas

```csv
ean,producto,marca,cantidad_unitarias,precio_unidad,fecha_vendio,id_lote
7790360026578,Galletitas,Marca X,2,7101,02/11/2026,LOT-E1B50FB5
```

Se usan `id_lote`, `ean`, `cantidad_unitarias`, `precio_unidad` y `fecha_vendido`. Acepta variantes de nombres de columna y separadores `,` `;` o tab.


## Licencia

*(MIT, Apache-2.0, Todos los derechos reservados.)*
