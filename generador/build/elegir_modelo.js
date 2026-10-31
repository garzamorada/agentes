// La configuración (CONFIG) está en config_modelos.js; gen.py la antepone a este código.
const isOllama = m => m.startsWith('ollama/');
// Estado compartido (usos, pausas) en mcp-tools: el "static data" de n8n se pisa entre ejecuciones en paralelo
const ROUTER = $env.MCP_URL.replace(/\/mcp\/?$/, '') + '/router';
const router = (ruta, body) => this.helpers.httpRequest({ method: 'POST', url: `${ROUTER}/${ruta}`, json: true, timeout: 5000,
  headers: { 'X-API-Key': $env.MCP_API_KEY }, body });

const j = { ...$input.item.json };
delete j.action; delete j.waitSeconds; delete j.model; delete j.modelName; delete j.provider;
const r = j._router || { tried: [], errors: [], waits: 0 };

// Aviso de progreso a la web (solo si el pedido viene de un chat de la web local)
const corto = m => String(m || '').replace(/^(ollama|nvidia)\//, '').replace(/^[\w-]+\/(?=[^/]+$)/, '');
const avisar = (tipo, texto, extra = {}) => j.session_id
  ? this.helpers.httpRequest({ method: 'POST', url: $env.WEB_EVENTOS_URL, json: true, timeout: 2000,
      headers: { 'X-API-Key': $env.WEB_EVENTOS_TOKEN },
      body: { chat: j.session_id, tipo, texto, agente: j.agent, ...extra } }).catch(() => null)
  : null;

const nvidia = [...(CONFIG.agents[j.agent] || []), ...CONFIG.fallbackGeneral];
const local = [...(CONFIG.ollama[j.agent] || CONFIG.ollama.default), ...CONFIG.ollama.default];
// Los especialistas llevan el catálogo de skills en el prompt (miles de tokens):
// van a NVIDIA aunque la tarea sea simple, así Ollama queda libre para el agente general.
const localPrimero = j.agent === 'general' && j.complejidad === 'simple';
// Subtareas paralelas (slot impar) arrancan por el segundo modelo local, así no hacen cola en el mismo
if (localPrimero && Number(j.slot) % 2 === 1) local.splice(0, 2, local[1], local[0]);
const order = [...new Set(localPrimero ? [...local, ...nvidia] : [...nvidia, ...local])];

// mcp-tools elige el primer modelo con cupo y registra el uso en el mismo paso (atómico entre agentes en paralelo)
let res = { accion: 'ninguno', espera_ms: null };
if (r.tried.length < CONFIG.maxIntentos) {
  try {
    res = await router('reservar', { orden: order, intentados: r.tried, limites: CONFIG.models, global_rpm: CONFIG.globalRpmNvidia });
  } catch (e) {
    // Sin mcp-tools no hay registro de cupos: se sigue con el primer modelo no probado
    const m = order.find(m => !r.tried.includes(m));
    res = m ? { accion: 'llamar', modelo: m } : res;
  }
}
const chosen = res.accion === 'llamar' ? res.modelo : null;

// Límite global de la cuenta NVIDIA: esperar a que se libere la ventana de 1 minuto
if (res.accion === 'esperar') {
  const waitSeconds = Math.ceil(res.espera_ms / 1000) + 1;
  await avisar('espera', `Esperando cupo de la cuenta NVIDIA (${waitSeconds} s)`);
  return { json: { ...j, _router: { ...r, waits: r.waits + 1 }, action: 'esperar', waitSeconds, motivo: res.motivo } };
}

if (!chosen) {
  const waitSeconds = Math.ceil((res.espera_ms ?? Infinity) / 1000) + 1;
  if (isFinite(waitSeconds) && waitSeconds <= CONFIG.maxEsperaSeg && r.waits < CONFIG.maxEsperas && r.tried.length < CONFIG.maxIntentos) {
    await avisar('espera', `Modelos ocupados o en pausa: esperando ${waitSeconds} s`);
    return { json: { ...j, _router: { ...r, waits: r.waits + 1 }, action: 'esperar', waitSeconds, motivo: 'modelos_en_cooldown' } };
  }
  await avisar('error', `Sin modelos disponibles para ${j.agent}`);
  return { json: { ...j, _router: r, action: 'agotado' } };
}

const que = j.agent === 'orquestador' ? 'Planificando el pedido' : j.agent === 'sintesis' ? 'Integrando las respuestas'
  : j.agent === 'verificador' ? 'Revisando que la respuesta cumpla todo lo pedido'
  : j.fase === 'correccion' ? `${j.agent}: completando lo que faltó` : `${j.agent}: trabajando`;
await avisar('modelo', `${que} con ${corto(chosen)}${r.tried.length ? ' (reintento)' : ''}`,
  { modelo: chosen, proveedor: isOllama(chosen) ? 'ollama' : 'nvidia' });

return {
  json: {
    ...j,
    model: chosen,
    provider: isOllama(chosen) ? 'ollama' : 'nvidia',
    modelName: isOllama(chosen) ? chosen.slice('ollama/'.length) : chosen,
    _router: r,
    action: 'llamar',
  },
};
