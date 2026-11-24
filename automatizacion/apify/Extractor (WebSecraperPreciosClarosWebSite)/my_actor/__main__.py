import asyncio
import random
import time
import requests
from apify import Actor


# CONFIGURACION

API_BASE = "https://d3e6htiiul5ek9.cloudfront.net/prod"

URL_IMAGEN = "https://imagenes.preciosclaros.gob.ar/productos/{ean}.jpg"

LITE_TEST = 0  # Límite para pruebas

SUCURSALES_CORDOBA = (
    "24-2-157,24-2-59,24-2-83,24-2-314,24-2-74,24-2-300,"
    "24-2-266,9-1-440,9-2-435,24-2-79,2002-1-81,24-2-131,"
    "9-2-441,24-2-58,24-2-66,24-2-101,2002-1-82,24-2-70,"
    "24-2-75,9-2-439,24-2-88,24-2-295,24-2-313,2-1-379,"
    "2002-1-173,9-1-473,24-2-90,24-2-325,9-2-33,23-1-6286"
)

SUCURSALES_POR_CONSULTA = 30

CATALOGO_ZONAS = {
    "Córdoba capital": (-31.4201, -64.1888),
    "CABA": (-34.6037, -58.3816),
    "La Plata": (-34.9214, -57.9544),
    "Mar del Plata": (-38.0055, -57.5426),
    "Bahía Blanca": (-38.7196, -62.2724),
    "Rosario": (-32.9442, -60.6505),
    "Santa Fe": (-31.6333, -60.7000),
    "Paraná": (-31.7333, -60.5297),
    "Mendoza": (-32.8895, -68.8458),
    "San Juan": (-31.5375, -68.5364),
    "San Luis": (-33.2950, -66.3356),
    "Tucumán": (-26.8083, -65.2176),
    "Salta": (-24.7821, -65.4232),
    "Jujuy": (-24.1858, -65.2995),
    "Santiago del Estero": (-27.7951, -64.2615),
    "Catamarca": (-28.4696, -65.7852),
    "La Rioja": (-29.4131, -66.8558),
    "Corrientes": (-27.4692, -58.8306),
    "Resistencia": (-27.4606, -58.9839),
    "Posadas": (-27.3671, -55.8961),
    "Formosa": (-26.1775, -58.1781),
    "Santa Rosa": (-36.6203, -64.2906),
    "Neuquén": (-38.9516, -68.0591),
    "Viedma": (-40.8135, -62.9967),
    "Rawson": (-43.3002, -65.1023),
    "Comodoro Rivadavia": (-45.8641, -67.4966),
    "Río Gallegos": (-51.6230, -69.2168),
    "Ushuaia": (-54.8019, -68.3030),
}

ZONAS_POR_DEFECTO = ["Córdoba capital"]

CATEGORIAS = {
    "01": "Alimentos congelados",
    "02": "Almacén",
    "03": "Bebés",
    "04": "Bebidas con alcohol",
    "05": "Bebidas sin alcohol",
    "06": "Frescos",
    "07": "Limpieza",
    "08": "Mascotas",
    "09": "Perfumería y cuidado personal",
    "50": "Electrodomésticos y equipamiento para el hogar",
    "70": "Materiales para la construcción",
}

PROVINCIAS = {
    "AR-A": "Salta",
    "AR-B": "Buenos Aires",
    "AR-C": "Ciudad Autónoma de Buenos Aires",
    "AR-D": "San Luis",
    "AR-E": "Entre Ríos",
    "AR-F": "La Rioja",
    "AR-G": "Santiago del Estero",
    "AR-H": "Chaco",
    "AR-J": "San Juan",
    "AR-K": "Catamarca",
    "AR-L": "La Pampa",
    "AR-M": "Mendoza",
    "AR-N": "Misiones",
    "AR-P": "Formosa",
    "AR-Q": "Neuquén",
    "AR-R": "Río Negro",
    "AR-S": "Santa Fe",
    "AR-T": "Tucumán",
    "AR-U": "Chubut",
    "AR-V": "Tierra del Fuego",
    "AR-W": "Corrientes",
    "AR-X": "Córdoba",
    "AR-Y": "Jujuy",
    "AR-Z": "Santa Cruz",
}

HEADERS = {
    "Accept": "application/json, text/plain, /",
    "Referer": "https://www.preciosclaros.gob.ar/",
    "User-Agent": "Mozilla/5.0",
}

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
]

PAUSA_MIN = 0.6
PAUSA_MAX = 1.2

MAX_REINTENTOS = 6
ESPERA_BASE = 5

session = requests.Session()
session.headers.update(HEADERS)


def renovar_sesion():
    global session
    session = requests.Session()
    session.headers.update(HEADERS)
    session.headers["User-Agent"] = random.choice(USER_AGENTS)


def pedir_json(url, params=None):
    ultimo_error = None
    for intento in range(MAX_REINTENTOS):
        try:
            response = session.get(url, params=params, timeout=60)
            if response.status_code in (403, 429) or response.status_code >= 500:
                raise requests.HTTPError(f"{response.status_code} al pedir {url}", response=response)
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError) as error:
            ultimo_error = error
            if intento == MAX_REINTENTOS - 1:
                break
            espera = ESPERA_BASE * (2 ** intento) + random.uniform(0, 2)
            time.sleep(espera)
            renovar_sesion()
    raise ultimo_error


def limpiar(valor):
    if valor is None:
        return None
    if isinstance(valor, str):
        valor = valor.strip()
        return valor or None
    return valor


def a_numero(valor):
    valor = limpiar(valor)
    if valor is None:
        return None
    try:
        return float(valor)
    except (TypeError, ValueError):
        return None


def extraer_lista(data, claves):
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        return []
    for clave in claves:
        valor = data.get(clave)
        if isinstance(valor, list):
            return valor
    return []


def obtener_lista_productos(data):
    return extraer_lista(data, ("productos", "resultado", "results", "items"))


def codigo_sucursal(s):
    if not isinstance(s, dict):
        return None
    sucursal_id = limpiar(s.get("id"))
    if sucursal_id is not None and str(sucursal_id).count("-") == 2:
        return str(sucursal_id)
    comercio = limpiar(s.get("comercioId"))
    bandera = limpiar(s.get("banderaId"))
    if None in (comercio, bandera, sucursal_id):
        return None
    return f"{comercio}-{bandera}-{sucursal_id}"


def buscar_sucursales_cercanas(lat, lng, limite=SUCURSALES_POR_CONSULTA):
    data = pedir_json(f"{API_BASE}/sucursales", {"lat": lat, "lng": lng, "limit": limite})
    lista = extraer_lista(data, ("sucursales", "resultado", "results", "items"))
    codigos = []
    for s in lista:
        codigo = codigo_sucursal(s)
        if codigo:
            codigos.append(codigo)
    return codigos


def dividir_en_grupos(lista, tamano):
    return [lista[i:i + tamano] for i in range(0, len(lista), tamano)]


def armar_zonas(nombres_zonas):
    zonas = []
    vistas = set()
    for nombre in nombres_zonas:
        if nombre not in CATALOGO_ZONAS:
            print(f"Zona desconocida, se omite: {nombre}")
            continue
        lat, lng = CATALOGO_ZONAS[nombre]
        print(f"Buscando sucursales de {nombre}...")
        try:
            codigos = buscar_sucursales_cercanas(lat, lng)
        except Exception as error:
            print(f"  No se pudo consultar /sucursales: {error}")
            codigos = []

        if not codigos and nombre == "Córdoba capital":
            print("  Se usa la lista fija de Córdoba como respaldo.")
            codigos = SUCURSALES_CORDOBA.split(",")

        nuevos = [c for c in codigos if c not in vistas]
        vistas.update(nuevos)

        if not nuevos:
            print(f"  {nombre}: sin sucursales nuevas, se omite.")
            continue

        print(f"  {nombre}: {len(nuevos)} sucursales.")
        grupos = dividir_en_grupos(nuevos, SUCURSALES_POR_CONSULTA)
        for i, grupo in enumerate(grupos, start=1):
            etiqueta = nombre if len(grupos) == 1 else f"{nombre} ({i})"
            zonas.append((etiqueta, ",".join(grupo)))
        time.sleep(random.uniform(PAUSA_MIN, PAUSA_MAX))
    return zonas


def resolver_nombres_zonas(entrada):
    zonas = (entrada or {}).get("zonas")
    if not zonas:
        return list(ZONAS_POR_DEFECTO)

    if isinstance(zonas, str):
        if zonas.strip().lower() == "todas":
            return list(CATALOGO_ZONAS.keys())
        return [z.strip() for z in zonas.split(",") if z.strip()]

    if isinstance(zonas, list):
        if len(zonas) == 1 and str(zonas[0]).strip().lower() == "todas":
            return list(CATALOGO_ZONAS.keys())
        return [str(z).strip() for z in zonas if str(z).strip()]

    return list(ZONAS_POR_DEFECTO)


def obtener_detalle_producto(ean, array_sucursales):
    params = {
        "limit": SUCURSALES_POR_CONSULTA,
        "id_producto": ean,
        "array_sucursales": array_sucursales,
    }
    return pedir_json(f"{API_BASE}/producto", params)


def obtener_producto_base(detalle):
    if not isinstance(detalle, dict):
        return {}
    producto = detalle.get("producto")
    if isinstance(producto, dict):
        return producto
    return detalle


def obtener_sucursales(detalle):
    if not isinstance(detalle, dict):
        return []
    sucursales = detalle.get("sucursales", [])
    return sucursales if isinstance(sucursales, list) else []


def sucursal_tiene_producto(sucursal):
    return (
        isinstance(sucursal, dict)
        and isinstance(sucursal.get("preciosProducto"), dict)
    )


def construir_registro_sucursal(
    sucursal,
    ean,
    nombre,
    marca,
    presentacion,
    categoria_nombre,
    precio_min,
    precio_max,
):
    precios = sucursal.get("preciosProducto") or {}
    provincia_codigo = limpiar(sucursal.get("provincia"))
    provincia = PROVINCIAS.get(provincia_codigo, provincia_codigo)

    precio_lista = limpiar(precios.get("precioLista"))
    if precio_lista is None:
        precio_lista = limpiar(precios.get("precio_unitario_con_iva"))

    return {
        "categoria": categoria_nombre,
        "comercio": limpiar(sucursal.get("banderaDescripcion")),
        "direccion": limpiar(sucursal.get("direccion")),
        "ean": ean,
        "imagen": URL_IMAGEN.format(ean=ean),
        "latitud": a_numero(sucursal.get("lat")),
        "localidad": limpiar(sucursal.get("localidad")),
        "longitud": a_numero(sucursal.get("lng")),
        "marca": marca,
        "precio_lista": precio_lista,
        "precio_max_producto": precio_max,
        "precio_min_producto": precio_min,
        "presentacion": presentacion,
        "producto": nombre,
        "provincia": provincia,
    }


async def procesar_zona(nombre_zona, array_sucursales, totales):
    eans_vistos = set()
    for categoria_id, categoria_nombre in CATEGORIAS.items():
        print(f"\n[{nombre_zona}] Categoria: {categoria_nombre}")
        offset = 0
        limite = 100

        while True:
            params = {
                "id_categoria": categoria_id,
                "array_sucursales": array_sucursales,
                "offset": offset,
                "limit": limite,
                "sort": "-cant_sucursales_disponible",
            }

            try:
                respuesta = await asyncio.to_thread(
                    pedir_json, f"{API_BASE}/productos", params
                )
            except Exception as error:
                print(f"Error listando categoria {categoria_id}, offset {offset}: {error}")
                break

            productos = obtener_lista_productos(respuesta)
            if not productos:
                print("No hay mas productos en esta pagina.")
                break

            print(f"Offset {offset}: {len(productos)} productos recibidos")

            for producto_lista in productos:
                if not isinstance(producto_lista, dict):
                    continue

                ean = producto_lista.get("id")
                if not ean:
                    continue

                ean = str(ean).strip()
                if ean in eans_vistos:
                    continue

                eans_vistos.add(ean)
                await asyncio.sleep(random.uniform(PAUSA_MIN, PAUSA_MAX))

                try:
                    detalle = await asyncio.to_thread(
                        obtener_detalle_producto, ean, array_sucursales
                    )
                except Exception as error:
                    print(f"Error detalle EAN {ean}: {error}")
                    continue

                producto = obtener_producto_base(detalle)
                sucursales = [
                    s for s in obtener_sucursales(detalle)
                    if sucursal_tiene_producto(s)
                ]

                if not sucursales:
                    totales["productos"] += 1
                    continue

                nombre = producto.get("nombre") or producto_lista.get("nombre")
                marca = producto.get("marca") or producto_lista.get("marca")
                presentacion = (
                    producto.get("presentacion")
                    or producto_lista.get("presentacion")
                )
                precio_min = (
                    producto.get("precioMin")
                    if producto.get("precioMin") is not None
                    else producto_lista.get("precioMin")
                )
                precio_max = (
                    producto.get("precioMax")
                    if producto.get("precioMax") is not None
                    else producto_lista.get("precioMax")
                )

                for sucursal in sucursales:
                    registro = construir_registro_sucursal(
                        sucursal,
                        ean,
                        nombre,
                        marca,
                        presentacion,
                        categoria_nombre,
                        precio_min,
                        precio_max,
                    )

                    await Actor.push_data(registro)
                    totales["sucursales"] += 1
                    if LITE_TEST and totales["sucursales"] >= LITE_TEST:
                        print(f"\n[TEST] Límite de {LITE_TEST} filas alcanzado.")
                        return

                totales["productos"] += 1

            offset += limite
            total_api = respuesta.get("total") if isinstance(respuesta, dict) else None
            if total_api is not None and offset >= total_api:
                break
            if len(productos) < limite:
                break


async def main():
    async with Actor:
        entrada = await Actor.get_input() or {}
        print("Iniciando extractor de Precios Claros")

        nombres_zonas = resolver_nombres_zonas(entrada)
        print(f"Zonas solicitadas: {', '.join(nombres_zonas)}")

        zonas = await asyncio.to_thread(armar_zonas, nombres_zonas)
        if not zonas:
            print("No se pudo obtener ninguna sucursal. Se usa la lista fija de Córdoba.")
            zonas = [("Córdoba capital", SUCURSALES_CORDOBA)]

        totales = {"productos": 0, "sucursales": 0}

        for nombre_zona, array_sucursales in zonas:
            cantidad = len(array_sucursales.split(","))
            print(f"\n===== ZONA: {nombre_zona} ({cantidad} sucursales) =====")
            await procesar_zona(nombre_zona, array_sucursales, totales)
            if LITE_TEST and totales["sucursales"] >= LITE_TEST:
                break

        print("\n========== FINALIZADO ==========")
        print(f"Zonas procesadas: {len(zonas)}")
        print(f"Productos procesados: {totales['productos']}")
        print(f"Filas de sucursales: {totales['sucursales']}")

if __name__ == "__main__":
    asyncio.run(main())