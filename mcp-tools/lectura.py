"""Leer archivos y URLs a texto: PDF, Word, Excel, CSV, JSON, TXT y HTML (antes era un sub-workflow de n8n)."""
import base64
import csv
import io
import json
import urllib.parse

import httpx
from bs4 import BeautifulSoup

from navegador import UA, host_privado

MAX_BYTES = 25 * 1024 * 1024
MAX_CHARS = 15000


def detectar_tipo(nombre: str, mime: str, datos: bytes) -> str:
    ext = nombre.lower().rsplit('.', 1)[-1] if '.' in nombre else ''
    mime = (mime or '').lower()
    if datos[:5] == b'%PDF-' or ext == 'pdf' or 'pdf' in mime:
        return 'pdf'
    if ext in ('xlsx', 'xlsm') or 'spreadsheetml' in mime:
        return 'xlsx'
    if ext == 'xls' or 'ms-excel' in mime:
        return 'xls'
    if ext == 'docx' or 'wordprocessingml' in mime:
        return 'docx'
    if ext == 'csv' or 'csv' in mime:
        return 'csv'
    if ext == 'json' or 'json' in mime:
        return 'json'
    if ext in ('html', 'htm') or 'html' in mime or datos[:200].lstrip().lower().startswith((b'<!doctype html', b'<html')):
        return 'html'
    return 'texto'


def _texto(datos: bytes) -> str:
    for enc in ('utf-8-sig', 'cp1252', 'latin-1'):
        try:
            return datos.decode(enc)
        except UnicodeDecodeError:
            continue
    return datos.decode('utf-8', 'replace')


def extraer(tipo: str, datos: bytes) -> str:
    if tipo == 'pdf':
        from pypdf import PdfReader
        r = PdfReader(io.BytesIO(datos))
        partes = [f'--- Página {i} ---\n{(p.extract_text() or "").strip()}' for i, p in enumerate(r.pages, 1)]
        txt = '\n\n'.join(partes)
        if len(txt.replace('--- Página', '').strip()) < 30 * len(r.pages):
            txt += '\n\n(El PDF casi no tiene texto: probablemente es escaneado y necesita OCR.)'
        return txt
    if tipo == 'xlsx':
        from openpyxl import load_workbook
        wb = load_workbook(io.BytesIO(datos), read_only=True, data_only=True)
        hojas = []
        for ws in wb.worksheets:
            filas = [','.join('' if v is None else str(v) for v in fila) for fila in ws.iter_rows(values_only=True)]
            hojas.append(f'--- Hoja "{ws.title}" ---\n' + '\n'.join(f for f in filas if f.strip(',')))
        return '\n\n'.join(hojas)
    if tipo == 'xls':
        import xlrd
        wb = xlrd.open_workbook(file_contents=datos)
        return '\n\n'.join(f'--- Hoja "{s.name}" ---\n' + '\n'.join(','.join(str(c) for c in s.row_values(i)) for i in range(s.nrows))
                           for s in wb.sheets())
    if tipo == 'docx':
        from docx import Document
        d = Document(io.BytesIO(datos))
        partes = [p.text for p in d.paragraphs if p.text.strip()]
        for t in d.tables:
            partes.append('\n'.join(' | '.join(c.text.strip() for c in fila.cells) for fila in t.rows))
        return '\n'.join(partes)
    if tipo == 'csv':
        filas = list(csv.reader(io.StringIO(_texto(datos))))
        return '\n'.join(','.join(f) for f in filas)
    if tipo == 'json':
        try:
            return json.dumps(json.loads(_texto(datos)), ensure_ascii=False, indent=1)
        except json.JSONDecodeError:
            return _texto(datos)
    if tipo == 'html':
        soup = BeautifulSoup(_texto(datos), 'html.parser')
        for t in soup(['script', 'style', 'nav', 'header', 'footer', 'noscript']):
            t.decompose()
        return '\n'.join(l.strip() for l in soup.get_text('\n').splitlines() if l.strip())
    return _texto(datos)


def a_texto(datos: bytes, nombre: str, mime: str = '') -> dict:
    tipo = detectar_tipo(nombre, mime, datos)
    try:
        texto = extraer(tipo, datos).strip()
    except Exception as e:  # noqa: BLE001 — archivo dañado o formato raro
        return {'archivo': nombre, 'tipo': tipo, 'truncado': False, 'texto': f'Error al leer el archivo ({tipo}): {e}'}
    total = len(texto)
    return {'archivo': nombre, 'tipo': tipo, 'caracteres': total, 'truncado': total > MAX_CHARS,
            'texto': texto[:MAX_CHARS] + (f'\n[... recortado: {MAX_CHARS} de {total} caracteres]' if total > MAX_CHARS else '')}


async def leer_url(url: str) -> dict:
    url = url.strip()
    if not url.lower().startswith(('http://', 'https://')):
        url = 'https://' + url

    async def revisar(req):  # también en cada redirección
        if await host_privado(req.url.host):
            raise httpx.HTTPError('por seguridad no se leen direcciones locales ni de la red interna')

    try:
        async with httpx.AsyncClient(timeout=40, follow_redirects=True, headers={'User-Agent': UA},
                                     event_hooks={'request': [revisar]}) as c, c.stream('GET', url) as r:
            r.raise_for_status()
            datos = b''
            async for trozo in r.aiter_bytes():
                datos += trozo
                if len(datos) > MAX_BYTES:
                    return {'archivo': url, 'tipo': '?', 'truncado': True, 'texto': 'Error: el archivo supera 25 MB.'}
            mime = r.headers.get('content-type', '')
    except httpx.HTTPError as e:
        return {'archivo': url, 'tipo': '?', 'truncado': False, 'texto': f'Error al descargar {url}: {e}'}
    nombre = urllib.parse.unquote(urllib.parse.urlparse(url).path.rsplit('/', 1)[-1]) or url
    return a_texto(datos, nombre, mime)


def leer_base64(contenido: str, nombre: str, mime: str = '') -> dict:
    try:
        datos = base64.b64decode(contenido.split(',', 1)[-1] if contenido.startswith('data:') else contenido)
    except (ValueError, TypeError) as e:
        return {'archivo': nombre, 'tipo': '?', 'truncado': False, 'texto': f'Error: base64 inválido ({e}).'}
    return a_texto(datos, nombre, mime)
