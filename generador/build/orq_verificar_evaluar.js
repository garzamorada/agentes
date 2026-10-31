// Lee el veredicto del verificador. Si falta algo, arma el pedido de corrección para el agente principal.
// Si el verificador falla o no devuelve JSON, se da por cumplido (la revisión nunca bloquea la respuesta).
const v = $input.first().json;
let r = { cumple: true, faltantes: [], instruccion: '' };
try {
  const m = String(v.output || '').replace(/```(json)?/g, '').match(/\{[\s\S]*\}/);
  if (m) r = { ...r, ...JSON.parse(m[0]) };
} catch (e) {}
const faltantes = (Array.isArray(r.faltantes) ? r.faltantes : []).map(String).filter(f => f.trim()).slice(0, 6);
const cumple = r.cumple !== false || !faltantes.length;

const pp = $('Preparar pedido').first().json;
const previa = String($('Respuesta final').first().json.output || '').replace(/\n+---\n_Agentes:[\s\S]*$/, '');
// Corrige el agente que hizo la parte principal (el primero que respondió bien)
const esp = $('Ejecutar agentes en paralelo').all().map(i => i.json).filter(e => e.ok);
const agente = (esp[0] && esp[0].agent) || 'general';
return [{ json: {
  cumple, faltantes, instruccion: String(r.instruccion || ''), verificador: v.model || null,
  agent: agente, complejidad: 'compleja', fase: 'correccion', session_id: pp.session_id || null,
  prompt: `Tu respuesta anterior NO cumple todo lo que pidió el usuario.
Falta:
${faltantes.map(f => `- ${f}`).join('\n')}
${r.instruccion ? `Cómo completarlo: ${r.instruccion}\n` : ''}
Respuesta anterior:
${previa}

Devolvé la respuesta COMPLETA y corregida (no solo lo que falta). Si faltan archivos, gráficos, diagramas o capturas,
generalos con las herramientas y copiá los links nuevos tal cual.`,
  contexto: `Pedido original del usuario: ${pp.mensaje_original}`,
} }];
