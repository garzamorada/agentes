"""Estado compartido del router de modelos de n8n: usos por minuto/día, pausas (cooldown) y últimos errores.

n8n corre cada agente en paralelo como una ejecución aparte y guarda su "static data" al terminar: con varias
ejecuciones a la vez, la última pisa lo que registraron las demás (se pierden usos y pausas). Acá el estado vive
en un solo proceso y cada operación es atómica (funciones sin await dentro del event loop).

La configuración (orden de modelos, límites rpm/rpd) sigue en n8n (config_modelos.js) y llega en cada pedido.
"""
import datetime
import json
import os
import re
import time
from pathlib import Path

ARCHIVO = Path(os.environ.get('ROUTER_ESTADO', '/estado/router.json'))

try:
    estado = json.loads(ARCHIVO.read_text(encoding='utf-8'))
except (OSError, ValueError):
    estado = {}
estado.setdefault('global', [])
estado.setdefault('models', {})


def _guardar():
    try:
        ARCHIVO.parent.mkdir(parents=True, exist_ok=True)
        tmp = ARCHIVO.with_suffix('.tmp')
        tmp.write_text(json.dumps(estado), encoding='utf-8')
        tmp.replace(ARCHIVO)
    except OSError:
        pass  # sin disco el estado sigue en memoria


def _ahora():
    return int(time.time() * 1000)


def _hoy():
    return datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d')


def _modelo(m, ahora, hoy):
    s = estado['models'].setdefault(m, {})
    s['minute'] = [t for t in s.get('minute', []) if ahora - t < 60000]
    if (s.get('day') or {}).get('date') != hoy:
        s['day'] = {'date': hoy, 'count': 0}
    return s


def reservar(orden, intentados, limites, global_rpm):
    """Elige el primer modelo de `orden` con cupo y registra el uso en el mismo paso.
    → {'accion': 'llamar', 'modelo'} | {'accion': 'esperar', 'espera_ms', 'motivo'} | {'accion': 'ninguno', 'espera_ms'}"""
    ahora, hoy = _ahora(), _hoy()
    estado['global'] = [t for t in estado['global'] if ahora - t < 60000]
    elegido, proximo = None, None
    for m in orden:
        if m in intentados:
            continue
        s, lim = _modelo(m, ahora, hoy), limites.get(m) or {}
        if (s.get('cooldownUntil') or 0) > ahora:
            proximo = min(proximo or s['cooldownUntil'], s['cooldownUntil'])
            continue
        if lim.get('rpd') and s['day']['count'] >= lim['rpd']:
            continue                                                    # cupo diario agotado
        if lim.get('rpm') and len(s['minute']) >= lim['rpm']:
            libre = s['minute'][0] + 60000
            proximo = min(proximo or libre, libre)
            continue
        elegido = m
        break
    nvidia = elegido and not elegido.startswith('ollama/')
    # Límite global de la cuenta NVIDIA: esperar a que se libere la ventana de 1 minuto
    if nvidia and len(estado['global']) >= global_rpm:
        return {'accion': 'esperar', 'espera_ms': estado['global'][0] + 60000 - ahora, 'motivo': 'limite_global_rpm'}
    if not elegido:
        return {'accion': 'ninguno', 'espera_ms': proximo - ahora if proximo else None}
    s = estado['models'][elegido]
    s['minute'].append(ahora)
    s['day']['count'] += 1
    s['lastUsed'] = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')
    if nvidia:
        estado['global'].append(ahora)
    _guardar()
    return {'accion': 'llamar', 'modelo': elegido}


def fallo(modelo, error):
    """Clasifica el error y pone al modelo en pausa según el tipo. → {'tipo', 'cooldown_ms'}"""
    s = estado['models'].setdefault(modelo, {})
    err = str(error or 'respuesta vacía del modelo')[:500]
    tipo, pausa = 'otro', 0
    if re.search(r'429|rate.?limit|too many requests|quota|exceeded|credits', err, re.I):
        tipo = 'limite'
        s['strikes'] = s.get('strikes', 0) + 1
        pausa = min(60000 * 2 ** (s['strikes'] - 1), 15 * 60000)        # 1, 2, 4, 8, 15 min
    elif re.search(r'404|410|not found|does not exist|deprecated|no longer', err, re.I):
        tipo, pausa = 'no_disponible', 24 * 3600000
    elif re.search(r'5\d\d|timeout|timed out|terminated|aborted|ECONN|socket|overloaded|unavailable|bad gateway', err, re.I):
        # "terminated": la conexión se cortó después de minutos sin respuesta (modelo colgado)
        tipo, pausa = 'caido', 2 * 60000
    if pausa:
        s['cooldownUntil'] = _ahora() + pausa
    s['lastError'] = {'at': datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z'),
                      'tipo': tipo, 'error': err[:200]}
    _guardar()
    return {'tipo': tipo, 'cooldown_ms': pausa}


def exito(modelo):
    s = estado['models'].setdefault(modelo, {})
    if s.get('strikes'):
        s['strikes'] = 0
        _guardar()
    return {'ok': True}


def ver():
    ahora, hoy = _ahora(), _hoy()
    estado['global'] = [t for t in estado['global'] if ahora - t < 60000]
    for m in list(estado['models']):
        _modelo(m, ahora, hoy)
    return estado
