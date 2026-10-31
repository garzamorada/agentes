"""Navegador web de las herramientas MCP (Playwright + Chromium).

Acciones: buscar, abrir, leer, clic, escribir, completar, extraer, tecla, desplazar, captura, atras, cerrar.

Cada agente usa una "sesión" (pestaña propia) que se mantiene entre llamadas: puede abrir una página,
hacer clic, escribir en un buscador y seguir navegando. Las capturas se guardan en la carpeta que sirve
doc-service (http://localhost:8090/files/...).

Límites de seguridad:
- Solo http/https y solo sitios públicos: se bloquea localhost, IPs privadas y los contenedores de la red
  (también en redirecciones y en cada recurso que carga la página).
- No escribe contraseñas ni datos de tarjeta/cuenta, no descarga archivos y no resuelve CAPTCHAs.
"""
import asyncio
import datetime
import ipaddress
import json
import os
import re
import socket
import time
import urllib.parse
import uuid
from pathlib import Path

import httpx
from bs4 import BeautifulSoup
from playwright.async_api import Error as PWError
from playwright.async_api import async_playwright
from pydantic import BaseModel

import extraccion

DATA = Path(os.environ.get('DATA_DIR', '/data'))
PUBLIC = os.environ.get('PUBLIC_URL', 'http://localhost:8090').rstrip('/')
MAX_SESIONES = int(os.environ.get('MAX_SESIONES', '6'))
INACTIVIDAD = int(os.environ.get('INACTIVIDAD_S', '600'))
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) '
      'Chrome/131.0.0.0 Safari/537.36')
MAX_ELEMENTOS = 40
CAPTCHA = re.compile(r'captcha|are you a robot|not a robot|verify you are human|unusual traffic|'
                     r'tráfico inusual|no soy un robot|verificá que sos humano', re.I)
SENSIBLE = re.compile(r'passw|contrase|clave|\bpin\b|card|tarjeta|cvv|cvc|cbu|cvu|iban|cuenta.?banc|token|otp', re.I)

# ---------- red: solo sitios públicos ----------
_cache_hosts: dict[str, tuple[bool, float]] = {}


def _host_privado(host: str) -> bool:
    h = (host or '').lower().strip('[]').rstrip('.')
    if not h or h == 'localhost' or h.endswith(('.localhost', '.local', '.internal', '.lan')) or '.' not in h and ':' not in h:
        return True  # nombres sin dominio = contenedores de la red Docker (n8n-container, doc-service...)
    hit = _cache_hosts.get(h)
    if hit and hit[1] > time.time():
        return hit[0]
    try:
        ips = {ai[4][0] for ai in socket.getaddrinfo(h, None)}
        privado = any(not ipaddress.ip_address(ip.split('%')[0]).is_global for ip in ips)
    except (socket.gaierror, ValueError):
        privado = False  # no resuelve: que falle el navegador con su propio error
    _cache_hosts[h] = (privado, time.time() + 300)
    return privado


async def host_privado(host: str) -> bool:
    return await asyncio.to_thread(_host_privado, host)


async def url_permitida(url: str) -> str | None:
    """Devuelve un motivo si la URL no se puede abrir."""
    p = urllib.parse.urlparse(url)
    if p.scheme not in ('http', 'https'):
        return 'solo se pueden abrir direcciones http o https'
    if await host_privado(p.hostname or ''):
        return 'por seguridad no se navegan direcciones locales ni de la red interna'
    return None


async def filtro_red(route):
    url = route.request.url
    if url.startswith(('data:', 'blob:', 'about:')):
        return await route.continue_()
    p = urllib.parse.urlparse(url)
    if p.scheme not in ('http', 'https') or await host_privado(p.hostname or ''):
        return await route.abort('blockedbyclient')
    await route.continue_()


# ---------- sesiones (una pestaña por agente) ----------
class Sesion:
    def __init__(self, sid, ctx, page):
        self.sid, self.ctx, self.page = sid, ctx, page
        self.usado = time.time()
        self.lock = asyncio.Lock()
        self.carpeta = None
        self.capturas = 0


estado_global = {'pw': None, 'browser': None}
sesiones: dict[str, Sesion] = {}


async def nueva_sesion(sid):
    ctx = await (await navegador()).new_context(
        user_agent=UA, locale='es-AR', timezone_id='America/Argentina/Buenos_Aires',
        viewport={'width': 1280, 'height': 800}, accept_downloads=False)
    await ctx.route('**/*', filtro_red)
    page = await ctx.new_page()
    page.set_default_timeout(15000)
    return Sesion(sid, ctx, page)


async def obtener_sesion(sid) -> Sesion:
    ahora = time.time()
    for k, s in list(sesiones.items()):
        if ahora - s.usado > INACTIVIDAD and not s.lock.locked():
            await cerrar_sesion(k)
    if sid not in sesiones:
        if len(sesiones) >= MAX_SESIONES:
            libre = min((s for s in sesiones.values() if not s.lock.locked()), key=lambda s: s.usado, default=None)
            if libre:
                await cerrar_sesion(libre.sid)
        sesiones[sid] = await nueva_sesion(sid)
    s = sesiones[sid]
    s.usado = ahora
    return s


async def cerrar_sesion(sid):
    s = sesiones.pop(sid, None)
    if s:
        try:
            await s.ctx.close()
        except PWError:
            pass


_lock_inicio = asyncio.Lock()


async def navegador():
    """Chromium se inicia la primera vez que se usa."""
    async with _lock_inicio:
        if not estado_global['browser']:
            estado_global['pw'] = await async_playwright().start()
            estado_global['browser'] = await estado_global['pw'].chromium.launch(
                args=['--no-sandbox', '--disable-dev-shm-usage'])
    return estado_global['browser']


class Pedido(BaseModel):
    accion: str
    sesion: str = 'default'
    url: str = ''
    consulta: str = ''
    objetivo: str = ''      # número de elemento [N], texto visible, etiqueta/placeholder o selector CSS
    texto: str = ''         # texto a escribir o tecla a presionar
    enviar: bool = False    # escribir/completar: enviar el formulario después
    campos: str = ''        # completar: JSON {"etiqueta o nombre del campo": "valor", ...}
    motor: str = 'playwright'  # playwright (por defecto) | selenium
    max_chars: int = 4000


# ---------- página → texto para el agente ----------
JS_ELEMENTOS = '''(max) => {
  const vis = e => { const r = e.getBoundingClientRect(); const s = getComputedStyle(e);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  document.querySelectorAll('[data-wt]').forEach(e => e.removeAttribute('data-wt'));
  const sel = 'a[href], button, input:not([type=hidden]), textarea, select, [role=button], [role=link], [role=searchbox], [contenteditable=true]';
  const els = [...document.querySelectorAll(sel)].filter(vis).slice(0, max);
  return els.map((e, i) => {
    e.setAttribute('data-wt', String(i + 1));
    const tag = e.tagName.toLowerCase();
    const tipo = tag === 'input' ? 'campo:' + (e.type || 'text') : tag === 'a' ? 'link' : tag === 'textarea' ? 'campo:texto' : tag;
    const txt = (e.innerText || e.value || e.placeholder || e.getAttribute('aria-label') || e.title || e.name || '')
      .trim().replace(/\\s+/g, ' ').slice(0, 70);
    return { n: i + 1, tipo, texto: txt, href: tag === 'a' ? e.href : '' };
  });
}'''
# Texto principal: oculta un momento menús, encabezados, pies y barras laterales para no leer "ruido"
JS_TEXTO = '''() => {
  const limpio = t => (t || '').replace(/[ \\t]+/g, ' ').replace(/\\n\\s*\\n+/g, '\\n\\n').trim();
  const ruido = document.querySelectorAll('nav, header, footer, aside, [role=navigation], [role=banner], [role=contentinfo], ' +
    '[role=complementary], [role=menu], [aria-hidden=true], .vector-header-container, .vector-page-toolbar, .vector-column-start, ' +
    '.vector-column-end, .mw-editsection, #cookie-banner, .cookie, [class*=cookie-banner]');
  const antes = [...ruido].map(e => [e, e.style.display]);
  antes.forEach(([e]) => e.style.setProperty('display', 'none', 'important'));
  try {
    const m = document.querySelector('#mw-content-text, article, main, [role=main]');
    const tm = m ? limpio(m.innerText) : '';
    return tm.length > 300 ? tm : limpio(document.body ? document.body.innerText : '');
  } finally {
    antes.forEach(([e, d]) => { e.style.display = d; });
  }
}'''


async def esperar_carga(page):
    try:
        await page.wait_for_load_state('domcontentloaded', timeout=15000)
        await page.wait_for_load_state('networkidle', timeout=4000)
    except PWError:
        pass


IFRAMES_CAPTCHA = 'iframe[src*="recaptcha"], iframe[src*="hcaptcha"], iframe[src*="turnstile"]'


async def describir(page, max_chars=4000, con_texto=True):
    titulo = await page.title()
    texto = await page.evaluate(JS_TEXTO) if con_texto else ''
    elementos = await page.evaluate(JS_ELEMENTOS, MAX_ELEMENTOS * 2)
    iframe = await page.locator(IFRAMES_CAPTCHA).count() > 0
    return formatear(titulo, page.url, texto, elementos, iframe, max_chars, con_texto)


def formatear(titulo, url, texto, elementos, iframe_captcha, max_chars=4000, con_texto=True, motor='playwright'):
    """Arma el texto que recibe el agente (igual para los dos motores)."""
    captcha = iframe_captcha or bool(CAPTCHA.search(titulo + ' ' + texto[:3000]))
    partes = [f'Página: {titulo}', f'URL: {url}'] + (['Motor: Selenium'] if motor == 'selenium' else [])
    if captcha:
        partes.append('AVISO: la página pide un CAPTCHA o verificación humana. No se puede resolver: '
                      'usá otra fuente (otro resultado de búsqueda).')
    if con_texto:
        total = len(texto)
        if total > max_chars:
            texto = texto[:max_chars] + f'\n[... recortado: se muestran {max_chars} de {total} caracteres; usá accion=leer para más]'
        partes.append(f'\nTexto de la página:\n{texto or "(sin texto visible)"}')
    lista = []
    for e in elementos[:MAX_ELEMENTOS]:
        destino = f' → {e["href"]}' if e['href'] and not e['href'].startswith('javascript') else ''
        lista.append(f'[{e["n"]}] {e["tipo"]} "{e["texto"]}"{destino}')
    if lista:
        extra = f' (hay {len(elementos)} o más; se listan {MAX_ELEMENTOS})' if len(elementos) > MAX_ELEMENTOS else ''
        partes.append(f'\nElementos para interactuar{extra} — usá el número en "objetivo" para clic o escribir:\n' + '\n'.join(lista))
    return {'titulo': titulo, 'url': url, 'captcha': captcha, 'resultado': '\n'.join(partes)}


async def ubicar(page, objetivo: str):
    o = (objetivo or '').strip()
    if not o:
        return None
    num = o.strip('[]# ')
    if num.isdigit():
        loc = page.locator(f'[data-wt="{num}"]')
        return loc.first if await loc.count() else None
    candidatos = []
    if re.match(r'^([#.\[]|[a-z]+[#.\[:])', o):
        candidatos.append(page.locator(o))
    candidatos += [page.get_by_label(o), page.get_by_placeholder(o), page.get_by_role('button', name=o),
                   page.get_by_role('link', name=o), page.get_by_text(o)]
    for loc in candidatos:
        try:
            if await loc.count():
                return loc.first
        except PWError:
            continue
    return None


def es_sensible(info: dict) -> bool:
    """info: {t: type, ac: autocomplete, n: nombre/id/placeholder/aria-label} del campo."""
    return info['t'] == 'password' or info['ac'].startswith('cc-') or 'password' in info['ac'] or bool(SENSIBLE.search(info['n'] or ''))


JS_INFO_CAMPO = ('e => ({t: (e.type || "").toLowerCase(), ac: (e.autocomplete || "").toLowerCase(), '
                 'n: [e.name, e.id, e.placeholder, e.getAttribute("aria-label")].join(" ")})')
MSG_SENSIBLE = 'Por seguridad no se escriben contraseñas, claves ni datos de tarjetas o cuentas. Pedile al usuario que lo haga él mismo.'
SI = {'si', 'sí', 'true', '1', 'x', 'yes', 'marcar', 'marcado', 'on'}


def leer_campos(campos: str) -> dict | str:
    try:
        d = json.loads(campos) if isinstance(campos, str) else campos
    except json.JSONDecodeError as e:
        return f'"campos" no es JSON válido ({e}). Ejemplo: {{"Desde": "Córdoba", "Fecha": "2026-11-15"}}'
    if not isinstance(d, dict) or not d:
        return 'Falta "campos": un JSON con {"etiqueta o nombre del campo": "valor"}. Usá accion=extraer objetivo=campos para verlos.'
    return d


def elegir_opcion(opciones: list, valor) -> list | None:
    """opciones: [[value, texto], ...]. Coincidencia exacta por valor o texto; si no, texto que contiene el valor."""
    v = str(valor).strip().lower()
    return next((o for o in opciones if v in (o[0].lower(), o[1].lower())), None) \
        or next((o for o in opciones if v and v in o[1].lower()), None)


async def campo_pw(page, clave: str):
    """Ubica un campo de formulario por número [N], etiqueta, name, id, placeholder o aria-label."""
    k = str(clave).strip()
    num = k.strip('[]# ')
    cands = [page.locator(f'[data-wt="{num}"]')] if num.isdigit() else []
    cands += [page.get_by_label(k, exact=True), page.get_by_label(k), page.locator(f'[name="{k}"]'),
              page.locator(f'[id="{k}"]'), page.get_by_placeholder(k), page.locator(f'[aria-label="{k}"]')]
    for loc in cands:
        try:
            if await loc.count():
                return loc.first
        except PWError:
            continue
    return None


async def completar_pw(page, campos: dict, enviar: bool) -> list[str]:
    hechos, ultimo = [], None
    for k, v in campos.items():
        loc = await campo_pw(page, k)
        if not loc:
            hechos.append(f'✗ {k}: no encontré el campo')
            continue
        if es_sensible(await loc.evaluate(JS_INFO_CAMPO)):
            hechos.append(f'✗ {k}: {MSG_SENSIBLE}')
            continue
        tag = await loc.evaluate('e => e.tagName.toLowerCase()')
        tipo = (await loc.get_attribute('type') or '').lower()
        try:
            if tag == 'select':
                opciones = await loc.evaluate('e => [...e.options].map(o => [o.value, o.text.trim()])')
                elegida = elegir_opcion(opciones, v)
                if not elegida:
                    hechos.append(f'✗ {k}: no hay opción "{v}" (opciones: {", ".join(o[1] for o in opciones[:15])})')
                    continue
                await loc.select_option(value=elegida[0])
                v = elegida[1]
            elif tipo in ('checkbox', 'radio'):
                await loc.set_checked(str(v).strip().lower() in SI)
            else:
                await loc.fill(str(v))
                ultimo = loc
            hechos.append(f'✓ {k} = {v}')
        except PWError as e:
            hechos.append(f'✗ {k}: {str(e).splitlines()[0][:120]}')
    if enviar:
        boton = ultimo.locator('xpath=ancestor::form//*[@type="submit" or self::button[not(@type)]]') if ultimo else None
        if boton is not None and await boton.count():
            await boton.first.click()
            hechos.append('→ formulario enviado (botón)')
        elif ultimo:
            await ultimo.press('Enter')
            hechos.append('→ formulario enviado (Enter)')
        else:
            hechos.append('→ no se envió: no hay ningún campo de texto completado')
    return hechos


# ---------- búsqueda web ----------
async def buscar_ddg(q):
    async with httpx.AsyncClient(timeout=15, headers={'User-Agent': UA}, follow_redirects=True) as c:
        r = await c.post('https://html.duckduckgo.com/html/', data={'q': q, 'kl': 'ar-es'})
    soup = BeautifulSoup(r.text, 'html.parser')
    out = []
    for res in soup.select('.result'):
        a = res.select_one('a.result__a')
        if not a:
            continue
        href = a.get('href', '')
        if 'uddg=' in href:
            href = urllib.parse.parse_qs(urllib.parse.urlparse(href).query).get('uddg', [href])[0]
        if 'duckduckgo.com/y.js' in href or not href.startswith('http'):
            continue  # publicidad
        sn = res.select_one('.result__snippet')
        out.append({'titulo': a.get_text(' ', strip=True), 'url': href, 'resumen': sn.get_text(' ', strip=True) if sn else ''})
    return out


async def buscar_bing(q):
    s = await nueva_sesion('_busqueda')
    try:
        await s.page.goto('https://www.bing.com/search?setlang=es&q=' + urllib.parse.quote(q), wait_until='domcontentloaded')
        return await s.page.evaluate('''() => [...document.querySelectorAll('li.b_algo')].map(li => {
            const a = li.querySelector('h2 a'); const p = li.querySelector('.b_caption p, p');
            return a ? { titulo: a.innerText.trim(), url: a.href, resumen: p ? p.innerText.trim() : '' } : null; }).filter(Boolean)''')
    finally:
        await s.ctx.close()


async def buscar(q):
    resultados, motor = [], 'DuckDuckGo'
    try:
        resultados = await buscar_ddg(q)
    except httpx.HTTPError:
        pass
    if not resultados:
        motor = 'Bing'
        resultados = await buscar_bing(q)
    resultados = resultados[:8]
    if not resultados:
        return {'ok': False, 'resultado': f'La búsqueda "{q}" no devolvió resultados. Probá con otras palabras.'}
    lineas = [f'{i}. {r["titulo"]}\n   {r["url"]}\n   {r["resumen"][:220]}' for i, r in enumerate(resultados, 1)]
    return {'ok': True, 'resultados': resultados,
            'resultado': f'Resultados de "{q}" ({motor}):\n' + '\n'.join(lineas) +
                         '\n\nPara leer uno: navegador con accion=abrir y su url. Citá las fuentes (url) en tu respuesta.'}


# ---------- acciones ----------
ACCION_DESCONOCIDA = ('Acción "{}" desconocida. Usá: buscar, abrir, leer, clic, escribir, completar, extraer, tecla, '
                      'desplazar, captura, atras o cerrar.')

async def accion_captura(s: Sesion, completa: bool):
    if not s.carpeta:
        s.carpeta = DATA / f'web-{datetime.datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}'
        s.carpeta.mkdir(parents=True, exist_ok=True)
    s.capturas += 1
    nombre = f'captura_{s.capturas}.png'
    await s.page.screenshot(path=s.carpeta / nombre, full_page=completa)
    url = f'{PUBLIC}/files/{s.carpeta.name}/{nombre}'
    titulo = (await s.page.title()) or s.page.url
    return {'captura_url': url,
            'resultado': f'Captura guardada de "{titulo}" ({s.page.url}).\nURL de la imagen: {url}\n'
                         f'Para mostrarla en tu respuesta o en un documento escribí en Markdown: ![{titulo[:60]}]({url})'}


async def ejecutar(p: Pedido):
    acc = p.accion.strip().lower()
    if acc == 'buscar':
        q = (p.consulta or p.texto or p.url).strip()
        if not q:
            return {'ok': False, 'resultado': 'Falta "consulta" con lo que hay que buscar.'}
        return await buscar(q)
    if acc == 'cerrar':
        await cerrar_sesion(p.sesion)
        return {'ok': True, 'resultado': 'Sesión del navegador cerrada.'}

    s = await obtener_sesion(p.sesion)
    async with s.lock:
        page = s.page
        if p.url and acc in ('abrir', 'captura', 'leer', 'extraer', 'completar'):
            url = p.url.strip()
            if not re.match(r'^[a-z]+://', url, re.I):
                url = 'https://' + url
            motivo = await url_permitida(url)
            if motivo:
                return {'ok': False, 'resultado': f'No se abrió {url}: {motivo}.'}
            if acc != 'leer' or page.url != url:
                try:
                    await page.goto(url, wait_until='domcontentloaded', timeout=30000)
                except PWError as e:
                    return {'ok': False, 'resultado': f'No se pudo abrir {url}: {str(e).splitlines()[0][:200]}'}
                await esperar_carga(page)
        elif acc in ('abrir',) and not p.url:
            return {'ok': False, 'resultado': 'Falta "url" para abrir.'}

        if page.url in ('about:blank', '') and acc not in ('abrir',):
            return {'ok': False, 'resultado': 'No hay ninguna página abierta en esta sesión: primero usá accion=abrir con una url.'}

        if acc == 'abrir':
            return {'ok': True, **await describir(page, p.max_chars)}
        if acc == 'leer':
            return {'ok': True, **await describir(page, max(p.max_chars, 12000))}
        if acc == 'captura':
            return {'ok': True, **await accion_captura(s, p.objetivo.strip().lower() in ('completa', 'pagina completa', 'full'))}
        if acc == 'extraer':
            return extraccion.extraer(await page.content(), page.url, p.objetivo or p.texto or 'tablas', max(p.max_chars, 8000))
        if acc == 'completar':
            campos = leer_campos(p.campos)
            if isinstance(campos, str):
                return {'ok': False, 'resultado': campos}
            hechos = await completar_pw(page, campos, p.enviar)
            await esperar_carga(page)
            d = await describir(page, p.max_chars)
            return {**d, 'ok': not any(h.startswith('✗') for h in hechos),
                    'resultado': 'Formulario:\n' + '\n'.join(hechos) + '\n\n' + d['resultado']}
        if acc == 'atras':
            await page.go_back()
            await esperar_carga(page)
            return {'ok': True, **await describir(page, p.max_chars)}
        if acc == 'desplazar':
            await page.mouse.wheel(0, -700 if p.objetivo.strip().lower() in ('arriba', 'up') else 700)
            await page.wait_for_timeout(600)
            return {'ok': True, **await describir(page, p.max_chars, con_texto=False)}
        if acc == 'tecla':
            await page.keyboard.press(p.texto.strip() or 'Enter')
            await esperar_carga(page)
            return {'ok': True, **await describir(page, p.max_chars)}

        if acc in ('clic', 'click', 'escribir'):
            loc = await ubicar(page, p.objetivo)
            if not loc:
                return {'ok': False, 'resultado': f'No encontré el elemento "{p.objetivo}". Usá el número [N] de la lista de elementos '
                                                  f'(accion=abrir o leer la vuelve a mostrar).'}
            if acc == 'escribir':
                if es_sensible(await loc.evaluate(JS_INFO_CAMPO)):
                    return {'ok': False, 'resultado': MSG_SENSIBLE}
                await loc.fill(p.texto)
                if p.enviar:
                    await loc.press('Enter')
            else:
                await loc.click()
            await esperar_carga(page)
            return {'ok': True, **await describir(page, p.max_chars)}

    return {'ok': False, 'resultado': ACCION_DESCONOCIDA.format(p.accion)}


async def accion(p: Pedido) -> dict:
    try:
        return await asyncio.wait_for(ejecutar(p), timeout=90)
    except TimeoutError:
        return {'ok': False, 'resultado': 'La acción tardó demasiado (más de 90 s). Probá con otra página o acción.'}
    except PWError as e:
        return {'ok': False, 'resultado': f'Error del navegador: {str(e).splitlines()[0][:300]}'}
