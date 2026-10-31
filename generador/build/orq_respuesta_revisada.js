// Respuesta final después de la revisión: la corregida si hizo falta completar algo, si no la original
const base = $('Respuesta final').first().json;
const ev = $('Evaluar verificación').first().json;
const pie = (String(base.output).match(/\n+---\n_Agentes:[\s\S]*$/) || [''])[0];
let output = base.output;
const verificacion = { cumple: ev.cumple, faltantes: ev.faltantes, corregido: false, modelo: ev.verificador };
if (!ev.cumple) {
  const c = $json;  // lo que devolvió el agente al completar
  if (c.ok && String(c.output || '').trim()) {
    output = String(c.output).trim() + (pie ? pie.replace(/_\s*$/, ` · revisión → completó ${c.agent} con ${c.model}_`) : '');
    verificacion.corregido = true;
  } else {
    output = `${base.output}\n\n> ⚠️ La revisión indica que podría faltar: ${ev.faltantes.join('; ')}`;
  }
}
return [{ json: { output, titulo: base.titulo, verificacion } }];
