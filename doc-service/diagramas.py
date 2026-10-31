"""Diagramas visuales (recuadros, círculos, globos, rombos, flechas) con Graphviz.

- normalizar(): valida un diagrama pedido por un agente en graficos_json ({"tipo": "diagrama", ...}).
- extraer():    reemplaza bloques Mermaid y árboles ASCII (├── └──) del Markdown por diagramas dibujados.
- render():     devuelve (svg, png) del diagrama.
"""
import re
import subprocess

FORMAS = {
    'recuadro': ('box', 'rounded,filled'), 'caja': ('box', 'rounded,filled'), 'rectangulo': ('box', 'filled'),
    'circulo': ('circle', 'filled'), 'círculo': ('circle', 'filled'),
    'globo': ('ellipse', 'filled'), 'elipse': ('ellipse', 'filled'), 'ovalo': ('ellipse', 'filled'),
    'rombo': ('diamond', 'filled'), 'decision': ('diamond', 'filled'), 'decisión': ('diamond', 'filled'),
    'nota': ('note', 'filled'), 'base_de_datos': ('cylinder', 'filled'), 'cilindro': ('cylinder', 'filled'),
    'hexagono': ('hexagon', 'filled'), 'hexágono': ('hexagon', 'filled'),
}
# Colores suaves por nivel/grupo: (relleno, borde)
COLORES = [('#e3edfc', '#2a6fdb'), ('#fdeedd', '#e8833a'), ('#e1f3e7', '#3aa35b'), ('#fbe3e1', '#c4453c'),
           ('#ece4f6', '#8a5cc2'), ('#f1ebe4', '#8c6d4f'), ('#fbe4f0', '#d45d9e'), ('#eceef1', '#6b7280')]
DIRECCIONES = {'TB', 'TD', 'LR', 'RL', 'BT'}


def _txt(s):
    return str(s).replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n')


def normalizar(g):
    nodos, ids = [], set()
    for i, n in enumerate(g.get('nodos') or g.get('nodes') or []):
        if isinstance(n, str):
            n = {'id': n, 'texto': n}
        nid = str(n.get('id') or n.get('texto') or f'n{i}')
        ids.add(nid)
        nodos.append({'id': nid, 'texto': str(n.get('texto') or n.get('label') or nid),
                      'forma': str(n.get('forma') or n.get('shape') or 'recuadro').lower(),
                      'grupo': n.get('grupo', n.get('nivel'))})
    flechas = []
    for f in g.get('flechas') or g.get('edges') or g.get('conexiones') or []:
        if isinstance(f, (list, tuple)) and len(f) >= 2:
            f = {'de': f[0], 'a': f[1], 'texto': f[2] if len(f) > 2 else ''}
        de, a = str(f.get('de') or f.get('from') or ''), str(f.get('a') or f.get('to') or '')
        if not de or not a:
            continue
        for x in (de, a):                       # flechas hacia nodos no declarados: se crean
            if x not in ids:
                ids.add(x)
                nodos.append({'id': x, 'texto': x, 'forma': 'recuadro', 'grupo': None})
        flechas.append({'de': de, 'a': a, 'texto': str(f.get('texto') or f.get('label') or ''),
                        'estilo': str(f.get('estilo') or '')})
    if not nodos:
        raise ValueError('Un diagrama necesita "nodos" (y normalmente "flechas").')
    direccion = str(g.get('direccion') or g.get('direction') or 'TB').upper()
    ancho = sum(min(len(n['texto']), 30) for n in nodos) + 6 * len(nodos)
    if direccion in ('LR', 'RL') and (len(nodos) > 6 or ancho > 90):   # horizontal y largo: en A4 quedaría ilegible
        direccion = 'TB'
    return {'tipo': 'diagrama', 'titulo': str(g.get('titulo') or ''), 'nodos': nodos, 'flechas': flechas,
            'direccion': 'TB' if direccion == 'TD' or direccion not in DIRECCIONES else direccion}


def _dot(d):
    grupos = {}
    lineas = ['digraph G {',
              f'rankdir={d["direccion"]}; bgcolor="white"; pad=0.3; nodesep=0.45; ranksep=0.55;',
              f'labelloc=t; fontname="DejaVu Sans Bold"; fontsize=16; label="{_txt(d["titulo"])}";' if d['titulo'] else '',
              'node [fontname="DejaVu Sans", fontsize=12, margin="0.18,0.10", penwidth=1.6];',
              'edge [fontname="DejaVu Sans", fontsize=10, color="#59636e", penwidth=1.4, arrowsize=0.8];']
    for n in d['nodos']:
        forma, estilo = FORMAS.get(n['forma'], FORMAS['recuadro'])
        clave = n['grupo'] if n['grupo'] is not None else n['forma']
        relleno, borde = COLORES[grupos.setdefault(clave, len(grupos)) % len(COLORES)]
        extra = ' width=1.1 fixedsize=false' if forma == 'circle' else ''
        lineas.append(f'"{_txt(n["id"])}" [label="{_txt(n["texto"])}", shape={forma}, style="{estilo}", '
                      f'fillcolor="{relleno}", color="{borde}"{extra}];')
    for f in d['flechas']:
        est = {'punteada': 'dashed', 'dashed': 'dashed', 'gruesa': 'bold', 'bold': 'bold'}.get(f['estilo'], 'solid')
        flecha = 'none' if f['estilo'] in ('linea', 'línea', 'sin_flecha') else 'normal'
        lineas.append(f'"{_txt(f["de"])}" -> "{_txt(f["a"])}" [label="{_txt(f["texto"])}", style={est}, arrowhead={flecha}];')
    lineas.append('}')
    return '\n'.join(l for l in lineas if l)


def render(d):
    fuente = _dot(d).encode('utf-8')
    svg = subprocess.run(['dot', '-Tsvg'], input=fuente, capture_output=True, check=True).stdout.decode('utf-8')
    png = subprocess.run(['dot', '-Tpng', '-Gdpi=150'], input=fuente, capture_output=True, check=True).stdout
    return svg[svg.find('<svg'):], png


# ---------------- Mermaid → diagrama ----------------

NODO_MM = re.compile(r'([\w.\-]+)\s*(\(\(.*?\)\)|\(\[.*?\]\)|\[\[.*?\]\]|\[\(.*?\)\]|\{\{.*?\}\}|\[.*?\]|\(.*?\)|\{.*?\}|>.*?\])?')
FLECHA_MM = re.compile(r'\s*(?:--\s*([^->|]+?)\s*-->|==\s*([^=>|]+?)\s*==>|(-\.->|-->|==>|---|-\.-|->>|-->>|->|--x|--o))\s*(?:\|([^|]*)\|)?\s*')


def _forma_mm(deco):
    if not deco:
        return None, None
    if deco.startswith('(('):
        return deco[2:-2], 'circulo'
    if deco.startswith('(['):
        return deco[2:-2], 'globo'
    if deco.startswith('[('):
        return deco[2:-2], 'cilindro'
    if deco.startswith('{{'):
        return deco[2:-2], 'hexagono'
    if deco.startswith('[['):
        return deco[2:-2], 'recuadro'
    if deco.startswith('{'):
        return deco[1:-1], 'rombo'
    if deco.startswith('('):
        return deco[1:-1], 'globo'
    if deco.startswith('>'):
        return deco[1:-1], 'nota'
    return deco[1:-1], 'recuadro'


def _limpiar(t):
    return re.sub(r'<br\s*/?>', '\n', str(t).strip().strip('"').strip("'"))


def _mermaid(codigo):
    lineas = [l.strip() for l in re.split(r'[\n;]', codigo) if l.strip() and not l.strip().startswith('%%')]
    if not lineas:
        return None
    cab = lineas[0].split()
    tipo = cab[0].lower()
    nodos, flechas, orden = {}, [], []

    def nodo(nid, deco=None, forma=None):
        texto, f = _forma_mm(deco)
        if nid not in nodos:
            nodos[nid] = {'id': nid, 'texto': nid, 'forma': forma or 'recuadro'}
            orden.append(nid)
        if texto is not None:
            nodos[nid]['texto'] = _limpiar(texto)
            nodos[nid]['forma'] = f
        return nid

    if tipo == 'mindmap':                                   # árbol por indentación
        return _arbol([(len(l) - len(l.lstrip()), l.strip()) for l in codigo.splitlines()[1:] if l.strip()], 'LR')

    if tipo == 'sequencediagram':
        for l in lineas[1:]:
            m = re.match(r'(?:participant|actor)\s+(\S+)(?:\s+as\s+(.+))?', l)
            if m:
                nodo(m.group(1))
                nodos[m.group(1)]['texto'] = _limpiar(m.group(2) or m.group(1))
                nodos[m.group(1)]['forma'] = 'globo' if l.startswith('actor') else 'recuadro'
                continue
            m = re.match(r'([\w.\-]+)\s*-[-x>)]*>+[+-]?\s*([\w.\-]+)\s*:\s*(.*)', l)
            if m:
                flechas.append({'de': nodo(m.group(1)), 'a': nodo(m.group(2)), 'texto': f'{len(flechas) + 1}. {m.group(3)}'})
        return {'tipo': 'diagrama', 'titulo': '', 'direccion': 'LR', 'nodos': list(nodos.values()), 'flechas': flechas}

    direccion = cab[1].upper() if len(cab) > 1 and cab[1].upper() in DIRECCIONES else 'TB'
    for l in lineas[1:]:
        if re.match(r'(subgraph|end|classDef|class|style|linkStyle|click|direction)\b', l):
            continue
        pos, previo, etiqueta = 0, None, ''
        while pos < len(l):
            m = NODO_MM.match(l, pos)
            if not m or not m.group(1):
                break
            actual = nodo(m.group(1), m.group(2))
            if previo:
                flechas.append({'de': previo, 'a': actual, 'texto': _limpiar(etiqueta) if etiqueta else '',
                                'estilo': estilo})
            pos = m.end()
            f = FLECHA_MM.match(l, pos)
            if not f or f.end() == pos:
                break
            etiqueta = f.group(1) or f.group(2) or f.group(4) or ''
            simbolo = f.group(3) or ''
            estilo = 'punteada' if '.' in simbolo else 'gruesa' if '=' in simbolo else 'linea' if simbolo in ('---', '-.-') else ''
            previo, pos = actual, f.end()
    if not nodos:
        return None
    return {'tipo': 'diagrama', 'titulo': '', 'direccion': direccion,
            'nodos': [nodos[k] for k in orden], 'flechas': flechas}


# ---------------- árbol ASCII → diagrama ----------------

RAMA = re.compile(r'^((?:[│|]\s{1,4}|\s{2,4})*)(?:├──|└──|├─|└─|\+--|\|--|`--|\\--)\s*(.*)$')


def _arbol(items, direccion='TB'):
    """items: lista de (profundidad, texto). Devuelve diagrama jerárquico."""
    nodos, flechas, pila = [], [], []
    for i, (prof, texto) in enumerate(items):
        texto = re.sub(r'^[-*+]\s+', '', texto).strip()
        if not texto:
            continue
        nid = f'n{i}'
        while pila and pila[-1][0] >= prof:
            pila.pop()
        nivel = len(pila)
        forma = 'circulo' if nivel == 0 and len(texto) <= 14 else 'globo' if nivel == 0 else 'recuadro'
        nodos.append({'id': nid, 'texto': texto, 'forma': forma, 'grupo': nivel})
        if pila:
            flechas.append({'de': pila[-1][1], 'a': nid, 'texto': ''})
        pila.append((prof, nid))
    if len(nodos) < 2:
        return None
    return {'tipo': 'diagrama', 'titulo': '', 'direccion': direccion, 'nodos': nodos, 'flechas': flechas}


def _arbol_ascii(texto):
    items = []
    for l in texto.splitlines():
        if not l.strip():
            continue
        m = RAMA.match(l)
        if m:
            items.append((len(m.group(1)) + 1, m.group(2)))
        elif not items:
            items.append((0, l.strip()))                     # raíz
        else:
            return None                                      # no es un árbol
    return _arbol(items) if any(p > 0 for p, _ in items) else None


TITULO = re.compile(r'^(#{1,6})\s+(.*)$')
CLAVE_FLUJO = re.compile(r'diagrama|flujo|proceso|esquema|circuito|pipeline|workflow', re.I)
CLAVE_ESTRUCTURA = re.compile(r'estructura|carpetas|directorio|árbol|arbol|jerarqu|organigrama', re.I)
ITEM_NUM = re.compile(r'^\s*\d+[.)]\s+(.*)$')
ITEM_RUTA = re.compile(r'^\s*[-*+]\s+`?(/?[\w.\-]+(?:/[\w.\-]*)*/?)`?\s*(?:[–—:-]\s*(.*))?$')


def _corto(texto, largo=38):
    t = re.sub(r'[*`_]', '', texto).strip()
    return t if len(t) <= largo else t[:largo - 1].rstrip() + '…'


def completar(md, inicio):
    """Dibuja los diagramas que el texto anuncia pero no trae:
    - sección "Diagrama / Flujo / Proceso" vacía → flujo con los pasos numerados del documento;
    - sección "Estructura / Carpetas" con lista de rutas → árbol visual debajo de la lista."""
    lineas = md.splitlines()
    titulos = [(i, len(m.group(1)), m.group(2)) for i, l in enumerate(lineas) if (m := TITULO.match(l))]
    pasos = [ITEM_NUM.match(l).group(1) for l in lineas if ITEM_NUM.match(l)]
    inserciones, diagramas = {}, []

    for k, (i, nivel, texto) in enumerate(titulos):
        fin = next((j for j, n, _ in titulos[k + 1:] if n <= nivel), len(lineas))
        cuerpo = lineas[i + 1:fin]
        if any('[[grafico' in l.lower() for l in cuerpo):
            continue
        if CLAVE_ESTRUCTURA.search(texto):
            rutas = [(m.group(1), m.group(2) or '') for l in cuerpo if (m := ITEM_RUTA.match(l))]
            if len(rutas) >= 2:
                nodos = [{'id': 'raiz', 'texto': 'proyecto', 'forma': 'circulo', 'grupo': 0}]
                flechas = []
                for n, (ruta, desc) in enumerate(rutas):
                    etiqueta = ruta + (f'\n{_corto(desc, 30)}' if desc else '')
                    nodos.append({'id': f'r{n}', 'texto': etiqueta, 'forma': 'recuadro', 'grupo': 1})
                    flechas.append({'de': 'raiz', 'a': f'r{n}'})
                ultimo = max(j for j in range(i + 1, fin) if ITEM_RUTA.match(lineas[j]))
                diagramas.append({'tipo': 'diagrama', 'titulo': '', 'direccion': 'LR' if len(rutas) > 4 else 'TB',
                                  'nodos': nodos, 'flechas': flechas})
                inserciones[ultimo] = inicio + len(diagramas) - 1
        elif CLAVE_FLUJO.search(texto) and not any(l.strip() for l in cuerpo if not TITULO.match(l)) and len(pasos) >= 2:
            nombres = [_corto(re.split(r'\s+[–—:-]\s+', p, maxsplit=1)[0]) for p in pasos[:12]]
            nodos = ([{'id': 'ini', 'texto': 'Inicio', 'forma': 'circulo', 'grupo': 0}] +
                     [{'id': f'p{n}', 'texto': t, 'forma': 'recuadro', 'grupo': 1} for n, t in enumerate(nombres)] +
                     [{'id': 'fin', 'texto': 'Fin', 'forma': 'circulo', 'grupo': 2}])
            orden = [n['id'] for n in nodos]
            diagramas.append({'tipo': 'diagrama', 'titulo': '', 'direccion': 'TB' if len(nombres) > 4 else 'LR',
                              'nodos': nodos, 'flechas': [{'de': a, 'a': b} for a, b in zip(orden, orden[1:])]})
            inserciones[i] = inicio + len(diagramas) - 1

    if not diagramas:
        return md, []
    salida = []
    for j, l in enumerate(lineas):
        salida.append(l)
        if j in inserciones:
            salida += ['', f'[[grafico:{inserciones[j]}]]', '']
    return '\n'.join(salida), [normalizar(d) for d in diagramas]


def extraer(md, inicio):
    """Reemplaza bloques Mermaid y árboles ASCII por [[grafico:N]]. Devuelve (md, diagramas)."""
    diagramas = []

    def poner(d):
        diagramas.append(normalizar(d))
        return f'\n[[grafico:{inicio + len(diagramas) - 1}]]\n'

    def bloque(m):
        lang, cuerpo = (m.group(1) or '').lower(), m.group(2)
        try:
            if lang == 'mermaid' or re.match(r'\s*(graph|flowchart|sequenceDiagram|mindmap)\b', cuerpo):
                d = _mermaid(cuerpo)
            elif re.search(r'[├└]──|\+--|\|--|`--', cuerpo):
                d = _arbol_ascii(cuerpo)
            else:
                return m.group(0)
            return poner(d) if d else m.group(0)
        except (ValueError, IndexError):
            return m.group(0)

    md = re.sub(r'```[ \t]*(\w+)?[^\n]*\n(.*?)```', bloque, md, flags=re.S)

    # Árboles ASCII sueltos (fuera de bloques de código): raíz + líneas con ├── / └──
    def suelto(m):
        d = _arbol_ascii(m.group(0))
        return poner(d) if d else m.group(0)

    md = re.sub(r'(?m)^[^\n│├└|`\s][^\n]*\n(?:^[ \t│|]*(?:├──|└──|├─|└─)[^\n]*\n?)+', suelto, md)
    return md, diagramas
