"""Herramientas simples: calculadora, fecha/hora, conversor de unidades y tablas (antes eran nodos de código en n8n)."""
import ast
import csv
import datetime
import io
import json
import math
import operator
import re
import unicodedata
from zoneinfo import ZoneInfo

# ---------- calculadora (evaluación segura con AST) ----------
_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod, ast.Pow: operator.pow,
        ast.USub: operator.neg, ast.UAdd: operator.pos}
_FUNCS = {'sqrt': math.sqrt, 'raiz': math.sqrt, 'log': math.log, 'ln': math.log, 'log10': math.log10, 'log2': math.log2,
          'exp': math.exp, 'sin': math.sin, 'cos': math.cos, 'tan': math.tan, 'asin': math.asin, 'acos': math.acos,
          'atan': math.atan, 'abs': abs, 'round': round, 'redondear': round, 'min': min, 'max': max, 'pow': pow,
          'floor': math.floor, 'ceil': math.ceil, 'factorial': math.factorial, 'radians': math.radians, 'degrees': math.degrees}
_CONST = {'pi': math.pi, 'e': math.e}


def _eval(n):
    if isinstance(n, ast.Expression):
        return _eval(n.body)
    if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
        return n.value
    if isinstance(n, ast.Name) and n.id in _CONST:
        return _CONST[n.id]
    if isinstance(n, ast.BinOp) and type(n.op) in _OPS:
        izq, der = _eval(n.left), _eval(n.right)
        if isinstance(n.op, ast.Pow) and abs(der) > 1000:
            raise ValueError('exponente demasiado grande')
        return _OPS[type(n.op)](izq, der)
    if isinstance(n, ast.UnaryOp) and type(n.op) in _OPS:
        return _OPS[type(n.op)](_eval(n.operand))
    if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in _FUNCS and not n.keywords:
        return _FUNCS[n.func.id](*[_eval(a) for a in n.args])
    raise ValueError(f'expresión no permitida: {ast.dump(n)[:60]}')


_FECHA = re.compile(r'\b(\d{4})-(\d{1,2})-(\d{1,2})\b')


def calcular(expresion: str) -> str:
    # Fechas ISO → número de día, así "2027-01-01 - 2026-10-30" da la diferencia en días
    fechas = _FECHA.findall(expresion)
    if fechas:
        try:
            e = _FECHA.sub(lambda m: str(datetime.date(*map(int, m.groups())).toordinal()), expresion)
            r = _eval(ast.parse(e.strip(), mode='eval'))
        except (ValueError, SyntaxError, TypeError) as ex:
            return f'Error: no pude calcular "{expresion}" ({ex}). Para fechas usá "AAAA-MM-DD - AAAA-MM-DD".'
        return f'{expresion} = {int(r) if float(r).is_integer() else r} días'
    e = expresion.strip().replace('^', '**').replace('×', '*').replace('÷', '/')
    e = re.sub(r'(\d),(\d)', r'\1.\2', e)                       # 3,5 → 3.5
    e = re.sub(r'(\d+(?:\.\d+)?)\s*%\s*(?:de|of)\s*', r'\1/100*', e)  # 15% de 2340 → 15/100*2340
    e = re.sub(r'(\d+(?:\.\d+)?)\s*%', r'(\1/100)', e)
    try:
        r = _eval(ast.parse(e, mode='eval'))
    except ZeroDivisionError:
        return 'Error: división por cero.'
    except (ValueError, SyntaxError, TypeError, OverflowError) as ex:
        return f'Error: no pude calcular "{expresion}" ({ex}). Usá números y + - * / ** ( ) sqrt() log() round().'
    if isinstance(r, float):
        r = round(r, 10)
        if r.is_integer() and abs(r) < 1e15:
            r = int(r)
    return f'{expresion} = {r}'


# ---------- fecha y hora ----------
def fecha_hora(zona: str = 'America/Argentina/Buenos_Aires') -> str:
    try:
        tz = ZoneInfo(zona)
    except Exception:  # noqa: BLE001 — zona inválida: usar Argentina
        zona, tz = 'America/Argentina/Buenos_Aires', ZoneInfo('America/Argentina/Buenos_Aires')
    d = datetime.datetime.now(tz)
    dias = ['lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado', 'domingo']
    meses = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre']
    return (f'Ahora ({zona}): {dias[d.weekday()]} {d.day} de {meses[d.month - 1]} de {d.year}, {d:%H:%M:%S} '
            f'| ISO: {d.isoformat(timespec="seconds")} | semana ISO {d.isocalendar().week}')


# ---------- conversor de unidades ----------
_ALIAS = {
    'metro': 'm', 'kilometro': 'km', 'centimetro': 'cm', 'milimetro': 'mm', 'milla': 'mi', 'mile': 'mi', 'yarda': 'yd',
    'foot': 'ft', 'feet': 'ft', 'pie': 'ft', 'inch': 'in', 'inches': 'in', 'pulgada': 'in',
    'kilo': 'kg', 'kilogramo': 'kg', 'gramo': 'g', 'miligramo': 'mg', 'pound': 'lb', 'lbs': 'lb', 'libra': 'lb',
    'ounce': 'oz', 'onza': 'oz', 'tonelada': 't',
    'litro': 'l', 'liter': 'l', 'litre': 'l', 'mililitro': 'ml', 'gallon': 'gal', 'galon': 'gal', 'galone': 'gal',
    'hectarea': 'ha', 'segundo': 's', 'seg': 's', 'minuto': 'min', 'hora': 'h', 'day': 'dia', 'semana': 'semana', 'week': 'semana',
    'month': 'mes', 'mese': 'mes', 'year': 'año', 'ano': 'año', 'anio': 'año',
    'celsius': 'c', 'centigrado': 'c', '°c': 'c', 'fahrenheit': 'f', '°f': 'f', 'kelvin': 'k',
    'kilometros por hora': 'km/h', 'kph': 'km/h', 'millas por hora': 'mph', 'nudo': 'kn',
    'kilovatio hora': 'kwh', 'kilocaloria': 'kcal', 'caloria': 'cal', 'julio': 'j', 'joule': 'j', 'byte': 'b',
}
_TABLAS = {
    'longitud': {'m': 1, 'km': 1000, 'cm': 0.01, 'mm': 0.001, 'um': 1e-6, 'nm': 1e-9, 'mi': 1609.344, 'yd': 0.9144,
                 'ft': 0.3048, 'in': 0.0254, 'nmi': 1852},
    'masa': {'kg': 1, 'g': 0.001, 'mg': 1e-6, 't': 1000, 'lb': 0.45359237, 'oz': 0.028349523125},
    'volumen': {'l': 1, 'ml': 0.001, 'cl': 0.01, 'm3': 1000, 'cm3': 0.001, 'gal': 3.785411784, 'fl oz': 0.0295735295625, 'taza': 0.2365882365},
    'área': {'m2': 1, 'km2': 1e6, 'cm2': 1e-4, 'ha': 1e4, 'acre': 4046.8564224, 'ft2': 0.09290304, 'in2': 0.00064516},
    'tiempo': {'s': 1, 'ms': 0.001, 'min': 60, 'h': 3600, 'dia': 86400, 'semana': 604800, 'mes': 2629746, 'año': 31556952},
    'datos': {'b': 1, 'kb': 1e3, 'mb': 1e6, 'gb': 1e9, 'tb': 1e12, 'pb': 1e15, 'kib': 1024, 'mib': 1024 ** 2,
              'gib': 1024 ** 3, 'tib': 1024 ** 4, 'bit': 0.125},
    'velocidad': {'m/s': 1, 'km/h': 1 / 3.6, 'mph': 0.44704, 'kn': 0.514444, 'ft/s': 0.3048},
    'energía': {'j': 1, 'kj': 1000, 'cal': 4.184, 'kcal': 4184, 'wh': 3600, 'kwh': 3.6e6, 'btu': 1055.05585},
    'presión': {'pa': 1, 'kpa': 1000, 'bar': 1e5, 'atm': 101325, 'psi': 6894.757293168, 'mmhg': 133.322387415},
}


def _norm(u: str) -> str:
    s = unicodedata.normalize('NFD', str(u or '').strip().lower())
    s = ''.join(c for c in s if unicodedata.category(c) != 'Mn' or c == '̃')  # quita tildes (deja la ñ)
    s = unicodedata.normalize('NFC', s).replace('²', '2').replace('³', '3')
    s = re.sub(r'\s*/\s*', '/', s)
    if s in _ALIAS:
        return _ALIAS[s]
    for cand in (re.sub(r'(es|s)$', '', s), re.sub(r's$', '', s)):   # plurales: libras → libra, metros → metro
        if cand in _ALIAS:
            return _ALIAS[cand]
    if any(s in t for t in _TABLAS.values()) or s in ('c', 'f', 'k'):
        return s
    return re.sub(r's$', '', s) if len(s) > 3 else s


def convertir_unidades(valor: float, de: str, a: str) -> str:
    u1, u2 = _norm(de), _norm(a)
    if u1 in ('c', 'f', 'k') and u2 in ('c', 'f', 'k'):
        c = {'c': lambda v: v, 'f': lambda v: (v - 32) * 5 / 9, 'k': lambda v: v - 273.15}[u1](valor)
        r = {'c': lambda v: v, 'f': lambda v: v * 9 / 5 + 32, 'k': lambda v: v + 273.15}[u2](c)
        return f'{valor} {de} = {round(r, 6):g} {a} (temperatura)'
    for mag, t in _TABLAS.items():
        if u1 in t and u2 in t:
            return f'{valor} {de} = {float(f"{valor * t[u1] / t[u2]:.10g}"):g} {a} ({mag})'
    sop = ' | '.join(f'{m}: {", ".join(t)}' for m, t in _TABLAS.items())
    return f'Error: no sé convertir de "{de}" a "{a}". Unidades: {sop} | temperatura: C, F, K'


# ---------- tablas ----------
def tabla(datos_json: str, formato: str = 'markdown') -> str:
    try:
        datos = json.loads(datos_json) if isinstance(datos_json, str) else datos_json
    except json.JSONDecodeError as e:
        return f'Error: datos_json no es JSON válido ({e}).'
    if isinstance(datos, dict):
        datos = [datos]
    if not isinstance(datos, list) or not datos or not all(isinstance(x, dict) for x in datos):
        return 'Error: datos_json tiene que ser un array de objetos, por ejemplo [{"producto":"A","precio":10}].'
    cols = list(dict.fromkeys(k for fila in datos for k in fila))
    if formato.strip().lower() == 'csv':
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=cols)
        w.writeheader()
        w.writerows(datos)
        return buf.getvalue().strip()
    esc = lambda v: str('' if v is None else v).replace('|', '\\|').replace('\n', ' ')
    lineas = ['| ' + ' | '.join(cols) + ' |', '|' + '|'.join('---' for _ in cols) + '|']
    lineas += ['| ' + ' | '.join(esc(f.get(c)) for c in cols) + ' |' for f in datos]
    return '\n'.join(lineas)
