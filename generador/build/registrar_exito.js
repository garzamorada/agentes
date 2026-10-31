const prev = $('Elegir modelo').item.json;

// Aviso de progreso a la web (solo si el pedido viene de un chat de la web local)
const corto = m => String(m || '').replace(/^(ollama|nvidia)\//, '').replace(/^[\w-]+\/(?=[^/]+$)/, '');
const avisar = (tipo, texto, extra = {}) => prev.session_id
  ? this.helpers.httpRequest({ method: 'POST', url: $env.WEB_EVENTOS_URL, json: true, timeout: 2000,
      headers: { 'X-API-Key': $env.WEB_EVENTOS_TOKEN },
      body: { chat: prev.session_id, tipo, texto, agente: prev.agent, modelo: prev.model, ...extra } }).catch(() => null)
  : null;
// Estado compartido en mcp-tools: el modelo respondió, se le borran los avisos de límite
await this.helpers.httpRequest({ method: 'POST', url: $env.MCP_URL.replace(/\/mcp\/?$/, '') + '/router/exito', json: true, timeout: 5000,
  headers: { 'X-API-Key': $env.MCP_API_KEY }, body: { modelo: prev.model } }).catch(() => null);

// Algunos modelos de razonamiento devuelven <think>...</think>
const crudo = String($json.output ?? $json.text ?? '');
let output = crudo.replace(/<think>[\s\S]*?<\/think>/g, '').trim();
// Si el modelo dejó toda la respuesta dentro del razonamiento, usar ese texto
if (!output) output = crudo.replace(/<\/?think>/g, '').trim();

// Razonamiento del modelo (si lo devolvió en <think>) y resumen del paso para la web
const pensado = (crudo.match(/<think>([\s\S]*?)<\/think>/) || [])[1];
if (pensado && pensado.trim()) await avisar('razonamiento', pensado.trim().replace(/\s+/g, ' ').slice(0, 600));
if (prev.agent === 'orquestador') {
  let plan = [];
  try { plan = JSON.parse((output.replace(/```(json)?/g, '').match(/\{[\s\S]*\}/) || ['{}'])[0]).plan || []; } catch (e) {}
  await avisar('plan', plan.length ? `Plan: ${plan.map(p => `${p.agente} → ${String(p.tarea).slice(0, 70)}`).join(' · ')}` : 'Plan listo',
    { datos: plan });
} else if (prev.agent === 'verificador') {
  let v = {};
  try { v = JSON.parse((output.replace(/```(json)?/g, '').match(/\{[\s\S]*\}/) || ['{}'])[0]); } catch (e) {}
  const falta = (v.faltantes || []).filter(Boolean);
  await avisar('verificacion', v.cumple === false && falta.length
    ? `Revisión: falta ${falta.join('; ').slice(0, 200)} — se completa`
    : 'Revisión: la respuesta cumple todo lo pedido');
} else {
  await avisar('listo', prev.agent === 'sintesis' ? 'Respuesta integrada' : `${prev.agente_nombre || prev.agent} terminó`);
}

return {
  json: {
    agent: prev.agent,
    nombre: prev.agente_nombre || null,
    tarea: prev.prompt,
    model: prev.model,
    proveedor: prev.provider,
    output,
    fallos_previos: prev._router.errors,
    ok: true,
  },
};
