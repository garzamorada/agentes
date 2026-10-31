"""Creación y edición de imágenes con Pillow (sin IA): portadas/banners y operaciones sobre imágenes.

Las imágenes de entrada pueden ser archivos generados por este proyecto (http://localhost:8090/files/...,
p. ej. capturas del navegador o gráficos) o URLs públicas (con el mismo bloqueo de red interna que el navegador).
"""
import datetime
import io
import json
import os
import re
import urllib.parse
import uuid
from pathlib import Path

import httpx
from PIL import Image, ImageColor, ImageDraw, ImageFont, ImageOps

from navegador import UA, host_privado

DATA = Path(os.environ.get('DATA_DIR', '/data'))
PUBLIC = os.environ.get('PUBLIC_URL', 'http://localhost:8090').rstrip('/')
MAX_BYTES = 20 * 1024 * 1024
MAX_LADO = 4096
FUENTES = {'normal': '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf',
           'negrita': '/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf'}
OPERACIONES = ('redimensionar', 'recortar', 'texto', 'collage', 'convertir', 'rotar', 'grises', 'borde')


def _fuente(tam: int, negrita=False):
    try:
        return ImageFont.truetype(FUENTES['negrita' if negrita else 'normal'], tam)
    except OSError:
        return ImageFont.load_default(tam)


def _color(c, defecto):
    try:
        return ImageColor.getrgb(str(c).strip()) if c else ImageColor.getrgb(defecto)
    except ValueError:
        return ImageColor.getrgb(defecto)


def _guardar(img: Image.Image, nombre: str, formato='png') -> dict:
    formato = {'jpeg': 'jpg'}.get(formato.lower(), formato.lower())
    if formato not in ('png', 'jpg', 'webp'):
        formato = 'png'
    carpeta = DATA / f'img-{datetime.datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}'
    carpeta.mkdir(parents=True, exist_ok=True)
    base = re.sub(r'[^a-z0-9\-]+', '_', nombre.lower()).strip('_')[:50] or 'imagen'
    archivo = carpeta / f'{base}.{formato}'
    if formato == 'jpg' and img.mode != 'RGB':
        img = img.convert('RGB')
    img.save(archivo, {'jpg': 'JPEG', 'png': 'PNG', 'webp': 'WEBP'}[formato], **({'quality': 90} if formato != 'png' else {}))
    url = f'{PUBLIC}/files/{carpeta.name}/{archivo.name}'
    return {'url': url, 'ancho': img.width, 'alto': img.height,
            'resultado': f'Imagen {img.width}×{img.height} ({formato.upper()}): {url}\nMostrala con: ![{base}]({url})'}


async def cargar(fuente: str) -> Image.Image:
    """Abre una imagen generada por el proyecto (ruta local) o descargada de una URL pública."""
    fuente = fuente.strip()
    if fuente.startswith(PUBLIC + '/files/'):
        ruta = (DATA / urllib.parse.unquote(fuente[len(PUBLIC) + len('/files/'):])).resolve()
        if not ruta.is_relative_to(DATA.resolve()) or not ruta.is_file():
            raise ValueError(f'no existe el archivo {fuente}')
        datos = ruta.read_bytes()
    else:
        if not fuente.lower().startswith(('http://', 'https://')):
            raise ValueError(f'"{fuente}" no es una URL')

        async def revisar(req):
            if await host_privado(req.url.host):
                raise httpx.HTTPError('por seguridad no se leen direcciones locales ni de la red interna')
        async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers={'User-Agent': UA},
                                     event_hooks={'request': [revisar]}) as c:
            r = await c.get(fuente)
            r.raise_for_status()
            datos = r.content[:MAX_BYTES + 1]
        if len(datos) > MAX_BYTES:
            raise ValueError('la imagen supera 20 MB')
    img = Image.open(io.BytesIO(datos))
    img.load()
    if max(img.size) > MAX_LADO * 2:
        img.thumbnail((MAX_LADO * 2, MAX_LADO * 2))
    return ImageOps.exif_transpose(img)


def _lista(valor) -> list[str]:
    if isinstance(valor, list):
        return [str(v) for v in valor]
    v = str(valor or '').strip()
    if v.startswith('['):
        try:
            return [str(x) for x in json.loads(v)]
        except json.JSONDecodeError:
            pass
    return [x.strip() for x in re.split(r'[\s,]+', v) if x.strip()]


def _texto_multilinea(draw, texto, fuente, ancho_max):
    """Corta el texto en líneas que entren en ancho_max."""
    lineas = []
    for parrafo in str(texto).split('\n'):
        actual = ''
        for palabra in parrafo.split():
            prueba = f'{actual} {palabra}'.strip()
            if draw.textlength(prueba, font=fuente) <= ancho_max or not actual:
                actual = prueba
            else:
                lineas.append(actual)
                actual = palabra
        lineas.append(actual)
    return lineas


def crear(titulo: str, subtitulo='', ancho=1200, alto=630, color1='#0f172a', color2='#76b900', color_texto='#ffffff',
          estilo='degradado', nombre='') -> dict:
    """Portada / banner / placa con título y subtítulo sobre fondo liso o degradado."""
    ancho, alto = max(200, min(int(ancho), MAX_LADO)), max(120, min(int(alto), MAX_LADO))
    c1, c2, ct = _color(color1, '#0f172a'), _color(color2, '#76b900'), _color(color_texto, '#ffffff')
    img = Image.new('RGB', (ancho, alto), c1)
    if estilo != 'liso':
        if estilo == 'diagonal':
            # Degradado más grande que la imagen, rotado y recortado al centro: sin esquinas vacías
            lado = int((ancho ** 2 + alto ** 2) ** 0.5) + 2
            grad = Image.linear_gradient('L').resize((lado, lado)).rotate(-55)
            x0, y0 = (lado - ancho) // 2, (lado - alto) // 2
            grad = grad.crop((x0, y0, x0 + ancho, y0 + alto))
        else:
            grad = Image.linear_gradient('L').resize((ancho, alto))
        img = Image.composite(Image.new('RGB', (ancho, alto), c2), img, grad)
    d = ImageDraw.Draw(img)
    margen = int(ancho * 0.07)
    f_tit = _fuente(max(24, int(alto * 0.11)), negrita=True)
    f_sub = _fuente(max(16, int(alto * 0.055)))
    l_tit = _texto_multilinea(d, titulo, f_tit, ancho - 2 * margen)[:4]
    l_sub = _texto_multilinea(d, subtitulo, f_sub, ancho - 2 * margen)[:3] if subtitulo else []
    alto_tit = sum(f_tit.getbbox(l)[3] + 10 for l in l_tit)
    alto_sub = sum(f_sub.getbbox(l)[3] + 8 for l in l_sub) + (20 if l_sub else 0)
    y = (alto - alto_tit - alto_sub) // 2
    for l in l_tit:
        d.text((margen, y), l, font=f_tit, fill=ct)
        y += f_tit.getbbox(l)[3] + 10
    y += 20
    for l in l_sub:
        d.text((margen, y), l, font=f_sub, fill=ct)
        y += f_sub.getbbox(l)[3] + 8
    d.rectangle([margen, alto - int(alto * 0.06), margen + int(ancho * 0.12), alto - int(alto * 0.06) + 6], fill=c2 if estilo == 'liso' else ct)
    return _guardar(img, nombre or titulo)


async def editar(imagenes: str, operacion: str, parametros: str = '') -> dict:
    op = (operacion or '').strip().lower()
    if op not in OPERACIONES:
        return {'ok': False, 'resultado': f'Operación "{operacion}" desconocida. Usá: {", ".join(OPERACIONES)}.'}
    try:
        p = json.loads(parametros) if parametros and parametros.strip().startswith('{') else {}
    except json.JSONDecodeError as e:
        return {'ok': False, 'resultado': f'"parametros" no es JSON válido ({e}).'}
    fuentes = _lista(imagenes)
    if not fuentes:
        return {'ok': False, 'resultado': 'Falta "imagenes": la URL de la imagen (o varias separadas por coma para un collage).'}
    try:
        imgs = [await cargar(f) for f in (fuentes if op == 'collage' else fuentes[:1])]
    except (ValueError, OSError, httpx.HTTPError) as e:
        return {'ok': False, 'resultado': f'No pude abrir la imagen: {e}'}
    img = imgs[0]
    formato = str(p.get('formato', 'png'))
    try:
        if op == 'redimensionar':
            a, h = p.get('ancho'), p.get('alto')
            if not a and not h:
                return {'ok': False, 'resultado': 'Indicá "ancho" y/o "alto" en parametros.'}
            a = int(a or img.width * int(h) / img.height)
            h = int(h or img.height * int(a) / img.width)
            img = img.resize((min(a, MAX_LADO), min(h, MAX_LADO)), Image.LANCZOS)
        elif op == 'recortar':
            if str(p.get('forma', '')).lower() in ('cuadrado', 'cuadrada'):
                lado = min(img.size)
                img = ImageOps.fit(img, (lado, lado))
            else:
                x, y = int(p.get('x', 0)), int(p.get('y', 0))
                img = img.crop((x, y, x + int(p.get('ancho', img.width - x)), y + int(p.get('alto', img.height - y))))
        elif op == 'texto':
            img = img.convert('RGBA')
            capa = Image.new('RGBA', img.size, (0, 0, 0, 0))
            d = ImageDraw.Draw(capa)
            f = _fuente(int(p.get('tamano', p.get('tamaño', max(18, img.height // 14)))), negrita=bool(p.get('negrita', True)))
            lineas = _texto_multilinea(d, p.get('texto', ''), f, img.width * 0.9)
            alto_txt = sum(f.getbbox(l)[3] + 6 for l in lineas) + 24
            pos = str(p.get('posicion', 'abajo')).lower()
            y0 = 0 if pos == 'arriba' else (img.height - alto_txt) // 2 if pos == 'centro' else img.height - alto_txt
            if p.get('fondo', True):
                d.rectangle([0, y0, img.width, y0 + alto_txt], fill=_color(p.get('color_fondo'), '#000000') + (150,))
            y = y0 + 12
            for l in lineas:
                d.text(((img.width - d.textlength(l, font=f)) / 2, y), l, font=f, fill=_color(p.get('color'), '#ffffff'))
                y += f.getbbox(l)[3] + 6
            img = Image.alpha_composite(img, capa)
        elif op == 'collage':
            cols = max(1, int(p.get('columnas', min(3, len(imgs)))))
            lado = int(p.get('tamano_celda', 480))
            sep = int(p.get('separacion', 12))
            celdas = [ImageOps.contain(i.convert('RGB'), (lado, lado)) for i in imgs]
            filas = (len(celdas) + cols - 1) // cols
            img = Image.new('RGB', (cols * lado + (cols + 1) * sep, filas * lado + (filas + 1) * sep), _color(p.get('fondo'), '#ffffff'))
            for n, c in enumerate(celdas):
                cx = sep + (n % cols) * (lado + sep) + (lado - c.width) // 2
                cy = sep + (n // cols) * (lado + sep) + (lado - c.height) // 2
                img.paste(c, (cx, cy))
        elif op == 'rotar':
            img = img.rotate(-float(p.get('grados', 90)), expand=True, fillcolor='white')
        elif op == 'grises':
            img = ImageOps.grayscale(img)
        elif op == 'borde':
            img = ImageOps.expand(img.convert('RGB'), border=int(p.get('grosor', 12)), fill=_color(p.get('color'), '#ffffff'))
        # 'convertir' solo cambia el formato de salida
    except (ValueError, TypeError) as e:
        return {'ok': False, 'resultado': f'Parámetros inválidos para "{op}": {e}'}
    nombre = p.get('nombre') or f'{op}_{Path(urllib.parse.urlparse(fuentes[0]).path).stem or "imagen"}'
    return {'ok': True, **_guardar(img, nombre, formato)}
