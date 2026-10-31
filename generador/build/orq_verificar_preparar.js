// Arma el pedido para el verificador: lo que pidió el usuario + la respuesta final (sin el pie de agentes)
const pp = $('Preparar pedido').first().json;
const respuesta = String($json.output || '').replace(/\n+---\n_Agentes:[\s\S]*$/, '');
let adjunto = '';
try { adjunto = $('Agregar texto del adjunto').first().json.textoAdjunto || ''; } catch (e) {}
const pedido = pp.mensaje_usuario || pp.mensaje_original;
return [{ json: {
  agent: 'verificador',
  complejidad: 'compleja',
  session_id: pp.session_id || null,
  prompt: `PEDIDO DEL USUARIO:\n${pedido}\n\nRESPUESTA A REVISAR:\n${respuesta}`,
  // Conversación previa (pedidos de seguimiento como "agregale gráficos") y adjunto, para entender qué se pidió
  contexto: [pp.mensaje_original !== pedido ? pp.mensaje_original : '', adjunto ? adjunto.slice(0, 3000) : ''].filter(Boolean).join('\n\n'),
} }];
