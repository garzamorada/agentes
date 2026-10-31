"""Segundo motor del navegador: Selenium + Chromium (chromedriver del sistema).

Mismas acciones y protecciones que el motor Playwright (navegador.py):
- Solo sitios públicos: se bloquean la red interna, localhost, IPs privadas y los contenedores (también en
  redirecciones y recursos de la página, vía Chrome DevTools: Network.setBlockedURLs).
- No escribe contraseñas ni datos de pago, no descarga archivos y avisa si hay CAPTCHA.
Selenium es sincrónico: cada acción corre en un hilo aparte.
"""
import asyncio
import datetime
import os
import threading
import time
import uuid
import urllib.parse

from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException, TimeoutException, WebDriverException
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import Select

import extraccion
from navegador import (DATA, IFRAMES_CAPTCHA, JS_ELEMENTOS, JS_INFO_CAMPO, JS_TEXTO, MAX_ELEMENTOS, MSG_SENSIBLE, PUBLIC, SI,
                       UA, ACCION_DESCONOCIDA, Pedido, _host_privado, elegir_opcion, es_sensible, formatear, leer_campos)

CHROMIUM = os.environ.get('CHROMIUM_BIN', '/usr/bin/chromium')
CHROMEDRIVER = os.environ.get('CHROMEDRIVER_BIN', '/usr/bin/chromedriver')
MAX_SESIONES = int(os.environ.get('MAX_SESIONES_SELENIUM', '3'))
INACTIVIDAD = int(os.environ.get('INACTIVIDAD_S', '600'))

# Patrones que Chrome no carga (Network.setBlockedURLs): red interna, contenedores y archivos locales
BLOQUEADAS = ['*://localhost*', '*://127.*', '*://0.*', '*://10.*', '*://192.168.*', '*://169.254.*', '*://[*',
              *[f'*://172.{i}.*' for i in range(16, 32)],
              '*://host.docker.internal*', '*://*.internal*', '*://*.local/*', '*://*.local:*', '*://*.localhost*',
              *[f'*://{h}{s}*' for h in ('n8n', 'n8n-container', 'n8n-runners', 'doc-service', 'mcp-tools', 'orquestador-web')
                for s in (':', '/')], 'file://*', 'ftp://*', 'chrome://*']

# Pasar texto entre comillas a XPath (admite comillas simples y dobles)
def _xq(t: str) -> str:
    if '"' not in t:
        return f'"{t}"'
    if "'" not in t:
        return f"'{t}'"
    return 'concat(' + ', \'"\', '.join(f'"{p}"' for p in t.split('"')) + ')'


class SesionSel:
    def __init__(self, sid, driver):
        self.sid, self.driver = sid, driver
        self.usado = time.time()
        self.lock = threading.Lock()
        self.carpeta = None
        self.capturas = 0


sesiones: dict[str, SesionSel] = {}
_lock = threading.Lock()


def _nuevo_driver():
    o = webdriver.ChromeOptions()
    o.binary_location = CHROMIUM
    for a in ('--headless=new', '--no-sandbox', '--disable-dev-shm-usage', '--window-size=1280,800', '--lang=es-AR',
              f'--user-agent={UA}', '--disable-extensions', '--disable-gpu'):
        o.add_argument(a)
    o.add_experimental_option('prefs', {'download_restrictions': 3, 'intl.accept_languages': 'es-AR,es'})
    d = webdriver.Chrome(service=Service(CHROMEDRIVER), options=o)
    d.set_page_load_timeout(30)
    d.set_script_timeout(15)
    d.execute_cdp_cmd('Network.enable', {})
    d.execute_cdp_cmd('Network.setBlockedURLs', {'urls': BLOQUEADAS})
    return d


def _cerrar(sid):
    s = sesiones.pop(sid, None)
    if s:
        try:
            s.driver.quit()
        except WebDriverException:
            pass


def _obtener(sid) -> SesionSel:
    with _lock:
        ahora = time.time()
        for k, s in list(sesiones.items()):
            if ahora - s.usado > INACTIVIDAD and not s.lock.locked():
                _cerrar(k)
        if sid not in sesiones:
            if len(sesiones) >= MAX_SESIONES:
                libre = min((s for s in sesiones.values() if not s.lock.locked()), key=lambda s: s.usado, default=None)
                if libre:
                    _cerrar(libre.sid)
            sesiones[sid] = SesionSel(sid, _nuevo_driver())
        s = sesiones[sid]
        s.usado = ahora
        return s


# ---------- página ----------
def _esperar(d, extra=0.6):
    fin = time.time() + 12
    while time.time() < fin:
        try:
            if d.execute_script('return document.readyState') == 'complete':
                break
        except WebDriverException:
            pass
        time.sleep(0.3)
    time.sleep(extra)


def _describir(d, max_chars=4000, con_texto=True):
    texto = d.execute_script(f'return ({JS_TEXTO})();') if con_texto else ''
    elementos = d.execute_script(f'return ({JS_ELEMENTOS})(arguments[0]);', MAX_ELEMENTOS * 2) or []
    iframe = bool(d.find_elements(By.CSS_SELECTOR, IFRAMES_CAPTCHA))
    return formatear(d.title, d.current_url, texto or '', elementos, iframe, max_chars, con_texto, motor='selenium')


def _info(d, el) -> dict:
    return d.execute_script(f'return ({JS_INFO_CAMPO})(arguments[0]);', el)


def _buscar(d, by, valor):
    try:
        els = [e for e in d.find_elements(by, valor) if e.is_displayed()] or d.find_elements(by, valor)
        return els[0] if els else None
    except (WebDriverException, NoSuchElementException):
        return None


def _campo(d, clave: str):
    """Campo de formulario por número [N], etiqueta, name, id, placeholder o aria-label."""
    k = str(clave).strip()
    num = k.strip('[]# ')
    if num.isdigit():
        return _buscar(d, By.CSS_SELECTOR, f'[data-wt="{num}"]')
    q = _xq(k)
    for by, v in ((By.XPATH, f'//label[normalize-space(.)={q}]'), (By.XPATH, f'//label[contains(normalize-space(.), {q})]')):
        lab = _buscar(d, by, v)
        if lab:
            if lab.get_attribute('for'):
                el = _buscar(d, By.ID, lab.get_attribute('for'))
                if el:
                    return el
            dentro = lab.find_elements(By.CSS_SELECTOR, 'input, select, textarea')
            if dentro:
                return dentro[0]
    for by, v in ((By.NAME, k), (By.ID, k), (By.XPATH, f'//*[@placeholder={q}]'), (By.XPATH, f'//*[@aria-label={q}]')):
        el = _buscar(d, by, v)
        if el:
            return el
    return None


def _ubicar(d, objetivo: str):
    """Cualquier elemento (botón, link, campo) por número, selector CSS, campo o texto visible."""
    o = (objetivo or '').strip()
    if not o:
        return None
    el = _campo(d, o)
    if el:
        return el
    if o[0] in '#.[' or any(c in o for c in ('>', '[', '=')):
        el = _buscar(d, By.CSS_SELECTOR, o)
        if el:
            return el
    q = _xq(o)
    return (_buscar(d, By.XPATH, f'//button[contains(normalize-space(.), {q})] | //a[contains(normalize-space(.), {q})] | '
                                 f'//input[(@type="submit" or @type="button") and contains(@value, {q})] | '
                                 f'//*[@role="button" and contains(normalize-space(.), {q})]')
            or _buscar(d, By.XPATH, f'//*[contains(normalize-space(text()), {q})]'))


def _abrir(d, url: str):
    p = urllib.parse.urlparse(url)
    if p.scheme not in ('http', 'https'):
        return 'solo se pueden abrir direcciones http o https'
    if _host_privado(p.hostname or ''):
        return 'por seguridad no se navegan direcciones locales ni de la red interna'
    try:
        d.get(url)
    except TimeoutException:
        pass  # la página tardó: se trabaja con lo que cargó
    _esperar(d)
    # Redirección a la red interna: se corta
    if _host_privado(urllib.parse.urlparse(d.current_url).hostname or ''):
        d.get('about:blank')
        return 'la página redirigió a una dirección interna y se bloqueó'
    return None


def _captura(s: SesionSel, completa: bool):
    d = s.driver
    if not s.carpeta:
        s.carpeta = DATA / f'web-{datetime.datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}'
        s.carpeta.mkdir(parents=True, exist_ok=True)
    s.capturas += 1
    nombre = f'captura_{s.capturas}.png'
    tam = d.get_window_size()
    if completa:
        alto = min(int(d.execute_script('return document.documentElement.scrollHeight') or 800), 8000)
        d.set_window_size(1280, alto)
        time.sleep(0.4)
    d.save_screenshot(str(s.carpeta / nombre))
    if completa:
        d.set_window_size(tam['width'], tam['height'])
    url = f'{PUBLIC}/files/{s.carpeta.name}/{nombre}'
    titulo = d.title or d.current_url
    return {'captura_url': url,
            'resultado': f'Captura guardada de "{titulo}" ({d.current_url}) con Selenium.\nURL de la imagen: {url}\n'
                         f'Para mostrarla escribí en Markdown: ![{titulo[:60]}]({url})'}


def _completar(d, campos: dict, enviar: bool) -> list[str]:
    hechos, ultimo = [], None
    for k, v in campos.items():
        el = _campo(d, k)
        if not el:
            hechos.append(f'✗ {k}: no encontré el campo')
            continue
        if es_sensible(_info(d, el)):
            hechos.append(f'✗ {k}: {MSG_SENSIBLE}')
            continue
        tipo = (el.get_attribute('type') or '').lower()
        try:
            if el.tag_name.lower() == 'select':
                sel = Select(el)
                opciones = [[o.get_attribute('value') or '', o.text.strip()] for o in sel.options]
                elegida = elegir_opcion(opciones, v)
                if not elegida:
                    hechos.append(f'✗ {k}: no hay opción "{v}" (opciones: {", ".join(o[1] for o in opciones[:15])})')
                    continue
                sel.select_by_value(elegida[0])
                v = elegida[1]
            elif tipo in ('checkbox', 'radio'):
                if (str(v).strip().lower() in SI) != el.is_selected():
                    d.execute_script('arguments[0].click();', el)
            else:
                el.clear()
                el.send_keys(str(v))
                ultimo = el
            hechos.append(f'✓ {k} = {v}')
        except WebDriverException as e:
            hechos.append(f'✗ {k}: {str(e).splitlines()[0][:120]}')
    if enviar:
        boton = None
        if ultimo:
            botones = ultimo.find_elements(By.XPATH, './ancestor::form//*[@type="submit" or self::button[not(@type)]]')
            boton = botones[0] if botones else None
        if boton:
            d.execute_script('arguments[0].click();', boton)
            hechos.append('→ formulario enviado (botón)')
        elif ultimo:
            ultimo.send_keys(Keys.ENTER)
            hechos.append('→ formulario enviado (Enter)')
        else:
            hechos.append('→ no se envió: no hay ningún campo de texto completado')
    return hechos


TECLAS = {'enter': Keys.ENTER, 'tab': Keys.TAB, 'escape': Keys.ESCAPE, 'esc': Keys.ESCAPE, 'pagedown': Keys.PAGE_DOWN,
          'pageup': Keys.PAGE_UP, 'arrowdown': Keys.ARROW_DOWN, 'arrowup': Keys.ARROW_UP, 'end': Keys.END, 'home': Keys.HOME}


def _ejecutar(p: Pedido) -> dict:
    acc = p.accion.strip().lower()
    if acc == 'cerrar':
        with _lock:
            _cerrar(p.sesion)
        return {'ok': True, 'resultado': 'Sesión de Selenium cerrada.'}
    s = _obtener(p.sesion)
    with s.lock:
        d = s.driver
        if p.url and acc in ('abrir', 'captura', 'leer', 'extraer', 'completar'):
            url = p.url.strip() if '://' in p.url else 'https://' + p.url.strip()
            if acc != 'leer' or d.current_url != url:
                motivo = _abrir(d, url)
                if motivo:
                    return {'ok': False, 'resultado': f'No se abrió {url}: {motivo}.'}
        elif acc == 'abrir':
            return {'ok': False, 'resultado': 'Falta "url" para abrir.'}
        if d.current_url in ('about:blank', 'data:,', '') and acc != 'abrir':
            return {'ok': False, 'resultado': 'No hay ninguna página abierta en esta sesión de Selenium: primero usá accion=abrir con una url.'}

        if acc == 'abrir':
            return {'ok': True, **_describir(d, p.max_chars)}
        if acc == 'leer':
            return {'ok': True, **_describir(d, max(p.max_chars, 12000))}
        if acc == 'extraer':
            return extraccion.extraer(d.page_source, d.current_url, p.objetivo or p.texto or 'tablas', max(p.max_chars, 8000))
        if acc == 'captura':
            return {'ok': True, **_captura(s, p.objetivo.strip().lower() in ('completa', 'pagina completa', 'full'))}
        if acc == 'atras':
            d.back()
            _esperar(d)
            return {'ok': True, **_describir(d, p.max_chars)}
        if acc == 'desplazar':
            d.execute_script('window.scrollBy(0, arguments[0]);', -700 if p.objetivo.strip().lower() in ('arriba', 'up') else 700)
            time.sleep(0.6)
            return {'ok': True, **_describir(d, p.max_chars, con_texto=False)}
        if acc == 'tecla':
            tecla = TECLAS.get(p.texto.strip().lower().replace(' ', ''), Keys.ENTER)
            webdriver.ActionChains(d).send_keys(tecla).perform()
            _esperar(d)
            return {'ok': True, **_describir(d, p.max_chars)}
        if acc == 'completar':
            campos = leer_campos(p.campos)
            if isinstance(campos, str):
                return {'ok': False, 'resultado': campos}
            hechos = _completar(d, campos, p.enviar)
            _esperar(d, 1.0)
            r = _describir(d, p.max_chars)
            return {**r, 'ok': not any(h.startswith('✗') for h in hechos),
                    'resultado': 'Formulario:\n' + '\n'.join(hechos) + '\n\n' + r['resultado']}
        if acc in ('clic', 'click', 'escribir'):
            el = _ubicar(d, p.objetivo)
            if not el:
                return {'ok': False, 'resultado': f'No encontré el elemento "{p.objetivo}". Usá el número [N] de la lista de elementos '
                                                  f'(accion=abrir o leer la vuelve a mostrar).'}
            if acc == 'escribir':
                if es_sensible(_info(d, el)):
                    return {'ok': False, 'resultado': MSG_SENSIBLE}
                el.clear()
                el.send_keys(p.texto)
                if p.enviar:
                    el.send_keys(Keys.ENTER)
            else:
                try:
                    el.click()
                except WebDriverException:
                    d.execute_script('arguments[0].click();', el)  # tapado por otro elemento: clic por JavaScript
            _esperar(d)
            return {'ok': True, **_describir(d, p.max_chars)}
    return {'ok': False, 'resultado': ACCION_DESCONOCIDA.format(p.accion)}


async def accion(p: Pedido) -> dict:
    try:
        return await asyncio.wait_for(asyncio.to_thread(_ejecutar, p), timeout=90)
    except asyncio.TimeoutError:
        return {'ok': False, 'resultado': 'La acción con Selenium tardó demasiado (más de 90 s). Probá con otra página o acción.'}
    except WebDriverException as e:
        return {'ok': False, 'resultado': f'Error de Selenium: {str(e).splitlines()[0][:300]}'}
