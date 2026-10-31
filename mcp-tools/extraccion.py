"""Extracción de datos de una página con BeautifulSoup (sirve para los dos motores: Playwright y Selenium).

objetivo:
- "tablas"     → tablas HTML en Markdown
- "listas"     → listas (ul/ol) con sus ítems
- "enlaces"    → links con su texto y URL
- "titulos"    → estructura de títulos (h1-h4)
- "campos"     → campos de formulario: etiqueta, nombre, tipo y opciones (para usar después en "completar")
- "metadatos"  → título, descripción y datos Open Graph / JSON-LD
- cualquier otro valor → selector CSS (por ejemplo ".precio", "div.producto h2", "table#cotizaciones td")
"""
import json
import re
import urllib.parse

from bs4 import BeautifulSoup

MAX_FILAS = 40
MAX_TABLAS = 6
MAX_ITEMS = 60


def _txt(el) -> str:
    return re.sub(r'\s+', ' ', el.get_text(' ', strip=True)).strip() if el else ''


def _tabla_md(t) -> str:
    filas = []
    for tr in t.find_all('tr'):
        celdas = [_txt(c).replace('|', '\\|') for c in tr.find_all(['th', 'td'])]
        if any(celdas):
            filas.append(celdas)
    if not filas:
        return ''
    ancho = max(len(f) for f in filas)
    filas = [f + [''] * (ancho - len(f)) for f in filas]
    md = ['| ' + ' | '.join(filas[0]) + ' |', '|' + '---|' * ancho]
    md += ['| ' + ' | '.join(f) + ' |' for f in filas[1:MAX_FILAS + 1]]
    if len(filas) - 1 > MAX_FILAS:
        md.append(f'(… {len(filas) - 1 - MAX_FILAS} filas más)')
    return '\n'.join(md)


def _etiqueta(soup, campo) -> str:
    """Texto de la etiqueta asociada a un campo (label for=, label que lo envuelve, aria-label, placeholder)."""
    if campo.get('id'):
        lab = soup.find('label', attrs={'for': campo['id']})
        if lab:
            return _txt(lab)
    padre = campo.find_parent('label')
    if padre:
        return _txt(padre)
    return campo.get('aria-label') or campo.get('placeholder') or campo.get('title') or ''


def campos_formulario(soup) -> list[dict]:
    out = []
    for c in soup.select('input, select, textarea'):
        tipo = (c.get('type') or c.name).lower()
        if tipo in ('hidden', 'submit', 'button', 'image', 'reset'):
            continue
        d = {'etiqueta': _etiqueta(soup, c)[:80], 'nombre': c.get('name') or '', 'id': c.get('id') or '',
             'tipo': 'select' if c.name == 'select' else ('textarea' if c.name == 'textarea' else tipo)}
        if c.name == 'select':
            d['opciones'] = [_txt(o) or o.get('value', '') for o in c.find_all('option')][:25]
        if tipo in ('checkbox', 'radio') and c.get('value'):
            d['valor'] = c['value']
        if c.has_attr('required'):
            d['obligatorio'] = True
        out.append(d)
    return out


def extraer(html: str, url_base: str, objetivo: str, max_chars: int = 8000) -> dict:
    soup = BeautifulSoup(html, 'html.parser')
    for t in soup(['script', 'style', 'noscript', 'template']):
        if t.get('type') != 'application/ld+json':
            t.decompose()
    obj = (objetivo or 'tablas').strip()
    clave = obj.lower()

    if clave in ('tablas', 'tabla'):
        tablas = [m for m in (_tabla_md(t) for t in soup.find_all('table')) if m][:MAX_TABLAS]
        texto = '\n\n'.join(f'Tabla {i}:\n{t}' for i, t in enumerate(tablas, 1)) or 'La página no tiene tablas HTML.'
    elif clave in ('listas', 'lista'):
        listas = []
        for l in soup.find_all(['ul', 'ol']):
            items = [_txt(li) for li in l.find_all('li', recursive=False) if _txt(li)]
            if len(items) >= 2 and not l.find_parent(['nav', 'header', 'footer']):
                listas.append('\n'.join(f'- {i[:200]}' for i in items[:MAX_ITEMS]))
        texto = '\n\n'.join(listas[:10]) or 'La página no tiene listas con contenido.'
    elif clave in ('enlaces', 'links', 'link'):
        vistos, lineas = set(), []
        for a in soup.find_all('a', href=True):
            href = urllib.parse.urljoin(url_base, a['href'])
            if href.startswith('http') and href not in vistos and _txt(a):
                vistos.add(href)
                lineas.append(f'- {_txt(a)[:90]} → {href}')
        texto = '\n'.join(lineas[:MAX_ITEMS * 2]) or 'La página no tiene enlaces.'
    elif clave in ('titulos', 'títulos', 'estructura'):
        texto = '\n'.join(f'{"  " * (int(h.name[1]) - 1)}- {_txt(h)}' for h in soup.find_all(['h1', 'h2', 'h3', 'h4']) if _txt(h)) \
            or 'La página no tiene títulos.'
    elif clave in ('campos', 'formulario', 'formularios'):
        cs = campos_formulario(soup)
        texto = ('Campos del formulario (para completar usá la etiqueta o el nombre como clave en "campos"):\n' +
                 '\n'.join('- ' + json.dumps(c, ensure_ascii=False) for c in cs)) if cs else 'La página no tiene campos de formulario.'
    elif clave in ('metadatos', 'meta'):
        meta = {'titulo': _txt(soup.title)}
        for m in soup.find_all('meta'):
            k = m.get('name') or m.get('property')
            if k and m.get('content') and (k in ('description', 'keywords', 'author') or k.startswith(('og:', 'article:', 'product:'))):
                meta[k] = m['content'][:300]
        ld = [s.string for s in soup.find_all('script', type='application/ld+json') if s.string]
        texto = json.dumps(meta, ensure_ascii=False, indent=1) + ('\n\nDatos estructurados (JSON-LD):\n' + '\n'.join(x[:2000] for x in ld[:3]) if ld else '')
    else:
        sel = obj[4:].strip() if clave.startswith('css:') else obj
        try:
            encontrados = soup.select(sel)
        except Exception as e:  # noqa: BLE001 — selector mal escrito
            return {'ok': False, 'resultado': f'Selector CSS inválido "{sel}": {e}. Probá con "tablas", "listas", "enlaces", "campos" o un selector válido.'}
        items = [_txt(e) for e in encontrados if _txt(e)]
        texto = (f'{len(items)} elementos para "{sel}":\n' + '\n'.join(f'- {i[:300]}' for i in items[:MAX_ITEMS])) if items \
            else f'No hay elementos con el selector "{sel}".'

    total = len(texto)
    if total > max_chars:
        texto = texto[:max_chars] + f'\n[… recortado: {max_chars} de {total} caracteres]'
    return {'ok': True, 'resultado': f'Extracción "{obj}" de {url_base}:\n{texto}'}
