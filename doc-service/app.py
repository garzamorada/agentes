"""Generador de documentos para los agentes de n8n.

POST /documento  → genera HTML, PDF, DOCX, XLSX y/o MD a partir de Markdown + gráficos
GET  /files/...  → descarga de los archivos generados
GET  /health
"""
import datetime
import difflib
import html as htmllib
import io
import json
import mimetypes
import os
import re
import unicodedata
import uuid
from pathlib import Path
from urllib.parse import quote

import markdown as mdlib
import matplotlib

matplotlib.use('Agg')
import secrets  # noqa: E402

import diagramas  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
from docx import Document  # noqa: E402
from docx.shared import Inches, Pt, RGBColor  # noqa: E402
from fastapi import Depends, FastAPI, Header, HTTPException  # noqa: E402
from fastapi.responses import FileResponse, RedirectResponse  # noqa: E402
from openpyxl import Workbook  # noqa: E402
from openpyxl.chart import AreaChart, BarChart, DoughnutChart, LineChart, PieChart, Reference  # noqa: E402
from openpyxl.drawing.image import Image as XLImage  # noqa: E402
from openpyxl.styles import Font, PatternFill  # noqa: E402
from openpyxl.utils import get_column_letter  # noqa: E402
from weasyprint import HTML as WeasyHTML  # noqa: E402

DATA = Path(os.environ.get('DATA_DIR', '/data'))
PUBLIC = os.environ.get('PUBLIC_URL', 'http://localhost:8090').rstrip('/')
# Clave para generar documentos (header X-API-Key). Las descargas de /files siguen libres: los links se abren en el navegador.
API_KEY = os.environ.get('DOC_SERVICE_API_KEY', '')
if not API_KEY:
    raise SystemExit('Falta DOC_SERVICE_API_KEY (ver .env.default)')


def requiere_clave(x_api_key: str = Header(default='')):
    if not secrets.compare_digest(x_api_key, API_KEY):
        raise HTTPException(401, 'Falta o es incorrecta la clave (header X-API-Key)')
FORMATOS = ['html', 'pdf', 'docx', 'xlsx', 'md']
PALETA = ['#2a6fdb', '#e8833a', '#3aa35b', '#c4453c', '#8a5cc2', '#8c6d4f', '#d45d9e', '#6b7280']
PLACEHOLDER = re.compile(r'\[\[\s*gr[aá]fico\s*:\s*(\d+)\s*\]\]', re.I)

DATA.mkdir(parents=True, exist_ok=True)
# python:slim no trae /etc/mime.types: sin esto Office se sirve como text/plain y el navegador no lo descarga
mimetypes.add_type('application/vnd.openxmlformats-officedocument.wordprocessingml.document', '.docx')
mimetypes.add_type('application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', '.xlsx')
app = FastAPI(title='Generador de documentos')


def _resolver_archivo(did, nombre):
    """El archivo pedido o, si el modelo copió mal el link, el más parecido con la misma extensión."""
    raiz = DATA.resolve()
    pedido = (DATA / did / nombre).resolve()
    if not pedido.is_relative_to(raiz):
        return None
    if pedido.is_file():
        return pedido
    ext = Path(nombre).suffix.lower()
    misma = (DATA / did).is_dir()
    # Carpeta correcta: buscar ahí. Carpeta mal copiada: buscar en las más recientes
    carpetas = [DATA / did] if misma else sorted((d for d in DATA.iterdir() if d.is_dir()), reverse=True)[:50]
    cands = [f for d in carpetas for f in d.iterdir()
             if f.is_file() and f.suffix.lower() == ext and not f.name.startswith('_')
             and ('_grafico_' in f.name) == ('_grafico_' in nombre)]
    if not cands:
        return None
    stem = Path(nombre).stem.lower()
    parecido = lambda f: difflib.SequenceMatcher(None, f.stem.lower(), stem).ratio()
    mejor = max(cands, key=parecido)
    if not misma and parecido(mejor) < 0.6:
        return None
    return mejor.resolve()


def _corregir_links(md):
    """Reescribe los links a /files/... que no existen con la URL del archivo real."""
    def fix(m):
        f = _resolver_archivo(m.group(1), m.group(2))
        return f'{PUBLIC}/files/{f.parent.name}/{f.name}' if f else m.group(0)
    return re.sub(re.escape(PUBLIC) + r'/files/([\w\-]+)/([^\s)\]"\'<>]+)', fix, md)


@app.get('/files/{did}/{nombre:path}')
def archivo(did: str, nombre: str, descargar: bool = False):
    f = _resolver_archivo(did, nombre)
    if not f:
        raise HTTPException(404, 'Archivo no encontrado')
    if (f.parent.name, f.name) != (did, nombre):
        return RedirectResponse(f'/files/{f.parent.name}/{quote(f.name)}' + ('?descargar=1' if descargar else ''), status_code=307)
    # ?descargar=1 → se baja como archivo (el atributo "download" no funciona entre la web :8095 y este servicio :8090)
    return FileResponse(f, filename=f.name if descargar else None)


@app.get('/health')
def health():
    return {'ok': True}


# ---------------- entrada ----------------

def _lista(valor, por_defecto):
    if valor is None or valor == '':
        return por_defecto
    if isinstance(valor, str):
        valor = valor.strip()
        if valor.startswith('['):
            return json.loads(valor)
        return [v.strip() for v in valor.split(',') if v.strip()]
    return list(valor)


def _reparar_json(texto):
    """Arregla errores típicos de modelos chicos: fences, comas de más/de menos y corchetes sin cerrar."""
    t = texto.strip()
    t = re.sub(r'^```(?:json)?\s*|\s*```$', '', t)
    t = re.sub(r',\s*([\]}])', r'\1', t)                 # coma final antes de cerrar
    t = re.sub(r'}\s*{', '},{', t)                        # objetos pegados
    pila, en_texto, escape = [], False, False
    for c in t:
        if en_texto:
            escape = (c == '\\' and not escape)
            if c == '"' and not escape:
                en_texto = False
            continue
        if c == '"':
            en_texto = True
        elif c in '[{':
            pila.append(']' if c == '[' else '}')
        elif c in ']}' and pila:
            pila.pop()
    return t + ''.join(reversed(pila))


def _graficos_desde_tabla(md, titulo):
    """Si el texto pide gráficos pero no vinieron datos válidos, los arma con la primera tabla numérica."""
    for filas in _tablas_md(md):
        cab, datos = filas[0], filas[1:]
        cols = [c for c in range(1, len(cab))
                if datos and all(isinstance(_num(f[c]) if c < len(f) else '', (int, float)) for f in datos)]
        if cols:
            c = cols[0]                                   # la primera columna numérica
            return [{'tipo': 'bar', 'titulo': cab[c], 'etiquetas': [f[0] for f in datos], 'eje_x': cab[0], 'eje_y': cab[c],
                     'series': [{'nombre': cab[c], 'valores': [_num(f[c]) for f in datos]}]}]
    return []


def _graficos(valor):
    if isinstance(valor, dict):
        valor = [valor]  # un solo gráfico
    try:
        gs = _lista(valor, [])
    except json.JSONDecodeError:
        try:
            gs = json.loads(_reparar_json(valor))
        except json.JSONDecodeError as e:
            raise HTTPException(400, f'graficos_json no es JSON válido: {e}') from e
    if isinstance(gs, dict):
        gs = [gs]
    salida = []
    for g in gs:
        if not isinstance(g, dict):
            continue
        if str(g.get('tipo', '')).lower() in ('diagrama', 'diagram', 'esquema', 'flujo', 'organigrama', 'mapa'):
            try:
                salida.append(diagramas.normalizar(g))
            except ValueError as e:
                raise HTTPException(400, str(e)) from e
            continue
        tipo = str(g.get('tipo', 'bar')).lower().strip()
        tipo = TIPOS.get(tipo, tipo)
        if tipo not in TIPOS_VALIDOS:
            tipo = 'bar'
        series = g.get('series') or []
        if not series and 'valores' in g:
            series = [{'nombre': g.get('titulo') or 'Serie', 'valores': g['valores']}]
        series = [{'nombre': str(s.get('nombre', f'Serie {i + 1}')),
                   'valores': [_num(v) for v in s.get('valores', [])]}
                  for i, s in enumerate(series) if isinstance(s, dict)]
        etiquetas = [str(e) for e in g.get('etiquetas') or g.get('labels') or []]
        if tipo == 'hist' and series and not etiquetas:
            etiquetas = ['']  # el histograma solo necesita los valores
        if not series or not etiquetas:
            raise HTTPException(400, 'Cada gráfico necesita "etiquetas" y "series" (o "valores").')
        colores = [str(c) for c in (g.get('colores') or []) if re.match(r'^#?[0-9a-fA-F]{6}$|^[a-z]+$', str(c))]
        salida.append({'tipo': tipo, 'titulo': str(g.get('titulo', '')), 'etiquetas': etiquetas, 'series': series,
                       'eje_x': str(g.get('eje_x', '')), 'eje_y': str(g.get('eje_y', '')),
                       'mostrar_valores': bool(g.get('mostrar_valores')), 'unidad': str(g.get('unidad', ''))[:12],
                       'colores': ['#' + c.lstrip('#') if re.match(r'^#?[0-9a-fA-F]{6}$', c) else c for c in colores]})
    return salida


# Sinónimos en español → tipo interno
TIPOS = {'barras': 'bar', 'barra': 'bar', 'columnas': 'bar', 'barras_horizontales': 'barh', 'horizontal': 'barh',
         'barras_apiladas': 'stacked', 'apiladas': 'stacked', 'apilado': 'stacked',
         'lineas': 'line', 'línea': 'line', 'linea': 'line', 'líneas': 'line', 'area': 'area', 'área': 'area', 'areas': 'area',
         'torta': 'pie', 'circular': 'pie', 'pastel': 'pie', 'dona': 'donut', 'anillo': 'donut', 'rosca': 'donut',
         'dispersion': 'scatter', 'dispersión': 'scatter', 'puntos': 'scatter',
         'histograma': 'hist', 'distribucion': 'hist', 'distribución': 'hist',
         'mapa_calor': 'heatmap', 'mapa_de_calor': 'heatmap', 'calor': 'heatmap', 'matriz': 'heatmap'}
TIPOS_VALIDOS = ('bar', 'barh', 'stacked', 'line', 'area', 'pie', 'donut', 'scatter', 'hist', 'heatmap')


def _num(v):
    if v in (None, ''):
        return 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return float(re.sub(r'[^0-9.\-]', '', str(v).replace(',', '.')) or 0)


def _slug(texto):
    ascii_ = unicodedata.normalize('NFKD', texto).encode('ascii', 'ignore').decode()   # gráficas → graficas
    s = re.sub(r'[^a-z0-9\-]+', '_', ascii_.strip().lower()).strip('_')
    return (s or 'documento')[:60]


# ---------------- gráficos ----------------
# Tipos con gráfico nativo en Excel; el resto (dispersión, histograma, mapa de calor, diagramas) va como imagen
EXCEL_NATIVO = {'bar': BarChart, 'barh': BarChart, 'stacked': BarChart, 'line': LineChart, 'area': AreaChart,
                'pie': PieChart, 'donut': DoughnutChart}


def _figura(g):
    if g['tipo'] == 'diagrama':
        return diagramas.render(g)
    tipo = g['tipo']
    paleta = (g.get('colores') or []) + PALETA
    unidad = g.get('unidad', '')
    fmt = (lambda v: f'{v:,.0f}{unidad}'.replace(',', '.') if abs(v) >= 100 else f'{v:g}{unidad}')
    alto = 4.2 if tipo != 'barh' else max(3.2, 0.42 * len(g['etiquetas']) + 1.2)
    fig, ax = plt.subplots(figsize=(7.5, alto), dpi=110)
    x = list(range(len(g['etiquetas'])))
    n = len(g['series'])
    if tipo in ('pie', 'donut'):
        s = g['series'][0]
        ax.pie(s['valores'], labels=g['etiquetas'], autopct='%1.1f%%', startangle=90, pctdistance=0.78 if tipo == 'donut' else 0.6,
               colors=paleta[:len(g['etiquetas'])],
               wedgeprops={'linewidth': 1, 'edgecolor': 'white', **({'width': 0.42} if tipo == 'donut' else {})})
        ax.axis('equal')
    elif tipo == 'heatmap':
        datos = [s['valores'] + [0.0] * (len(x) - len(s['valores'])) for s in g['series']]
        im = ax.imshow(datos, cmap='YlGnBu', aspect='auto')
        ax.set_xticks(x, g['etiquetas'], rotation=30 if len(x) > 6 else 0, ha='right' if len(x) > 6 else 'center')
        ax.set_yticks(range(n), [s['nombre'] for s in g['series']])
        if g.get('mostrar_valores') or len(x) * n <= 60:
            alto_v = max(max(f) for f in datos) or 1
            for i, fila in enumerate(datos):
                for j, v in enumerate(fila):
                    ax.text(j, i, fmt(v), ha='center', va='center', fontsize=8, color='white' if v > alto_v * 0.6 else '#1f2937')
        fig.colorbar(im, ax=ax, fraction=0.035, pad=0.02)
    elif tipo == 'hist':
        for i, s in enumerate(g['series']):
            ax.hist(s['valores'], bins='auto', alpha=0.75 if n > 1 else 1, label=s['nombre'], color=paleta[i % len(paleta)],
                    edgecolor='white')
        ax.grid(axis='y', alpha=0.3)
    elif tipo == 'scatter':
        xs = [_num(e) for e in g['etiquetas']]
        for i, s in enumerate(g['series']):
            ax.scatter(xs[:len(s['valores'])], s['valores'], s=46, alpha=0.85, label=s['nombre'], color=paleta[i % len(paleta)])
        ax.grid(alpha=0.3)
    else:
        ancho = 0.8 / n if tipo in ('bar', 'barh') else 0.65
        base = [0.0] * len(x)
        for i, s in enumerate(g['series']):
            color = paleta[i % len(paleta)]
            vals = s['valores'] + [0.0] * (len(x) - len(s['valores']))
            if tipo == 'bar':
                barras = ax.bar([p + (i - (n - 1) / 2) * ancho for p in x], vals, ancho, label=s['nombre'], color=color)
            elif tipo == 'barh':
                barras = ax.barh([p + (i - (n - 1) / 2) * ancho for p in x], vals, ancho, label=s['nombre'], color=color)
            elif tipo == 'stacked':
                barras = ax.bar(x, vals, ancho, bottom=base, label=s['nombre'], color=color)
                base = [b + v for b, v in zip(base, vals, strict=False)]
            elif tipo == 'area':
                ax.fill_between(x, vals, alpha=0.35, color=color)
                ax.plot(x, vals, linewidth=2, label=s['nombre'], color=color)
                barras = None
            else:
                ax.plot(x, vals, marker='o', linewidth=2, label=s['nombre'], color=color)
                barras = None
                if g.get('mostrar_valores'):
                    for xi, v in zip(x, vals, strict=False):
                        ax.annotate(fmt(v), (xi, v), textcoords='offset points', xytext=(0, 6), ha='center', fontsize=8)
            if barras is not None and g.get('mostrar_valores'):
                ax.bar_label(barras, labels=[fmt(v) for v in vals], fontsize=8, padding=2,
                             label_type='center' if tipo == 'stacked' else 'edge')
        if tipo == 'barh':
            ax.set_yticks(x, g['etiquetas'])
            ax.invert_yaxis()
            ax.grid(axis='x', alpha=0.3)
        else:
            ax.set_xticks(x)
            ax.set_xticklabels(g['etiquetas'], rotation=30 if len(x) > 6 else 0, ha='right' if len(x) > 6 else 'center')
            ax.grid(axis='y', alpha=0.3)
    if tipo not in ('pie', 'donut', 'heatmap'):
        ax.spines[['top', 'right']].set_visible(False)
        if g.get('eje_x'):
            (ax.set_ylabel if tipo == 'barh' else ax.set_xlabel)(g['eje_x'])
        if g.get('eje_y'):
            (ax.set_xlabel if tipo == 'barh' else ax.set_ylabel)(g['eje_y'])
        if n > 1:
            ax.legend(frameon=False)
    if g['titulo']:
        ax.set_title(g['titulo'], fontsize=12, fontweight='bold')
    fig.tight_layout()
    svg, png = io.StringIO(), io.BytesIO()
    fig.savefig(svg, format='svg')
    fig.savefig(png, format='png')
    plt.close(fig)
    svg_txt = svg.getvalue()
    svg_txt = svg_txt[svg_txt.find('<svg'):]
    return svg_txt, png.getvalue()


# ---------------- Markdown ----------------

def _tablas_md(md):
    """Devuelve las tablas Markdown como listas de filas (la primera es el encabezado)."""
    tablas, actual = [], []
    for linea in md.splitlines() + ['']:
        l = linea.strip()
        if l.startswith('|') and l.endswith('|'):
            celdas = [c.strip() for c in l.strip('|').split('|')]
            if not all(re.fullmatch(r':?-{2,}:?', c) for c in celdas if c):
                actual.append(celdas)
        else:
            if len(actual) >= 2:
                tablas.append(actual)
            actual = []
    return tablas


def _num(v):
    t = str(v).strip().replace('$', '').replace('%', '').replace(' ', '')
    if re.fullmatch(r'-?\d{1,3}(\.\d{3})+(,\d+)?', t):
        t = t.replace('.', '').replace(',', '.')
    elif re.fullmatch(r'-?\d+,\d+', t):
        t = t.replace(',', '.')
    try:
        return float(t) if '.' in t else int(t)
    except ValueError:
        return v


def _inline_docx(parrafo, texto):
    """Negrita, cursiva, código y links simples de Markdown dentro de un párrafo DOCX."""
    tokens = re.split(r'(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`|\[[^\]]+\]\([^)]+\))', texto)
    for t in tokens:
        if not t:
            continue
        if t.startswith('**') and t.endswith('**'):
            parrafo.add_run(t[2:-2]).bold = True
        elif t.startswith('`') and t.endswith('`'):
            r = parrafo.add_run(t[1:-1])
            r.font.name = 'Consolas'
        elif t.startswith('[') and '](' in t:
            texto_link, url = re.match(r'\[([^\]]+)\]\(([^)]+)\)', t).groups()
            r = parrafo.add_run(f'{texto_link} ({url})')
            r.font.color.rgb = RGBColor(0x2A, 0x6F, 0xDB)
        elif t.startswith('*') and t.endswith('*') and len(t) > 2:
            parrafo.add_run(t[1:-1]).italic = True
        else:
            parrafo.add_run(t)


def _docx(titulo, md, pngs, ruta):
    doc = Document()
    doc.styles['Normal'].font.name = 'Calibri'
    doc.styles['Normal'].font.size = Pt(11)
    doc.add_heading(titulo, 0)
    usados = set()
    lineas = md.splitlines()
    i = 0
    while i < len(lineas):
        l = lineas[i].rstrip()
        s = l.strip()
        m = PLACEHOLDER.fullmatch(s)
        if m:
            n = int(m.group(1))
            if 1 <= n <= len(pngs):
                doc.add_picture(io.BytesIO(pngs[n - 1]), width=Inches(6))
                usados.add(n)
            i += 1
            continue
        if s.startswith('```'):
            bloque = []
            i += 1
            while i < len(lineas) and not lineas[i].strip().startswith('```'):
                bloque.append(lineas[i])
                i += 1
            p = doc.add_paragraph()
            r = p.add_run('\n'.join(bloque))
            r.font.name = 'Consolas'
            r.font.size = Pt(9)
            i += 1
            continue
        if s.startswith('|') and s.endswith('|'):
            filas = []
            while i < len(lineas) and lineas[i].strip().startswith('|'):
                celdas = [c.strip() for c in lineas[i].strip().strip('|').split('|')]
                if not all(re.fullmatch(r':?-{2,}:?', c) for c in celdas if c):
                    filas.append(celdas)
                i += 1
            if filas:
                cols = max(len(f) for f in filas)
                tabla = doc.add_table(rows=len(filas), cols=cols)
                tabla.style = 'Light Grid Accent 1'
                for r, fila in enumerate(filas):
                    for c in range(cols):
                        tabla.cell(r, c).text = re.sub(r'\*\*|`', '', fila[c]) if c < len(fila) else ''
                doc.add_paragraph()
            continue
        h = re.match(r'(#{1,6})\s+(.*)', s)
        if h:
            doc.add_heading(h.group(2), min(len(h.group(1)), 4))
        elif re.match(r'[-*+]\s+', s):
            _inline_docx(doc.add_paragraph(style='List Bullet'), re.sub(r'^[-*+]\s+', '', s))
        elif re.match(r'\d+[.)]\s+', s):
            _inline_docx(doc.add_paragraph(style='List Number'), re.sub(r'^\d+[.)]\s+', '', s))
        elif s.startswith('>'):
            p = doc.add_paragraph(style='Intense Quote')
            _inline_docx(p, s.lstrip('> '))
        elif s:
            _inline_docx(doc.add_paragraph(), s)
        i += 1
    restantes = [n for n in range(1, len(pngs) + 1) if n not in usados]
    if restantes:
        doc.add_heading('Gráficos', 1)
        for n in restantes:
            doc.add_picture(io.BytesIO(pngs[n - 1]), width=Inches(6))
    doc.save(ruta)


def _xlsx(titulo, md, graficos, ruta):
    wb = Workbook()
    wb.remove(wb.active)
    cab = Font(bold=True, color='FFFFFF')
    fondo = PatternFill('solid', fgColor='2A6FDB')

    def hoja_datos(ws, filas):
        for fila in filas:
            ws.append([_num(c) for c in fila])
        for c in ws[1]:
            c.font, c.fill = cab, fondo
        for idx, col in enumerate(ws.columns, 1):
            ancho = max(len(str(c.value or '')) for c in col)
            ws.column_dimensions[get_column_letter(idx)].width = min(max(10, ancho + 2), 60)
        ws.freeze_panes = 'A2'

    for n, filas in enumerate(_tablas_md(md), 1):
        hoja_datos(wb.create_sheet(f'Tabla {n}'), filas)

    for n, g in enumerate(graficos, 1):
        if g['tipo'] not in EXCEL_NATIVO:
            ws = wb.create_sheet(f'{"Diagrama" if g["tipo"] == "diagrama" else "Gráfico"} {n}')
            ws['A1'] = g['titulo'] or f'{"Diagrama" if g["tipo"] == "diagrama" else "Gráfico"} {n}'
            ws['A1'].font = Font(bold=True, size=13)
            img = XLImage(io.BytesIO(_figura(g)[1]))
            escala = min(1.0, 900 / img.width)
            img.width, img.height = img.width * escala, img.height * escala
            ws.add_image(img, 'A3')
            continue
        ws = wb.create_sheet(f'Gráfico {n}')
        filas = [['Categoría'] + [s['nombre'] for s in g['series']]]
        for k, et in enumerate(g['etiquetas']):
            filas.append([et] + [s['valores'][k] if k < len(s['valores']) else None for s in g['series']])
        hoja_datos(ws, filas)
        ch = EXCEL_NATIVO[g['tipo']]()
        if g['tipo'] == 'barh':
            ch.type = 'bar'
        elif g['tipo'] == 'stacked':
            ch.grouping, ch.overlap = 'stacked', 100
        ch.title = g['titulo'] or f'Gráfico {n}'
        ch.height, ch.width = 9, 16
        ultima_col = 2 if g['tipo'] in ('pie', 'donut') else 1 + len(g['series'])
        datos = Reference(ws, min_col=2, max_col=ultima_col, min_row=1, max_row=len(filas))
        cats = Reference(ws, min_col=1, min_row=2, max_row=len(filas))
        ch.add_data(datos, titles_from_data=True)
        ch.set_categories(cats)
        if g['tipo'] not in ('pie', 'donut'):
            ch.y_axis.title = g['eje_y'] or None
            ch.x_axis.title = g['eje_x'] or None
        ws.add_chart(ch, f'{get_column_letter(len(filas[0]) + 2)}2')

    if not wb.sheetnames:
        ws = wb.create_sheet('Contenido')
        ws.append([titulo])
        ws['A1'].font = Font(bold=True, size=14)
        for linea in md.splitlines():
            ws.append([linea])
        ws.column_dimensions['A'].width = 120
    wb.save(ruta)


CSS = """
:root{--bg:#f6f7f9;--card:#fff;--txt:#1f2328;--sub:#59636e;--brd:#d8dee4;--acc:#2a6fdb;--code:#f1f3f5}
@media (prefers-color-scheme:dark){:root{--bg:#0f1115;--card:#171a21;--txt:#e6e8eb;--sub:#9aa4af;--brd:#2b313b;--acc:#6ea8ff;--code:#1e232c}}
*{box-sizing:border-box}body{margin:0;font:16px/1.6 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;background:var(--bg);color:var(--txt)}
.wrap{max-width:1180px;margin:0 auto;padding:24px 16px;display:grid;grid-template-columns:240px 1fr;gap:24px}
@media (max-width:860px){.wrap{grid-template-columns:1fr}nav.toc{position:static!important}}
header{grid-column:1/-1}h1{margin:0 0 4px;font-size:1.8rem}.meta{color:var(--sub);font-size:.9rem}
nav.toc{position:sticky;top:16px;align-self:start;background:var(--card);border:1px solid var(--brd);border-radius:10px;padding:12px 14px;font-size:.92rem}
nav.toc ul{list-style:none;padding-left:12px;margin:4px 0}nav.toc>div>ul{padding-left:0}nav.toc a{color:var(--txt);text-decoration:none}nav.toc a:hover{color:var(--acc)}
main{background:var(--card);border:1px solid var(--brd);border-radius:10px;padding:24px 28px;min-width:0}
.descargas{grid-column:1/-1;display:flex;flex-wrap:wrap;gap:8px;align-items:center}
.descargas a{display:inline-flex;gap:6px;align-items:center;padding:6px 12px;border:1px solid var(--brd);border-radius:999px;background:var(--card);color:var(--acc);text-decoration:none;font-size:.9rem}
.descargas a:hover{border-color:var(--acc)}
a{color:var(--acc)}table{border-collapse:collapse;width:100%;margin:16px 0;font-size:.95rem;display:block;overflow-x:auto}
th,td{border:1px solid var(--brd);padding:6px 10px;text-align:left}th{background:var(--code)}
code{background:var(--code);padding:1px 5px;border-radius:4px;font-size:.9em}pre{background:var(--code);padding:12px;border-radius:8px;overflow-x:auto}pre code{padding:0}
figure{margin:20px 0;text-align:center}figure svg{max-width:100%;height:auto;background:#fff;border-radius:8px}
blockquote{margin:12px 0;padding:4px 14px;border-left:4px solid var(--acc);color:var(--sub)}
@media print{nav.toc,.descargas{display:none}.wrap{display:block}main{border:0}}
"""

# PDF: una sola columna, sin tarjetas ni scroll, para que el contenido arranque en la primera página
CSS_PDF = """
@page{size:A4;margin:16mm 14mm}
body{background:#fff;color:#1f2328;font-size:11pt}
.wrap{display:block;max-width:none;padding:0}
nav.toc,.descargas{display:none}
main{border:0;padding:0;background:#fff;border-radius:0}
header{margin-bottom:10px;border-bottom:2px solid #2a6fdb;padding-bottom:6px}
table{display:table;overflow:visible;width:100%;font-size:10pt}
tr,figure,pre{break-inside:avoid}
h2,h3{break-after:avoid}
figure svg{max-width:100%;height:auto}
"""

ICONOS = {'pdf': '📕', 'docx': '📘', 'xlsx': '📗', 'md': '📝', 'html': '🌐', 'png': '🖼️', 'svg': '🖼️'}


def _html(titulo, md, svgs, descargas, para_pdf=False):
    conv = mdlib.Markdown(extensions=['tables', 'fenced_code', 'toc', 'sane_lists'],
                          extension_configs={'toc': {'toc_depth': '2-4'}})
    cuerpo = conv.convert(md)
    usados = set()

    def poner(m):
        n = int(m.group(1))
        if 1 <= n <= len(svgs):
            usados.add(n)
            return f'<figure id="grafico-{n}">{svgs[n - 1]}</figure>'
        return ''

    cuerpo = re.sub(r'<p>\s*' + PLACEHOLDER.pattern + r'\s*</p>', poner, cuerpo, flags=re.I)
    cuerpo = PLACEHOLDER.sub(poner, cuerpo)
    restantes = [n for n in range(1, len(svgs) + 1) if n not in usados]
    if restantes:
        cuerpo += '<h2 id="graficos">Gráficos</h2>' + ''.join(f'<figure id="grafico-{n}">{svgs[n - 1]}</figure>' for n in restantes)
    toc = conv.toc if '<li>' in conv.toc else ''
    if restantes:
        toc = toc.replace('</ul>\n</div>', '<li><a href="#graficos">Gráficos</a></li></ul></div>') if toc else \
            '<div class="toc"><ul><li><a href="#graficos">Gráficos</a></li></ul></div>'
    barra = ''
    if descargas and not para_pdf:
        barra = '<div class="descargas"><strong>Descargas:</strong>' + ''.join(
            f'<a href="{htmllib.escape(u)}" download>{ICONOS.get(n.rsplit(".", 1)[-1], "📎")} {htmllib.escape(n)}</a>'
            for n, u in descargas) + '</div>'
    fecha = datetime.datetime.now().strftime('%d/%m/%Y %H:%M')
    nav = f'<nav class="toc"><strong>Contenido</strong>{toc}</nav>' if toc else '<nav class="toc"><strong>Contenido</strong><p>—</p></nav>'
    return f"""<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{htmllib.escape(titulo)}</title><style>{CSS}{CSS_PDF if para_pdf else ""}</style></head><body><div class="wrap">
<header><h1>{htmllib.escape(titulo)}</h1><div class="meta">Generado el {fecha} por los agentes de n8n</div></header>
{barra}{nav}<main>{cuerpo}</main></div></body></html>"""


@app.post('/imagen', dependencies=[Depends(requiere_clave)])
def imagen(pedido: dict):
    """Un gráfico o diagrama suelto → PNG y/o SVG. Body: {grafico: {...}, formatos: "png,svg", nombre: "..."}."""
    g = pedido.get('grafico') or pedido.get('diagrama') or {k: v for k, v in pedido.items() if k not in ('formatos', 'nombre')}
    graficos = _graficos(g if not isinstance(g, str) else g)
    if not graficos:
        raise HTTPException(400, 'Falta "grafico": {"tipo": "bar|line|pie|...", "etiquetas": [...], "series": [...]} o un diagrama.')
    fmts = [f.strip().lower() for f in str(pedido.get('formatos') or 'png,svg').split(',') if f.strip().lower() in ('png', 'svg')] or ['png']
    did = datetime.datetime.now().strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:6]
    carpeta = DATA / did
    carpeta.mkdir(parents=True)
    base = _slug(str(pedido.get('nombre') or graficos[0].get('titulo') or 'grafico'))
    svg, png = _figura(graficos[0])
    archivos = []
    for f in fmts:
        (carpeta / f'{base}.{f}').write_bytes(png if f == 'png' else (svg.encode('utf-8') if isinstance(svg, str) else svg))
        archivos.append({'formato': f, 'nombre': f'{base}.{f}', 'url': f'{PUBLIC}/files/{did}/{base}.{f}'})
    return {'id': did, 'tipo': graficos[0]['tipo'], 'titulo': graficos[0].get('titulo', ''), 'archivos': archivos}


@app.post('/documento', dependencies=[Depends(requiere_clave)])
def documento(pedido: dict):
    titulo = str(pedido.get('titulo') or 'Documento').strip()[:150]
    md = str(pedido.get('contenido_md') or pedido.get('contenido') or '')
    if '\n' not in md and '\\n' in md:          # saltos de línea que llegaron escapados como texto
        md = md.replace('\\n', '\n').replace('\\t', '\t').replace('\\"', '"')
    try:
        formatos = [f.lower().lstrip('.') for f in _lista(pedido.get('formatos'), ['html'])]
    except json.JSONDecodeError:
        formatos = ['html']
    formatos = [{'excel': 'xlsx', 'xls': 'xlsx', 'word': 'docx', 'doc': 'docx', 'markdown': 'md'}.get(f, f) for f in formatos]
    desconocidos = [f for f in formatos if f not in FORMATOS]
    if desconocidos:
        raise HTTPException(400, f'Formatos no soportados: {desconocidos}. Usá: {FORMATOS}')
    formatos = [f for f in FORMATOS if f in formatos] or ['html']
    try:
        graficos = _graficos(pedido.get('graficos') if 'graficos' in pedido else pedido.get('graficos_json'))
    except HTTPException:
        if not PLACEHOLDER.search(md):
            raise
        graficos = []
    if not graficos and PLACEHOLDER.search(md):
        graficos = _graficos_desde_tabla(md, titulo)
    # Marcas [[grafico:N]] sin datos (el modelo las puso pero no mandó el gráfico): se quitan para completarlas abajo
    md = PLACEHOLDER.sub(lambda m: m.group(0) if 1 <= int(m.group(1)) <= len(graficos) else '', md)
    # Regla: nada de código Mermaid ni árboles ASCII en los documentos → se dibujan como diagramas
    md, extra = diagramas.extraer(md, len(graficos) + 1)
    graficos += extra
    # Secciones que anuncian un diagrama o una estructura pero no lo traen → se dibujan
    md, extra = diagramas.completar(md, len(graficos) + 1)
    graficos += extra
    # Si el Markdown empieza con el mismo título del documento, no repetirlo
    md = re.sub(r'^\s*#\s+' + re.escape(titulo) + r'\s*\n', '', md, count=1, flags=re.I)

    md = _corregir_links(md)
    did = datetime.datetime.now().strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:6]
    carpeta = DATA / did
    carpeta.mkdir(parents=True)
    base = _slug(pedido.get('nombre') or titulo)
    url = lambda nombre: f'{PUBLIC}/files/{did}/{nombre}'
    # Fuente guardada para poder incrustar este documento en otras páginas (por ejemplo la respuesta del chat)
    (carpeta / '_fuente.json').write_text(json.dumps({'titulo': titulo, 'md': md, 'graficos': graficos},
                                                     ensure_ascii=False), encoding='utf-8')

    # Documentos generados antes y enlazados en este texto: se incrustan al final de la versión HTML
    md_html, graficos_html = md, list(graficos)
    for otro in dict.fromkeys(re.findall(re.escape(PUBLIC) + r'/files/([\w\-]+)/', md)):
        fuente = DATA / otro / '_fuente.json'
        if otro == did or not fuente.exists():
            continue
        f = json.loads(fuente.read_text(encoding='utf-8'))
        desplazamiento = len(graficos_html)
        cuerpo = PLACEHOLDER.sub(lambda m, d=desplazamiento: f'[[grafico:{int(m.group(1)) + d}]]', f['md'])
        cuerpo = re.sub(r'^(#{1,5})\s', r'#\1 ', cuerpo, flags=re.M)          # bajar un nivel los títulos
        usados = {int(n) for n in PLACEHOLDER.findall(f['md'])}
        sueltos = ''.join(f'\n\n[[grafico:{n + desplazamiento}]]' for n in range(1, len(f['graficos']) + 1) if n not in usados)
        md_html += f"\n\n## {f['titulo']}\n\n{cuerpo}{sueltos}"
        graficos_html += f['graficos']

    svgs, pngs = [], []
    for n, g in enumerate(graficos, 1):
        svg, png = _figura(g)
        svgs.append(svg)
        pngs.append(png)
        (carpeta / f'{base}_grafico_{n}.png').write_bytes(png)

    nombres = {f: f'{base}.{f}' for f in formatos}
    # Links a otros archivos ya generados (por ejemplo por otros agentes) que aparezcan en el texto
    externos = []
    for u in re.findall(re.escape(PUBLIC) + r'/files/[\w\-./%]+', md):
        if u not in [x[1] for x in externos]:
            externos.append((u.rsplit('/', 1)[-1], u))
    descargas = [(nombres[f], url(nombres[f])) for f in formatos if f != 'html'] + externos

    if 'md' in formatos:
        md_archivo = PLACEHOLDER.sub(lambda m: f'![Gráfico {m.group(1)}]({url(f"{base}_grafico_{m.group(1)}.png")})', md)
        (carpeta / nombres['md']).write_text(f'# {titulo}\n\n{md_archivo}\n', encoding='utf-8')
    if 'xlsx' in formatos:
        _xlsx(titulo, md, graficos, carpeta / nombres['xlsx'])
    if 'docx' in formatos:
        _docx(titulo, md, pngs, carpeta / nombres['docx'])
    if 'html' in formatos:
        svgs_html = svgs + [_figura(g)[0] for g in graficos_html[len(graficos):]]
        (carpeta / nombres['html']).write_text(_html(titulo, md_html, svgs_html, descargas), encoding='utf-8')
    if 'pdf' in formatos:
        WeasyHTML(string=_html(titulo, md, svgs, descargas, para_pdf=True)).write_pdf(carpeta / nombres['pdf'])

    archivos = [{'formato': f, 'nombre': nombres[f], 'url': url(nombres[f])} for f in formatos]
    archivos += [{'formato': 'png', 'nombre': f'{base}_grafico_{n}.png', 'url': url(f'{base}_grafico_{n}.png')}
                 for n in range(1, len(graficos) + 1)]
    return {'id': did, 'titulo': titulo, 'html_url': url(nombres['html']) if 'html' in formatos else None,
            'archivos': archivos, 'graficos': len(graficos), 'tablas': len(_tablas_md(md))}
