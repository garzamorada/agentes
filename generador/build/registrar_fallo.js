// Marca el modelo que falló y devuelve el pedido a "Elegir modelo"
// para que pruebe el siguiente de la lista.
const prev = $('Elegir modelo').item.json;

// Aviso de progreso a la web (solo si el pedido viene de un chat de la web local)
const corto = m => String(m || '').replace(/^(ollama|nvidia)\//, '').replace(/^[\w-]+\/(?=[^/]+$)/, '');
const avisar = (tipo, texto, extra = {}) => prev.session_id
  ? this.helpers.httpRequest({ method: 'POST', url: $env.WEB_EVENTOS_URL, json: true, timeout: 2000,
      headers: { 'X-API-Key': $env.WEB_EVENTOS_TOKEN },
      body: { chat: prev.session_id, tipo, texto, agente: prev.agent, modelo: prev.model, ...extra } }).catch(() => null)
  : null;
const e = $json.error;
const err = e ? String(e.message || e.description || e).slice(0, 500) : 'respuesta vacía del modelo';

const st = $getWorkflowStaticData('global');
st.models = st.models || {};
const s = st.models[prev.model] = st.models[prev.model] || {};

let tipo = 'otro', cooldown = 0;
if (/429|rate.?limit|too many requests|quota|exceeded|credits/i.test(err)) {
  tipo = 'limite';
  s.strikes = (s.strikes || 0) + 1;
  cooldown = Math.min(60000 * 2 ** (s.strikes - 1), 15 * 60000);   // 1, 2, 4, 8, 15 min
} else if (/404|410|not found|does not exist|deprecated|no longer/i.test(err)) {
  tipo = 'no_disponible';
  cooldown = 24 * 3600000;
} else if (/5\d\d|timeout|timed out|ECONN|socket|overloaded|unavailable|bad gateway/i.test(err)) {
  tipo = 'caido';
  cooldown = 2 * 60000;
}
if (cooldown) s.cooldownUntil = Date.now() + cooldown;
s.lastError = { at: new Date().toISOString(), tipo, error: err.slice(0, 200) };
const motivo = { limite: 'límite de uso', no_disponible: 'no disponible', caido: 'caído o lento', otro: err.slice(0, 60) }[tipo];
await avisar('fallo', `${corto(prev.model)} falló (${motivo}); probando otro modelo`);

const { model, action, ...rest } = prev;
const r = prev._router;
return {
  json: {
    ...rest,
    _router: {
      ...r,
      tried: [...r.tried, model],
      errors: [...r.errors, { model, tipo, error: err.slice(0, 200) }],
    },
  },
};
