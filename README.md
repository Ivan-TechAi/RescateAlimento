# DataByte/RescateAlimento

**Inteligencia competitiva para que los comercios de alimentos vendan antes de que venza la mercadería.**

> Proyecto **DataByte.io** · Capstone **Samsung Innovation Campus** · Córdoba, Argentina · Noviembre 2026


---

## Tabla de contenidos

1. [El problema](#-el-problema)
2. [Por qué lo elegimos](#-por-qué-elegimos-este-problema)
3. [La solución](#-la-solución)
4. [Arquitectura](#-arquitectura)
5. [Datos](#-datos)
6. [El modelo de decisión](#-el-modelo-de-decisión-score-de-rescate)
7. [Métrica de negocio, costos y ROI](#-métrica-de-negocio-costos-y-roi)
8. [Resultados y hallazgos](#-resultados-y-hallazgos)
9. [Limitaciones (dichas con honestidad)](#-limitaciones)
10. [Estructura del repositorio](#-estructura-del-repositorio)
11. [Cómo ejecutarlo](#-cómo-ejecutarlo)
12. [Seguridad y privacidad](#-seguridad-y-privacidad)
13. [Hoja de ruta](#-hoja-de-ruta)
14. [Equipo](#-equipo)
15. [Licencia](#-licencia)

---

## El problema

**Cliente (caso del Capstone):** Diana, directora de *Vértice Comercial*, una comercializadora multicanal que evalúa entrar al rubro de alimentos y bebidas de consumo masivo.

| Dato de su ficha | Valor |
|---|---|
| Horas semanales relevando precios y competencia **a mano** | 12 h |
| Costo de una hora de trabajo | USD 8 |
| Equipo comercial | 3 personas |
| Publicaciones cargadas con error | 1 de cada 10 |
| Meta de ventas del nuevo rubro | USD 15.000 / mes |
| Presupuesto máximo | USD 2.500 de desarrollo + USD 150 / mes de operación |
| NPS actual | 22 |

Su queja resume el problema: *«llego tarde y pierdo ventas»*. Relevar precios a mano es lento, caro y propenso a errores, y cuando se decide un precio, la competencia ya cambió.

El problema se agrava en alimentos: **un producto perecedero que no se vende a tiempo se convierte en merma**: pérdida económica para el comercio y comida desperdiciada para la sociedad.

## Por qué elegimos este problema

1. **Doble impacto.** Resuelve un dolor comercial concreto (tiempo y plata) y a la vez reduce el desperdicio de alimentos (impacto social y ambiental).
2. **Hay datos públicos y reales.** Los precios de *Precios Claros* (preciosclaros.gob.ar) permiten medir la competencia sin depender de datos privados.
3. **Es accionable.** No nos quedamos en un tablero: el sistema le dice al comerciante **qué lote bajar, cuánto y cuándo**.
4. **Es explicable.** Un comerciante pequeño no confía en una caja negra. Por eso elegimos un modelo estadístico con reglas claras antes que un modelo opaco (ver [más abajo](#-el-modelo-de-decisión-score-de-rescate)).
5. **Es barato de operar.** Usa herramientas de bajo costo (Apify, n8n, Google Sheets, Telegram) que entran en el presupuesto del cliente.
6. **Funciona para comercios sin sistema.** El comerciante puede cargar ventas con una **foto de su cuaderno**, leída con IA. No necesita software de gestión.

## La solución

RescateAlimento tiene tres piezas que trabajan juntas:

| Pieza | Qué hace | Dónde |
|---|---|---|
| **1. Extracción automática de precios** | Un actor de Apify descarga los precios de Precios Claros; n8n lo programa y los guarda | `automatizacion/` *(workflows de n8n)* |
| **2. Bot de Telegram** | El comerciante carga lotes (foto del código de barras o factura PDF), carga ventas (archivo o foto del cuaderno), ve su stock con semáforo y consulta su Score de Rescate | [`bot/`](bot/) |
| **3. Análisis y modelo** | Limpieza de datos, EDA, comparación de modelos de demanda, simulación de ROI y KPIs | [`notebooks/`](notebooks/) |

### Funcionalidades del bot

| Menú | Qué hace |
|---|---|
| 📦 Cargar productos | Alta de lotes por **foto del EAN** o por **factura PDF**, con precios sugeridos desde el catálogo de la competencia |
| 📊 Stock y Ventas | Carga de ventas (`.csv`/`.xlsx` o **foto de cuaderno**) con vista previa y confirmación; stock actual con semáforo 🔴🟠🟢 |
| 🎯 Score de Rescate | Ranking de lotes (0–100) con la acción recomendada y el precio sugerido |
| 🔔 Notificaciones | *(próxima versión)* |


## Datos

### Datos reales: Precios Claros vía Apify

| Medición | Valor |
|---|---|
| Registros extraídos | **22.438** (un registro = un precio de un producto en una sucursal) |
| Productos únicos (EAN) | **3.009** |
| Duración de la corrida | 1 h (terminó por *timeout*) |
| Costo de la corrida | **USD 0,315** |
| Nulos / duplicados / EAN inválidos | 0 / 0 / 0 |
| Cobertura | Córdoba, 5 cadenas |

Se aplicó ETL completo (calidad, normalización de unidades, marcado de outliers sin borrarlos y uso de **mediana** en lugar de promedio). Ver [`notebooks/00_ETL_EDA_PreciosClaros_real.ipynb`](notebooks/00_ETL_EDA_PreciosClaros_real.ipynb).

### Datos simulados

El bot todavía no acumuló historial real de ventas (la pestaña `Ventas_Registradas` nació en la v02.7). Los notebooks 01 a 04 usan un **simulador** (columna `fuente = "SIMULADO"`) para construir y validar el pipeline completo. **No sirven para afirmar resultados reales.** El mismo código se re-ejecuta con datos reales apenas haya 4 a 6 semanas de historial.

## El modelo de decisión: Score de Rescate

```
Score (0–100) = 40 % Urgencia + 25 % Ritmo de venta + 20 % Valor en riesgo + 15 % Precio vs competencia
```

| Componente | Qué mide |
|---|---|
| **Urgencia** | Cuánto falta para vencer |
| **Ritmo** | ¿Alcanza a venderse el lote al ritmo actual? (media móvil de 7 días proyectada hasta el vencimiento) |
| **Valor** | Cuánta plata hay inmovilizada en el lote |
| **Precio** | Qué tan lejos está el precio propio del descuento que corresponde, comparado con la competencia |

La salida es una **acción**: `RETIRAR`, `LIQUIDAR_DONAR`, `BAJAR_YA`, `BAJAR`, `REFORZAR` o `MANTENER`, con precio sugerido.

### ¿Por qué un modelo estadístico y no Machine Learning?

Seguimos el principio *reglas simples → heurística → modelo*:

1. Con pocos datos por comercio, un modelo ML sobreajustaría.
2. El comerciante necesita entender **por qué** se le recomienda algo.
3. Cuando sí hubo datos (simulados), **medimos** en lugar de suponer: probamos 5 modelos y los comparamos contra la heurística.

### Comparación de modelos de demanda (datos simulados)

Se probaron 5 modelos (Ridge, KNN, Random Forest, Gradient Boosting y una red MLP) con validación cruzada temporal y búsqueda de hiperparámetros. Se eligió por error absoluto medio (MAE), mirando el conjunto de test una sola vez.

| Modelo | MAE test (unidades/día) |
|---|---|
| Heurística actual (media móvil 7) | 3,045 |
| Ridge | 2,825 |
| KNN | 2,932 |
| Random Forest | 2,644 |
| **Gradient Boosting** | **2,584** (≈ 15 % mejor que la heurística) |

⚠️ Resultado **provisorio**: viene de datos simulados. La regla de integración quedó escrita antes de ver los números: el ML entra al bot solo si mejora al menos 5 % en test y también gana en validación cruzada.

## Métrica de negocio, costos y ROI

**Métrica de negocio (3 elementos):**

| Elemento | Definición |
|---|---|
| **Indicador** | Horas semanales de relevamiento manual de precios (y su costo en USD) |
| **Dirección** | **Reducir** de 12 a 2 h por semana (−83 %), de USD 416 a USD 69 por mes |
| **Acción del modelo** | La extracción diaria reemplaza el relevamiento manual y el Score indica qué producto o lote ajustar hoy |

Métricas de apoyo en el negocio del comerciante: **% de merma valorizada** (principal) y **ganancia por lote** (guardarraíl: bajar el precio no es un logro si se pierde margen). Ver [`notebooks/04_Metrica_de_negocio_y_KPIs.ipynb`](notebooks/04_Metrica_de_negocio_y_KPIs.ipynb).

![KPIs](docs/img/kpis_tarjetas.png)

### Costos y ROI (notebook 05)

| Concepto | Valor |
|---|---|
| Costo de desarrollo | USD 1.839,58 |
| **Precio al cliente** (margen 30 %) | **USD 2.391,45** (dentro del tope de USD 2.500) |
| Operación mensual: monitoreo diario | USD 118,00 |
| Operación mensual: piloto semanal | USD 80,26 (dentro del tope de USD 150) |
| Ahorro mensual (10 h/sem automatizadas) | USD 346,67 |
| **ROI a 12 meses** (solo ahorro de horas) | **9,3 %** (diario) · **24,0 %** (semanal) |
| **Recuperación de la inversión** | **≈ 9 a 10,5 meses** |

El ROI es **conservador a propósito**: no suma ninguna venta adicional. El valor grande está en decidir antes, y se muestra aparte como escenario *upside* (con 1 % más de ventas, la recuperación baja a ≈ 8,5 a 9,5 meses según el margen).

**Benchmark de mercado:** nuestro costo por 1.000 registros es ≈ USD 0,014 de cómputo, frente a USD 0,80 a 10,00 de los actores públicos de Apify para Mercado Libre. No es una comparación idéntica (ellos son genéricos, nosotros específicos de una fuente) y no incluye las horas de construcción. Ver fuentes con URL al final del notebook 05.

## Resultados y hallazgos

1. **El pipeline funciona de punta a punta:** extracción → Sheets → bot → Score → dashboard.
2. **La simulación encontró un defecto real en nuestro propio modelo.** El Score v02.7 reduce la merma casi a cero, pero **resta ganancia**: recomienda descuentos profundos aunque el lote se iba a vender igual (ejemplo: leche con ritmo suficiente y merma proyectada 0, a la que igual sugería bajar de $1.499 a $984).
3. **La corrección:** el *Score calibrado* rebaja solo lo necesario para vender antes del vencimiento, usando la sensibilidad al precio medida y un piso de costo. Lo que no se pueda vender sobre el costo se dona.
4. **El argumento fuerte no es «vendo más caro».** Es: menos comida tirada, tiempo ahorrado al comerciante y decisiones de precio con datos de la competencia en lugar de a ojo.
5. **La palanca clave es la adherencia:** que el comerciante siga la recomendación.
6. **Insight de mercado (EDA real):** el precio depende sobre todo de *qué producto es* (marca, tamaño, categoría) más que de la cadena; la brecha mediana entre cadenas ronda el 3,4 %, y esa es la que se puede explotar.

## ⚠️ Limitaciones

Las decimos nosotros antes de que nos pregunten:

- **Los datos de ventas, stock y ROI de los notebooks 01 a 04 son simulados.** No presentarlos como resultados reales.
- **No usar el «ROI 80 %» del notebook 03** como cifra de pitch: viene de datos simulados.
- **El supuesto central del ROI real** es cuántas de las 12 horas se automatizan (asumimos 10). Se muestra con sensibilidad y proponemos **validarlo en un piloto de 4 semanas** cronometrando horas reales.
- **Cobertura de precios:** una provincia y 5 cadenas, con 56 % de registros de una farmacia. La corrida cortó por *timeout*: es una muestra, no el catálogo completo.
- **Frescura:** el precio es el del día de extracción; para detectar promociones hay que repetir la corrida y comparar.
- **Precios Claros publica precios, no ventas ni stock:** eso lo aporta el bot.
- **Costo de hosting del bot** sin cotizar (hoy corre en una PC del equipo).
- **Sin tests automáticos todavía.**
- Los precios de herramientas (n8n, Apify, AppSheet, FlutterFlow) se consultaron el 23/11/2026 y deben reverificarse.


##Cómo ejecutarlo

**Bot** (Python 3.10+):

```bash
cd bot
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env        # completá tus valores
python main.py
```

En Linux, `pyzbar` necesita `sudo apt install libzbar0`. Más detalle en [`bot/README.md`](bot/README.md).

**Notebooks:** correr en orden `01 → 02 → 03 → 04` (cada uno usa los archivos que deja el anterior); el `00` y el `05` son independientes. Los notebooks esperan una carpeta `data/` que **no se versiona** (ver [`.gitignore`](.gitignore)); si querés correrlos con datos reales, exportá `Ventas_Registradas` a `data/Ventas_Registradas.csv`.

**Dashboard:** `python bot/exportar_dashboard.py` publica la pestaña `Score_Rescate` en Google Sheets; luego se conecta a Looker Studio (pasos en el notebook 03).

##Seguridad y privacidad

- **Ningún secreto va en el código.** Token de Telegram, ID del Sheet, URLs de n8n y claves de API se leen de `.env`, que está en `.gitignore`.
- Nunca subir `.env` ni `credenciales_google.json`. Si un secreto llegó a un commit, **revocarlo** (borrar el archivo no alcanza: queda en el historial).
- Los webhooks de n8n deberían llevar un header secreto de autenticación.
- El bot guarda datos personales de comerciantes (DNI, email, teléfono, ubicación). **No subir exports reales del Sheet ni capturas con datos de personas.**
- Cada comerciante solo ve y modifica **sus propios lotes** (aislamiento por `telegram_id`).
- Todo lo que lee la IA del cuaderno pasa por **confirmación humana** antes de tocar el stock.

## Hoja de ruta

- [ ] Piloto de 4 semanas con un comercio real: medir horas ahorradas, merma y adherencia.
- [ ] Reemplazar datos simulados por `Ventas_Registradas` real y re-ejecutar los notebooks.
- [ ] Integrar el *Score calibrado* y, si supera el umbral, el modelo ML de demanda.
- [ ] Notificaciones proactivas de lotes en rojo.
- [ ] OCR para facturas escaneadas.
- [ ] Ampliar la cobertura de Precios Claros (más provincias, corridas por categoría).
- [ ] Tests automáticos para `modelo_score.py` y `logica_ventas.py`.
- [ ] Alta disponibilidad del bot (hosting) y cotización de operación.

## Equipo

**DataByte.io**, consultora de inteligencia competitiva.

| Rol | Integrante | Responsabilidad |
|---|---|---|
| Business Analyst (líder) | *Zalazar Daniel Ivan* | Mercado, caso de uso, dashboard, costos y pitch |
| Solution Engineer | *Ayelen Alejandra Sanchez* | Automatización (n8n + Apify), bot e integración |
| Data Scientist |  *Morena Angelina Ramirez* | ETL, EDA, modelo y métricas |

## Licencia

Distribuido bajo la licencia **MIT**. Ver [`LICENSE`](LICENSE).

Los datos de precios provienen de [Precios Claros](https://www.preciosclaros.gob.ar/) (fuente pública)

---

<sub>Proyecto académico desarrollado en el marco del Samsung Innovation Campus (Capstone, 3 al 24 de noviembre de 2026).</sub>
