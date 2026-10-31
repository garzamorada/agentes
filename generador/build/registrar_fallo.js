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

// mcp-tools clasifica el error y pone al modelo en pausa (estado compartido entre agentes en paralelo)
const { tipo } = await this.helpers.httpRequest({ method: 'POST', url: $env.MCP_URL.replace(/\/mcp\/?$/, '') + '/router/fallo',
  json: true, timeout: 5000, headers: { 'X-API-Key': $env.MCP_API_KEY }, body: { modelo: prev.model, error: err } })
  .catch(() => ({ tipo: 'otro' }));
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
