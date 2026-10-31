// Clave de acceso a la web (WEB_ACCESS_TOKEN del .env): se pide una vez y queda en este navegador
const CLAVE = 'orquestador.clave';
export const clave = {
  leer: () => { try { return localStorage.getItem(CLAVE) || ''; } catch { return ''; } },
  guardar: v => { try { localStorage.setItem(CLAVE, v); } catch { /* sin almacenamiento: se pedirá de nuevo */ } },
  borrar: () => { try { localStorage.removeItem(CLAVE); } catch { /* nada */ } },
};

async function pedir(url, opts = {}) {
  const r = await fetch(url, {
    ...opts,
    headers: { 'Content-Type': 'application/json', 'X-API-Key': clave.leer(), ...(opts.headers || {}) },
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  if (r.status === 401) {
    dispatchEvent(new Event('no-autorizado'));
    throw new Error('Clave de acceso incorrecta o vencida');
  }
  if (!r.ok) {
    let det = r.statusText;
    try { det = (await r.json()).detail || det; } catch { /* sin cuerpo JSON */ }
    throw new Error(det);
  }
  return r.json();
}

export const api = {
  chats: (q = '') => pedir(`/api/chats?q=${encodeURIComponent(q)}`),
  crear: () => pedir('/api/chats', { method: 'POST', body: {} }),
  chat: id => pedir(`/api/chats/${id}`),
  renombrar: (id, titulo) => pedir(`/api/chats/${id}`, { method: 'PATCH', body: { titulo } }),
  borrar: id => pedir(`/api/chats/${id}`, { method: 'DELETE' }),
  enviar: (id, texto, adjunto) => pedir(`/api/chats/${id}/mensajes`, { method: 'POST', body: { texto, adjunto } }),
  reintentar: msgId => pedir(`/api/mensajes/${msgId}/reintentar`, { method: 'POST' }),
  modelos: () => pedir('/api/modelos'),
  // desde: inicio de la sesión de la web (segundos); el servidor devuelve además el uso desde ese momento
  agentes: desde => pedir(`/api/agentes?desde=${desde || 0}`),
  herramientas: desde => pedir(`/api/herramientas?desde=${desde || 0}`),
  skills: desde => pedir(`/api/skills?desde=${desde || 0}`),
  usoModelos: desde => pedir(`/api/uso-modelos?desde=${desde || 0}`),
  salud: () => pedir('/api/health'),
};

export function leerArchivo(file) {
  return new Promise((ok, mal) => {
    const fr = new FileReader();
    fr.onload = () => ok({ base64: String(fr.result).split(',')[1] || '', nombre: file.name, mime: file.type });
    fr.onerror = () => mal(fr.error);
    fr.readAsDataURL(file);
  });
}
