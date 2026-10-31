// La configuración (CONFIG) está en config_modelos.js; gen.py la antepone a este código.
const isOllama = m => m.startsWith('ollama/');
const now = Date.now();
const today = new Date().toISOString().slice(0, 10);
const st = $getWorkflowStaticData('global');
st.models = st.models || {};
st.config = CONFIG;
st.global = (st.global || []).filter(t => now - t < 60000);

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
const local = [...(CONFIG.ollama[j.agent] || CONFIG.ollama.default), ...CONFIG.ollama.default, 'ollama/deepseek-v4-flash:cloud'];
// Los especialistas llevan el catálogo de skills en el prompt (miles de tokens):
// van a NVIDIA aunque la tarea sea simple, así Ollama queda libre para el agente general.
const localPrimero = j.agent === 'general' && j.complejidad === 'simple';
// Subtareas paralelas (slot impar) arrancan por el segundo modelo local, así no hacen cola en el mismo
if (localPrimero && Number(j.slot) % 2 === 1) local.splice(0, 2, local[1], local[0]);
const order = [...new Set(localPrimero ? [...local, ...nvidia] : [...nvidia, ...local])];

let chosen = null, soonest = Infinity;
if (r.tried.length < CONFIG.maxIntentos) {
  for (const m of order) {
    if (r.tried.includes(m)) continue;
    const s = st.models[m] = st.models[m] || {};
    s.minute = (s.minute || []).filter(t => now - t < 60000);
    if (!s.day || s.day.date !== today) s.day = { date: today, count: 0 };
    const lim = CONFIG.models[m] || {};
    if (s.cooldownUntil && s.cooldownUntil > now) { soonest = Math.min(soonest, s.cooldownUntil); continue; }
    if (lim.rpd && s.day.count >= lim.rpd) continue;                      // cupo diario agotado
    if (lim.rpm && s.minute.length >= lim.rpm) { soonest = Math.min(soonest, s.minute[0] + 60000); continue; }
    chosen = m; break;
  }
}

// Límite global de la cuenta NVIDIA: esperar a que se libere la ventana de 1 minuto
if (chosen && !isOllama(chosen) && st.global.length >= CONFIG.globalRpmNvidia) {
  const waitSeconds = Math.ceil((st.global[0] + 60000 - now) / 1000) + 1;
  await avisar('espera', `Esperando cupo de la cuenta NVIDIA (${waitSeconds} s)`);
  return { json: { ...j, _router: { ...r, waits: r.waits + 1 }, action: 'esperar', waitSeconds, motivo: 'limite_global_rpm' } };
}

if (!chosen) {
  const waitSeconds = Math.ceil((soonest - now) / 1000) + 1;
  if (isFinite(soonest) && waitSeconds <= CONFIG.maxEsperaSeg && r.waits < CONFIG.maxEsperas && r.tried.length < CONFIG.maxIntentos) {
    await avisar('espera', `Modelos ocupados o en pausa: esperando ${waitSeconds} s`);
    return { json: { ...j, _router: { ...r, waits: r.waits + 1 }, action: 'esperar', waitSeconds, motivo: 'modelos_en_cooldown' } };
  }
  await avisar('error', `Sin modelos disponibles para ${j.agent}`);
  return { json: { ...j, _router: r, action: 'agotado' } };
}

// Registrar el uso
const s = st.models[chosen];
s.minute.push(now);
s.day.count++;
s.lastUsed = new Date(now).toISOString();
if (!isOllama(chosen)) st.global.push(now);

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
