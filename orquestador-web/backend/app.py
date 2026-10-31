"""Web local del orquestador multi-agente: registro de chats (SQLite) + proxy al webhook de n8n.

Los pedidos al orquestador pueden tardar minutos, así que corren en segundo plano:
el mensaje del asistente queda 'pendiente' y la web consulta hasta que pasa a 'ok' o 'error'.
"""
import asyncio
import json
import os
import re
import secrets
import sqlite3
import time
import uuid
from contextlib import asynccontextmanager, closing
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

N8N_WEBHOOK = os.environ.get('N8N_WEBHOOK', 'http://n8n-container:5678/webhook/orquestador')
N8N_ESTADO = os.environ.get('N8N_ESTADO', 'http://n8n-container:5678/webhook/estado-modelos')
OLLAMA_URL = os.environ.get('OLLAMA_URL', 'http://192.168.65.254:11434').rstrip('/')
# Seguridad (ver .env.default):
# - WEB_ACCESS_TOKEN: clave para usar la web y su API (header X-API-Key; la interfaz la pide una vez)
# - WEB_EVENTOS_TOKEN: con este token n8n y el MCP envían el progreso (POST /api/eventos)
# - N8N_WEBHOOK_TOKEN: lo manda este backend a los webhooks de n8n
WEB_ACCESS_TOKEN = os.environ.get('WEB_ACCESS_TOKEN', '')
WEB_EVENTOS_TOKEN = os.environ.get('WEB_EVENTOS_TOKEN', '')
N8N_HEADERS = {'X-API-Key': os.environ.get('N8N_WEBHOOK_TOKEN', '')}
if not WEB_ACCESS_TOKEN or not WEB_EVENTOS_TOKEN:
    raise SystemExit('Faltan WEB_ACCESS_TOKEN / WEB_EVENTOS_TOKEN (ver .env.default)')
TIMEOUT = float(os.environ.get('N8N_TIMEOUT', '1200'))
DB = Path(os.environ.get('DB_PATH', '/data/chats.db'))
STATIC = Path(__file__).parent / 'static'
# Versión del frontend = hash del bundle de Vite; la web la compara para avisar que hay que recargar
_idx = STATIC / 'index.html'
VERSION = (re.search(r'assets/index-([\w-]+)\.js', _idx.read_text(encoding='utf-8')) or [None, 'dev'])[1] if _idx.exists() else 'dev'
HISTORIAL_MAX = 8          # mensajes previos que se mandan como contexto
PIE_AGENTES = re.compile(r'\n+---\n_Agentes:.*$', re.S)


def db():
    con = sqlite3.connect(DB, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA foreign_keys = ON')
    return con


def ahora():
    return time.time()


def init_db():
    DB.parent.mkdir(parents=True, exist_ok=True)
    with closing(db()) as con, con:
        con.execute('PRAGMA journal_mode = WAL')
        con.executescript('''
        CREATE TABLE IF NOT EXISTS chats (
            id TEXT PRIMARY KEY,
            titulo TEXT NOT NULL,
            creado REAL NOT NULL,
            actualizado REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS mensajes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id TEXT NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
            rol TEXT NOT NULL,              -- usuario | asistente
            texto TEXT NOT NULL DEFAULT '',
            estado TEXT NOT NULL DEFAULT 'ok',  -- ok | pendiente | error
            html_url TEXT,
            agentes TEXT,
            adjunto TEXT,
            creado REAL NOT NULL,
            duracion REAL
        );
        CREATE INDEX IF NOT EXISTS ix_mensajes_chat ON mensajes(chat_id, id);
        -- Progreso de cada respuesta: lo envían n8n (router de modelos) y el servidor MCP (herramientas)
        CREATE TABLE IF NOT EXISTS eventos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            msg_id INTEGER NOT NULL REFERENCES mensajes(id) ON DELETE CASCADE,
            ts REAL NOT NULL,
            tipo TEXT NOT NULL,             -- inicio | modelo | plan | herramienta | resultado | razonamiento | fallo | espera | listo | error
            texto TEXT NOT NULL,
            agente TEXT, modelo TEXT, herramienta TEXT
        );
        CREATE INDEX IF NOT EXISTS ix_eventos_msg ON eventos(msg_id, id);
        ''')
        # Pedidos que quedaron a medias si el contenedor se reinició
        con.execute("UPDATE mensajes SET estado='error', texto='Se interrumpió (el servicio se reinició). Reintentá el pedido.' "
                    "WHERE estado='pendiente'")


@asynccontextmanager
async def lifespan(_):
    init_db()
    yield


app = FastAPI(title='Orquestador web', lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


@app.middleware('http')
async def requiere_clave(request: Request, call_next):
    """La API pide clave; la página (HTML/JS) y /api/health son libres para poder mostrar el ingreso."""
    ruta = request.url.path
    if ruta.startswith('/api/') and ruta != '/api/health':
        esperada = WEB_EVENTOS_TOKEN if ruta == '/api/eventos' else WEB_ACCESS_TOKEN
        if not secrets.compare_digest(request.headers.get('x-api-key', ''), esperada):
            return JSONResponse({'detail': 'No autorizado'}, status_code=401)
    return await call_next(request)
tareas: set[asyncio.Task] = set()


# ---------- modelos ----------
class Adjunto(BaseModel):
    base64: str
    nombre: str = 'archivo'
    mime: str = ''


class NuevoMensaje(BaseModel):
    texto: str
    adjunto: Adjunto | None = None


class NuevoChat(BaseModel):
    titulo: str | None = None


class CambioChat(BaseModel):
    titulo: str


class Evento(BaseModel):
    chat: str
    tipo: str = 'info'
    texto: str = ''
    agente: str | None = None
    modelo: str | None = None
    herramienta: str | None = None


def fila_mensaje(r):
    m = dict(r)
    m['agentes'] = json.loads(m['agentes']) if m['agentes'] else []
    return m


def leer_chat(con, chat_id):
    c = con.execute('SELECT * FROM chats WHERE id=?', (chat_id,)).fetchone()
    if not c:
        raise HTTPException(404, 'Chat inexistente')
    return dict(c)


# ---------- orquestador ----------
async def consultar_orquestador(msg_id: int, chat_id: str, texto: str, adjunto: Adjunto | None):
    with closing(db()) as con:
        previos = con.execute(
            "SELECT rol, texto FROM mensajes WHERE chat_id=? AND estado='ok' AND id < ? ORDER BY id DESC LIMIT ?",
            (chat_id, msg_id - 1, HISTORIAL_MAX)).fetchall()
    historial = [{'rol': r['rol'], 'texto': PIE_AGENTES.sub('', r['texto'])} for r in reversed(previos)]
    # session_id: clave de la memoria de los agentes en n8n (una por chat)
    cuerpo = {'mensaje': texto, 'historial': historial, 'session_id': chat_id}
    if adjunto:
        cuerpo['adjunto'] = adjunto.model_dump()

    t0 = ahora()
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as cli:
            r = await cli.post(N8N_WEBHOOK, json=cuerpo, headers=N8N_HEADERS)
        if r.status_code >= 400:
            raise RuntimeError(f'n8n respondió {r.status_code}: {r.text[:500]}')
        data = r.json()
        if isinstance(data, list):
            data = data[0] if data else {}
        respuesta = data.get('respuesta') or data.get('output')
        if not respuesta:
            raise RuntimeError(f'Respuesta vacía de n8n: {json.dumps(data, ensure_ascii=False)[:500]}')
        valores = ('ok', respuesta, data.get('html_url'), json.dumps(data.get('agentes') or [], ensure_ascii=False))
    except Exception as e:  # noqa: BLE001 — cualquier falla queda registrada en el mensaje
        msg = str(e) or e.__class__.__name__
        if isinstance(e, httpx.TimeoutException):
            msg = f'El orquestador no respondió en {int(TIMEOUT)} s.'
        elif isinstance(e, httpx.ConnectError):
            msg = f'No se pudo conectar con n8n ({N8N_WEBHOOK}). ¿Está publicado el workflow?'
        valores = ('error', msg, None, None)

    with closing(db()) as con, con:
        con.execute('UPDATE mensajes SET estado=?, texto=?, html_url=?, agentes=?, duracion=? WHERE id=?',
                    (*valores, round(ahora() - t0, 1), msg_id))
        con.execute('UPDATE chats SET actualizado=? WHERE id=?', (ahora(), chat_id))


def lanzar(msg_id, chat_id, texto, adjunto):
    with closing(db()) as con, con:
        con.execute('DELETE FROM eventos WHERE msg_id=?', (msg_id,))  # reintento: arranca de cero
        con.execute("INSERT INTO eventos (msg_id, ts, tipo, texto) VALUES (?,?,?,?)",
                    (msg_id, ahora(), 'inicio', 'Pedido enviado al orquestador' + (f' con el adjunto {adjunto.nombre}' if adjunto else '')))
    t = asyncio.create_task(consultar_orquestador(msg_id, chat_id, texto, adjunto))
    tareas.add(t)
    t.add_done_callback(tareas.discard)


# ---------- API ----------
@app.get('/api/health')
def health():
    return {'ok': True, 'version': VERSION}


@app.get('/api/chats')
def listar_chats(q: str = ''):
    sql = '''SELECT c.*,
               (SELECT texto FROM mensajes m WHERE m.chat_id=c.id ORDER BY id DESC LIMIT 1) AS ultimo,
               (SELECT COUNT(*) FROM mensajes m WHERE m.chat_id=c.id) AS cantidad,
               (SELECT COUNT(*) FROM mensajes m WHERE m.chat_id=c.id AND estado='pendiente') AS pendientes
             FROM chats c'''
    args = ()
    if q.strip():
        sql += ' WHERE c.titulo LIKE ? OR EXISTS (SELECT 1 FROM mensajes m WHERE m.chat_id=c.id AND m.texto LIKE ?)'
        args = (f'%{q.strip()}%',) * 2
    with closing(db()) as con:
        filas = con.execute(sql + ' ORDER BY c.actualizado DESC', args).fetchall()
    out = []
    for f in filas:
        d = dict(f)
        d['ultimo'] = PIE_AGENTES.sub('', d['ultimo'] or '')[:140]
        out.append(d)
    return out


@app.post('/api/chats')
def crear_chat(body: NuevoChat):
    cid = uuid.uuid4().hex[:12]
    t = ahora()
    with closing(db()) as con, con:
        con.execute('INSERT INTO chats VALUES (?,?,?,?)', (cid, (body.titulo or 'Nuevo chat').strip()[:120], t, t))
        return leer_chat(con, cid)


@app.get('/api/chats/{chat_id}')
def ver_chat(chat_id: str):
    with closing(db()) as con:
        chat = leer_chat(con, chat_id)
        chat['mensajes'] = [fila_mensaje(r) for r in
                            con.execute('SELECT * FROM mensajes WHERE chat_id=? ORDER BY id', (chat_id,))]
        eventos: dict[int, list] = {}
        for e in con.execute('SELECT e.* FROM eventos e JOIN mensajes m ON m.id = e.msg_id WHERE m.chat_id=? ORDER BY e.id',
                             (chat_id,)):
            eventos.setdefault(e['msg_id'], []).append({k: e[k] for k in ('ts', 'tipo', 'texto', 'agente', 'modelo', 'herramienta')})
        for m in chat['mensajes']:
            m['eventos'] = eventos.get(m['id'], [])
    return chat


@app.patch('/api/chats/{chat_id}')
def renombrar_chat(chat_id: str, body: CambioChat):
    with closing(db()) as con, con:
        leer_chat(con, chat_id)
        con.execute('UPDATE chats SET titulo=? WHERE id=?', (body.titulo.strip()[:120] or 'Sin título', chat_id))
        return leer_chat(con, chat_id)


@app.delete('/api/chats/{chat_id}')
def borrar_chat(chat_id: str):
    with closing(db()) as con, con:
        leer_chat(con, chat_id)
        con.execute('DELETE FROM chats WHERE id=?', (chat_id,))
    return {'ok': True}


@app.post('/api/chats/{chat_id}/mensajes')
async def enviar(chat_id: str, body: NuevoMensaje):
    texto = body.texto.strip()
    if not texto and not body.adjunto:
        raise HTTPException(400, 'Mensaje vacío')
    t = ahora()
    with closing(db()) as con, con:
        chat = leer_chat(con, chat_id)
        primero = not con.execute('SELECT 1 FROM mensajes WHERE chat_id=? LIMIT 1', (chat_id,)).fetchone()
        nombre = body.adjunto.nombre if body.adjunto else None
        con.execute('INSERT INTO mensajes (chat_id, rol, texto, adjunto, creado) VALUES (?,?,?,?,?)',
                    (chat_id, 'usuario', texto, nombre, t))
        cur = con.execute("INSERT INTO mensajes (chat_id, rol, estado, creado) VALUES (?,?,?,?)",
                          (chat_id, 'asistente', 'pendiente', t))
        msg_id = cur.lastrowid
        titulo = chat['titulo']
        if primero and titulo == 'Nuevo chat':
            base = texto or f'Archivo {nombre}'
            titulo = base if len(base) <= 70 else base[:67].rstrip() + '…'
        con.execute('UPDATE chats SET actualizado=?, titulo=? WHERE id=?', (t, titulo, chat_id))
    lanzar(msg_id, chat_id, texto or 'Analizá el archivo adjunto.', body.adjunto)
    return ver_chat(chat_id)


@app.post('/api/mensajes/{msg_id}/reintentar')
async def reintentar(msg_id: int):
    with closing(db()) as con, con:
        m = con.execute('SELECT * FROM mensajes WHERE id=?', (msg_id,)).fetchone()
        if not m or m['rol'] != 'asistente':
            raise HTTPException(404, 'Mensaje inexistente')
        if m['estado'] == 'pendiente':
            raise HTTPException(409, 'Ya está en curso')
        u = con.execute("SELECT texto FROM mensajes WHERE chat_id=? AND id<? AND rol='usuario' ORDER BY id DESC LIMIT 1",
                        (m['chat_id'], msg_id)).fetchone()
        if not u:
            raise HTTPException(400, 'No hay pedido para reintentar')
        con.execute("UPDATE mensajes SET estado='pendiente', texto='', html_url=NULL, agentes=NULL, duracion=NULL, "
                    "creado=? WHERE id=?", (ahora(), msg_id))
    # El adjunto no se guarda: un reintento solo reenvía el texto
    lanzar(msg_id, m['chat_id'], u['texto'] or 'Continuá.', None)
    return ver_chat(m['chat_id'])


@app.post('/api/eventos')
def recibir_evento(ev: Evento):
    """Progreso de una respuesta en curso. Se asocia a la respuesta pendiente más reciente del chat."""
    with closing(db()) as con, con:
        m = con.execute("SELECT id FROM mensajes WHERE chat_id=? AND rol='asistente' AND estado='pendiente' ORDER BY id DESC LIMIT 1",
                        (ev.chat,)).fetchone()
        if not m:
            return {'ok': False}
        con.execute('INSERT INTO eventos (msg_id, ts, tipo, texto, agente, modelo, herramienta) VALUES (?,?,?,?,?,?,?)',
                    (m['id'], ahora(), ev.tipo[:20], ev.texto[:800], ev.agente, ev.modelo, ev.herramienta))
    return {'ok': True}


@app.get('/api/modelos')
async def modelos():
    """Modelos remotos (NVIDIA, según el router de n8n) y locales (Ollama), con su estado y uso."""
    out = {'remotos': [], 'locales': [], 'nvidia_rpm_global': None, 'errores': []}
    async with httpx.AsyncClient(timeout=8) as cli:
        router, tags, ps = await asyncio.gather(cli.get(N8N_ESTADO, headers=N8N_HEADERS), cli.get(f'{OLLAMA_URL}/api/tags'),
                                                cli.get(f'{OLLAMA_URL}/api/ps'), return_exceptions=True)
    config = {}
    if isinstance(router, httpx.Response) and router.status_code == 200:
        d = router.json()
        d = d[0] if isinstance(d, list) else d
        out['nvidia_rpm_global'] = d.get('nvidia_rpm_global')
        config = {m['id']: m for m in d.get('modelos', [])}
        out['remotos'] = [m for m in config.values() if m['proveedor'] == 'nvidia']
    else:
        out['errores'].append('No se pudo leer el estado del router en n8n (¿está publicado el agente?).')
    cargados = {}
    if isinstance(ps, httpx.Response) and ps.status_code == 200:
        cargados = {m['name']: m for m in ps.json().get('models', [])}
    if isinstance(tags, httpx.Response) and tags.status_code == 200:
        for t in tags.json().get('models', []):
            r = config.get(f"ollama/{t['name']}", {})
            c = cargados.get(t['name'])
            out['locales'].append({
                'id': t['name'], 'tamano_gb': round(t.get('size', 0) / 1e9, 1),
                'parametros': (t.get('details') or {}).get('parameter_size'), 'cuantizacion': (t.get('details') or {}).get('quantization_level'),
                'cargado': bool(c), 'vram_gb': round(c.get('size_vram', 0) / 1e9, 1) if c else 0,
                'en_router': bool(r), 'estado': r.get('estado', 'sin usar' if not r else 'disponible'),
                'usos_hoy': r.get('usos_hoy', 0), 'agentes': r.get('agentes', []), 'ultimo_uso': r.get('ultimo_uso'),
                'ultimo_error': r.get('ultimo_error'), 'nube': t['name'].endswith(':cloud'),
            })
    else:
        out['errores'].append(f'No se pudo conectar con Ollama ({OLLAMA_URL}).')
    out['locales'].sort(key=lambda m: (not m['en_router'], not m['cargado'], m['id']))
    out['remotos'].sort(key=lambda m: (m['estado'] != 'disponible', -m['usos_hoy'], m['id']))
    return out


# ---------- frontend (build de React) ----------
if STATIC.exists():
    app.mount('/assets', StaticFiles(directory=STATIC / 'assets'), name='assets')

    @app.get('/{ruta:path}', include_in_schema=False)
    def spa(ruta: str):
        f = STATIC / ruta
        if ruta and f.is_file():
            return FileResponse(f)  # assets con hash en el nombre: se pueden cachear
        # index.html nunca en caché, así una versión nueva se ve al recargar
        return FileResponse(STATIC / 'index.html', headers={'Cache-Control': 'no-cache, no-store, must-revalidate'})
