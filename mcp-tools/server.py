"""Servidor MCP con todas las herramientas de los agentes (Streamable HTTP en :8092/mcp).

Las usan:
- El agente especialista de n8n (nodo "MCP Client Tool") → todas las herramientas.
- El orquestador de n8n (nodo "MCP Client") → leer_archivo para los adjuntos del chat.

La sesión del navegador sale del parámetro ?sesion= de la URL (n8n pone el id de ejecución),
así cada agente mantiene su pestaña entre llamadas.
"""
import asyncio
import json
import logging
import os
import re
import secrets
from pathlib import Path

import httpx
from mcp.server.fastmcp import Context, FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse

import basicas
import lectura
import navegador as nav
import selenium_nav
import imagenes

DOC_SERVICE = os.environ.get('DOC_SERVICE', 'http://doc-service:8090/documento')
DOC_SERVICE_API_KEY = os.environ.get('DOC_SERVICE_API_KEY', '')
WEB_EVENTOS_TOKEN = os.environ.get('WEB_EVENTOS_TOKEN', '')
# Clave de acceso al MCP (Authorization: Bearer <clave>, X-API-Key o ?key=). Sin clave el servidor no arranca.
MCP_API_KEY = os.environ.get('MCP_API_KEY', '')
if not MCP_API_KEY:
    raise SystemExit('Falta MCP_API_KEY (ver .env.default)')
REGLAS = (Path(__file__).parent / 'reglas.md').read_text(encoding='utf-8')

# Perfiles (?perfil= en la URL): qué herramientas ve cada tipo de agente.
# Los modelos locales chicos se confunden con muchas herramientas y el planificador no debe resolver la tarea él mismo.
PERFILES = {
    'planificador': {'fecha_hora'},
    'basicas': {'calculadora', 'fecha_hora', 'convertir_unidades', 'tabla'},
    'adjuntos': {'leer_archivo'},
}


def _param(req, nombre, defecto):
    try:
        return (req.query_params.get(nombre) if req else None) or defecto
    except (AttributeError, ValueError):
        return defecto


EVENTOS_URL = os.environ.get('EVENTOS_URL', 'http://orquestador-web:8095/api/eventos')
_tareas: set[asyncio.Task] = set()


async def _avisar(evento: dict):
    try:
        async with httpx.AsyncClient(timeout=3) as c:
            await c.post(EVENTOS_URL, json=evento, headers={'X-API-Key': WEB_EVENTOS_TOKEN})
    except httpx.HTTPError:
        pass  # la web local puede no estar levantada: no frena la herramienta


def _resumen_args(nombre: str, args: dict) -> str:
    claves = {'calculadora': ['expresion'], 'buscar_web': ['consulta'], 'navegador': ['motor', 'accion', 'url', 'objetivo', 'texto', 'campos'],
              'leer_url': ['url'], 'convertir_unidades': ['valor', 'de', 'a'], 'generar_documento': ['titulo', 'formatos'],
              'fecha_hora': [], 'tabla': ['formato'], 'crear_grafico': ['formatos'], 'crear_diagrama': ['formatos'],
              'crear_imagen': ['titulo'], 'editar_imagen': ['operacion', 'imagenes']}.get(nombre, list(args)[:2])
    partes = [str(args[k])[:60] for k in claves if args.get(k) not in (None, '', False)]
    return ', '.join(partes)


def _texto_resultado(r) -> str:
    bloques = r[0] if isinstance(r, tuple) else r
    for b in bloques if isinstance(bloques, (list, tuple)) else []:
        if getattr(b, 'text', None):
            return b.text
    return ''


class ServidorConPerfiles(FastMCP):
    def _request(self):
        try:
            return self.get_context().request_context.request
        except (LookupError, ValueError, AttributeError):
            return None

    async def list_tools(self):
        todas = await super().list_tools()
        permitidas = PERFILES.get(_param(self._request(), 'perfil', 'todas'))
        return [t for t in todas if permitidas is None or t.name in permitidas]

    async def call_tool(self, name, arguments):
        """Además de ejecutar la herramienta, avisa a la web local qué se está usando (si el pedido viene de un chat)."""
        req = self._request()
        chat, agente = _param(req, 'chat', ''), _param(req, 'agente', '')
        if chat:
            base = {'chat': chat, 'agente': agente, 'herramienta': name}
            t = asyncio.create_task(_avisar({**base, 'tipo': 'herramienta',
                                             'texto': f'{agente}: {name}({_resumen_args(name, arguments or {})})'}))
            _tareas.add(t)
            t.add_done_callback(_tareas.discard)
        r = await super().call_tool(name, arguments)
        if chat:
            res = ' '.join(_texto_resultado(r).split())[:140]
            t = asyncio.create_task(_avisar({**base, 'tipo': 'resultado', 'texto': f'{name} → {res}'}))
            _tareas.add(t)
            t.add_done_callback(_tareas.discard)
        return r


mcp = ServidorConPerfiles('herramientas-agentes', instructions=REGLAS, host='0.0.0.0', port=8092,
                          stateless_http=True, json_response=True)


def _sesion(ctx: Context) -> str:
    try:
        return _param(ctx.request_context.request, 'sesion', 'default')
    except (AttributeError, ValueError):
        return 'default'


# ---------- básicas ----------
@mcp.tool()
def calculadora(expresion: str) -> str:
    """Calcula una expresión matemática exacta. Usala para CUALQUIER cuenta (nunca calcules de memoria).
    Ejemplos: "0.15*2340", "15% de 2340", "(120+80)/2", "sqrt(2)", "round(10/3, 2)", "2^10".
    Días entre fechas: "2027-01-01 - 2026-10-30" (formato AAAA-MM-DD; usá fecha_hora para saber hoy)."""
    return basicas.calcular(expresion)


@mcp.tool()
def fecha_hora(zona: str = 'America/Argentina/Buenos_Aires') -> str:
    """Fecha y hora actual. Usala para "hoy", "ahora", plazos, edades y vencimientos. Sin parámetros = Argentina."""
    return basicas.fecha_hora(zona)


@mcp.tool()
def convertir_unidades(valor: float, de: str, a: str) -> str:
    """Convierte un valor entre unidades: longitud (m, km, mi, ft, in), masa (kg, g, lb, oz), volumen (l, ml, gal),
    área (m2, ha, acre), tiempo (s, min, h, dia, semana, mes, año), datos (MB, GB, GiB, TB), velocidad (km/h, mph, m/s),
    energía (J, kWh, kcal, BTU), presión (Pa, bar, atm, psi) y temperatura (C, F, K). Ej: valor=72, de="F", a="C"."""
    return basicas.convertir_unidades(valor, de, a)


@mcp.tool()
def tabla(datos_json: str, formato: str = 'markdown') -> str:
    """Convierte un array JSON de objetos en una tabla Markdown o CSV.
    Ej: datos_json='[{"producto":"A","precio":10}]', formato="markdown" o "csv"."""
    return basicas.tabla(datos_json, formato)


# ---------- lectura ----------
def _formatear(r: dict) -> str:
    extra = ', recortado' if r.get('truncado') else ''
    return f'Archivo "{r["archivo"]}" ({r["tipo"]}{extra}):\n{r["texto"]}'


@mcp.tool()
async def leer_url(url: str) -> str:
    """Descarga un ARCHIVO por URL y devuelve su texto: PDF, Word (.docx), Excel (.xlsx/.xls), CSV, JSON o TXT.
    Para páginas web usá navegador (accion="abrir")."""
    return _formatear(await lectura.leer_url(url))


@mcp.tool()
def leer_archivo(contenido_base64: str, nombre: str, mime: str = '') -> dict:
    """Convierte a texto un archivo recibido en base64 (adjuntos del chat): PDF, Word, Excel, CSV, JSON o TXT.
    Devuelve {archivo, tipo, truncado, texto}."""
    return lectura.leer_base64(contenido_base64, nombre, mime)


# ---------- documentos ----------
@mcp.tool()
async def generar_documento(titulo: str, contenido_md: str, formatos: str = 'html,pdf', graficos_json: str = '') -> str:
    """Genera archivos descargables (html, pdf, docx, xlsx, md) desde Markdown, con tablas, gráficos y diagramas.
    Llamala UNA vez, al final, con todo el contenido, y copiá los links que devuelve tal cual en tu respuesta.
    - contenido_md: títulos (##), listas, tablas |a|b|; para ubicar un gráfico escribí [[grafico:1]].
    - formatos: separados por coma (html, pdf, docx, xlsx, md).
    - graficos_json: array JSON. Gráfico: {"tipo":"bar|line|pie","titulo":"...","etiquetas":["Ene","Feb"],
      "series":[{"nombre":"Ventas","valores":[10,20]}]}. Diagrama (nunca Mermaid ni árboles ASCII):
      {"tipo":"diagrama","nodos":[{"id":"a","texto":"Inicio","forma":"circulo|recuadro|globo|rombo"}],
      "flechas":[{"de":"a","a":"b","texto":""}]}. Vacío si no hay."""
    try:
        async with httpx.AsyncClient(timeout=120) as c:
            r = await c.post(DOC_SERVICE, headers={'X-API-Key': DOC_SERVICE_API_KEY}, json={'titulo': titulo, 'contenido_md': contenido_md,
                                                 'formatos': formatos or 'html', 'graficos_json': graficos_json or ''})
        d = r.json()
    except (httpx.HTTPError, ValueError) as e:
        return f'Error al generar el documento: {e}. Probá de nuevo.'
    if r.status_code >= 400 or not d.get('archivos'):
        return f'Error al generar el documento: {str(d.get("detail") or d)[:400]}. Corregí los datos y volvé a intentar.'
    links = '\n'.join(f'- [{a["nombre"]}]({a["url"]})' for a in d['archivos'] if a['formato'] != 'png')
    return (f'Documento generado ({d.get("graficos", 0)} gráficos, {d.get("tablas", 0)} tablas). '
            f'Copiá estos links tal cual en tu respuesta:\n{links}')


# ---------- gráficos e imágenes ----------
async def _imagen_doc_service(grafico, formatos: str, nombre: str) -> str:
    """Pide a doc-service un gráfico o diagrama suelto (PNG/SVG) y devuelve los links."""
    if isinstance(grafico, str):
        try:
            grafico = json.loads(grafico)
        except json.JSONDecodeError as e:
            return f'El JSON no es válido ({e}). Revisá comillas y corchetes.'
    try:
        async with httpx.AsyncClient(timeout=90) as c:
            r = await c.post(DOC_SERVICE.rsplit('/', 1)[0] + '/imagen', headers={'X-API-Key': DOC_SERVICE_API_KEY},
                             json={'grafico': grafico, 'formatos': formatos or 'png,svg', 'nombre': nombre})
        d = r.json()
    except (httpx.HTTPError, ValueError) as e:
        return f'Error al generar la imagen: {e}. Probá de nuevo.'
    if r.status_code >= 400:
        return f'Error: {str(d.get("detail") or d)[:400]}. Corregí los datos y volvé a intentar.'
    png = next((a['url'] for a in d['archivos'] if a['formato'] == 'png'), d['archivos'][0]['url'])
    links = '\n'.join(f'- [{a["nombre"]}]({a["url"]})' for a in d['archivos'])
    return (f'{"Diagrama" if d["tipo"] == "diagrama" else "Gráfico"} "{d.get("titulo") or nombre}" generado.\n'
            f'Mostralo en tu respuesta con: ![{d.get("titulo") or "gráfico"}]({png})\nDescargas:\n{links}')


@mcp.tool()
async def crear_grafico(grafico_json: str, formatos: str = 'png,svg', nombre: str = '') -> str:
    """Crea un gráfico suelto (imagen PNG y SVG) para mostrar en la respuesta. Para gráficos DENTRO de un documento
    usá generar_documento con graficos_json.
    grafico_json: {"tipo": "...", "titulo": "...", "etiquetas": [...], "series": [{"nombre": "...", "valores": [...]}],
      "eje_x": "...", "eje_y": "...", "unidad": "%", "mostrar_valores": true, "colores": ["#76b900", ...]}
    tipos: barras | barras_horizontales | apiladas | linea | area | torta | dona | dispersion (etiquetas = valores X
      numéricos) | histograma (solo "valores") | mapa_calor (cada serie es una fila).
    Una sola serie: podés usar "valores": [...] en lugar de "series"."""
    return await _imagen_doc_service(grafico_json, formatos, nombre)


@mcp.tool()
async def crear_diagrama(diagrama_json: str, formatos: str = 'png,svg', nombre: str = '') -> str:
    """Crea un diagrama visual suelto (flujo, proceso, organigrama, arquitectura, mapa conceptual) en PNG y SVG.
    Nunca uses Mermaid ni árboles ASCII: usá esto.
    diagrama_json: {"titulo": "...", "direccion": "TB|LR",
      "nodos": [{"id": "a", "texto": "Inicio", "forma": "circulo|recuadro|globo|elipse|rombo|nota|cilindro|hexagono"}],
      "flechas": [{"de": "a", "a": "b", "texto": "opcional", "estilo": "punteada|gruesa|linea"}]}"""
    if isinstance(diagrama_json, str):
        try:
            diagrama_json = json.loads(diagrama_json)
        except json.JSONDecodeError as e:
            return f'El JSON no es válido ({e}).'
    if isinstance(diagrama_json, dict):
        diagrama_json = {'tipo': 'diagrama', **diagrama_json}
    return await _imagen_doc_service(diagrama_json, formatos, nombre)


@mcp.tool()
def crear_imagen(titulo: str, subtitulo: str = '', ancho: int = 1200, alto: int = 630, color1: str = '#0f172a',
                 color2: str = '#76b900', color_texto: str = '#ffffff', estilo: str = 'degradado') -> str:
    """Crea una imagen con texto (sin IA): portada, banner, placa para redes, encabezado de presentación.
    estilo: "degradado" (color1 → color2), "diagonal" o "liso". Tamaños típicos: 1200x630 (redes/link),
    1920x1080 (presentación), 1080x1080 (cuadrada), 1500x500 (banner).
    No genera fotos ni ilustraciones."""
    return imagenes.crear(titulo, subtitulo, ancho, alto, color1, color2, color_texto, estilo)['resultado']


@mcp.tool()
async def editar_imagen(imagenes_urls: str, operacion: str, parametros: str = '') -> str:
    """Edita imágenes: capturas del navegador, gráficos generados o imágenes públicas por URL.
    imagenes_urls: URL de la imagen (para "collage", varias separadas por coma o lista JSON).
    operacion y parametros (JSON):
    - "redimensionar": {"ancho": 800} y/o {"alto": 600} (mantiene la proporción si das uno solo)
    - "recortar": {"x": 0, "y": 0, "ancho": 500, "alto": 300} o {"forma": "cuadrado"}
    - "texto": {"texto": "...", "posicion": "abajo|arriba|centro", "tamano": 40, "color": "#fff", "fondo": true}
    - "collage": {"columnas": 2, "tamano_celda": 480, "separacion": 12, "fondo": "#ffffff"}
    - "convertir": {"formato": "png|jpg|webp"}   - "rotar": {"grados": 90}   - "grises": {}
    - "borde": {"grosor": 12, "color": "#ffffff"}
    Todas aceptan "formato" (png, jpg, webp) y "nombre" para el archivo de salida."""
    return (await imagenes.editar(imagenes_urls, operacion, parametros))['resultado']


# ---------- web ----------
@mcp.tool()
async def buscar_web(consulta: str) -> str:
    """Busca en la web y devuelve títulos, URLs y resúmenes. Usala para datos actuales o que pueden haber cambiado
    (precios, noticias, versiones, especificaciones) o que no sabés con certeza. Consulta corta: 3 a 8 palabras.
    Después abrí los mejores resultados con navegador (accion="abrir")."""
    r = await nav.accion(nav.Pedido(accion='buscar', consulta=consulta))
    return r['resultado']


@mcp.tool()
async def navegador(accion: str, url: str = '', objetivo: str = '', texto: str = '', enviar: bool = False,
                    campos: str = '', motor: str = 'playwright', ctx: Context = None) -> str:
    """Navegador real (Chromium) con pestaña propia que se mantiene entre llamadas.
    accion: "abrir" (url) | "leer" (más texto de la página actual) | "clic" (objetivo) |
    "escribir" (objetivo, texto, enviar=true para presionar Enter) |
    "completar" (campos = JSON {"etiqueta o nombre del campo": "valor"}; texto, listas desplegables y casillas;
      enviar=true para mandar el formulario) |
    "extraer" (BeautifulSoup sobre la página: objetivo = "tablas" | "listas" | "enlaces" | "titulos" | "campos" |
      "metadatos" | un selector CSS como ".precio") |
    "tecla" (texto: "Enter", "PageDown") | "desplazar" (objetivo: "abajo"/"arriba") |
    "captura" (url opcional; objetivo="completa" = página entera) | "atras" | "cerrar".
    objetivo = el número [N] de la lista "Elementos para interactuar" que devuelve abrir/clic.
    motor: "playwright" (por defecto) o "selenium" (segundo motor: usalo si una página no carga, no responde
    a los clics o se comporta raro con el primero; cada motor tiene su propia pestaña).
    Prohibido: iniciar sesión, contraseñas, datos personales o de pago, comprar, enviar formularios de contacto o publicar."""
    sesion = _sesion(ctx) if ctx else 'default'
    pedido = nav.Pedido(accion=accion, sesion=sesion, url=url, objetivo=str(objetivo), texto=texto,
                        enviar=bool(enviar), campos=campos if isinstance(campos, str) else json.dumps(campos), motor=motor)
    r = await (selenium_nav.accion(pedido) if str(motor).strip().lower() == 'selenium' else nav.accion(pedido))
    return r['resultado']


# ---------- rutas HTTP auxiliares ----------
@mcp.custom_route('/health', methods=['GET'])
async def health(_: Request):
    return JSONResponse({'ok': True, 'sesiones_navegador': len(nav.sesiones), 'sesiones_selenium': len(selenium_nav.sesiones)})


@mcp.custom_route('/reglas', methods=['GET'])
async def reglas(_: Request):
    return PlainTextResponse(REGLAS)


# ---------- seguridad ----------
class RequiereClave:
    """Middleware ASGI: /mcp solo con la clave. /health y /reglas quedan libres (no exponen datos)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'http' and scope['path'].startswith('/mcp'):
            h = {k.decode().lower(): v.decode() for k, v in scope.get('headers', [])}
            q = dict(p.split('=', 1) for p in scope.get('query_string', b'').decode().split('&') if '=' in p)
            dada = h.get('x-api-key') or h.get('authorization', '').removeprefix('Bearer ').strip() or q.get('key', '')
            if not secrets.compare_digest(dada, MCP_API_KEY):
                resp = JSONResponse({'error': 'No autorizado: falta o es incorrecta la clave del MCP'}, status_code=401)
                return await resp(scope, receive, send)
        await self.app(scope, receive, send)


class OcultarClave(logging.Filter):
    """Saca la clave (?key=...) de los logs de acceso."""

    def filter(self, record):
        record.args = tuple(re.sub(r'key=[^&\s"]+', 'key=***', a) if isinstance(a, str) else a for a in (record.args or ()))
        return True


if __name__ == '__main__':
    import uvicorn
    logging.getLogger('uvicorn.access').addFilter(OcultarClave())
    uvicorn.run(RequiereClave(mcp.streamable_http_app()), host='0.0.0.0', port=8092)
