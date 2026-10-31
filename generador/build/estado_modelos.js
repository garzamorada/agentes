// Devuelve la configuración del router y el uso registrado de cada modelo (lo consulta la web local)
const h = $input.first().json.headers || {};
if ((h['x-api-key'] || '') !== $env.N8N_WEBHOOK_TOKEN) throw new Error('No autorizado: falta o es incorrecto el header X-API-Key');
// Uso registrado: vive en mcp-tools (compartido entre los agentes en paralelo)
const st = await this.helpers.httpRequest({ method: 'GET', url: $env.MCP_URL.replace(/\/mcp\/?$/, '') + '/router/estado', json: true,
  timeout: 5000, headers: { 'X-API-Key': $env.MCP_API_KEY } }).catch(() => ({}));
const ahora = Date.now();
const hoy = new Date().toISOString().slice(0, 10);
const usados = (st.global || []).filter(t => ahora - t < 60000).length;
const agentesDe = m => Object.entries(CONFIG.agents).filter(([, l]) => l.includes(m)).map(([a]) => a)
  .concat(Object.entries(CONFIG.ollama).filter(([, l]) => l.includes(m)).map(([a]) => a === 'default' ? 'general (local)' : `${a} (local)`));
const modelos = Object.entries(CONFIG.models).map(([id, lim]) => {
  const s = (st.models || {})[id] || {};
  const minuto = (s.minute || []).filter(t => ahora - t < 60000).length;
  const dia = s.day && s.day.date === hoy ? s.day.count : 0;
  const cooldown = s.cooldownUntil && s.cooldownUntil > ahora ? new Date(s.cooldownUntil).toISOString() : null;
  const estado = cooldown ? 'pausa' : lim.rpd && dia >= lim.rpd ? 'agotado' : lim.rpm && minuto >= lim.rpm ? 'limite' : 'disponible';
  return {
    id, proveedor: id.startsWith('ollama/') ? 'ollama' : 'nvidia', rpm: lim.rpm || null, rpd: lim.rpd || null,
    usos_minuto: minuto, usos_hoy: dia, estado, cooldown_hasta: cooldown,
    ultimo_uso: s.lastUsed || null, ultimo_error: s.lastError || null, agentes: agentesDe(id),
    en_fallback: CONFIG.fallbackGeneral.includes(id),
  };
});
return [{ json: { generado: new Date().toISOString(), nvidia_rpm_global: { usados, limite: CONFIG.globalRpmNvidia }, modelos } }];
