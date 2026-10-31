import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { marked } from 'marked';
import DOMPurify from 'dompurify';
import { api, clave, leerArchivo } from './api.js';

const PIE_AGENTES = /\n+---\n_Agentes:[\s\S]*$/;
const EJEMPLOS = [
  'Armame un informe en PDF y Word sobre cómo elegir una GPU para inferencia local, con un gráfico comparativo',
  'Convertí 72 °F a Celsius y 15 millas a kilómetros',
  '¿Qué skills de NVIDIA me sirven para armar un agente RAG con guardrails?',
  'Generame un Excel con un presupuesto mensual de ejemplo y un gráfico de torta',
];

// Links siempre en pestaña nueva
DOMPurify.addHook('afterSanitizeAttributes', n => {
  if (n.tagName === 'A') { n.setAttribute('target', '_blank'); n.setAttribute('rel', 'noopener'); }
  if (n.tagName === 'IMG') { n.setAttribute('loading', 'lazy'); n.setAttribute('title', 'Clic para ampliar'); }
});

// Visor de imágenes: un clic en una imagen de la respuesta la abre ampliada, con descarga
const verImagen = (src, alt) => dispatchEvent(new CustomEvent('ver-imagen', { detail: { src, alt } }));

function VisorImagen({ img, onCerrar }) {
  useEffect(() => {
    const f = e => e.key === 'Escape' && onCerrar();
    addEventListener('keydown', f);
    return () => removeEventListener('keydown', f);
  }, [onCerrar]);
  const nombre = decodeURIComponent(img.src.split('/').pop() || 'imagen.png');
  return (
    <div className="visor" onClick={onCerrar} role="dialog" aria-label="Imagen ampliada">
      <img src={img.src} alt={img.alt || ''} onClick={e => e.stopPropagation()} />
      <div className="visor-barra" onClick={e => e.stopPropagation()}>
        <span className="visor-nombre">{img.alt && !/^imagen generada/.test(img.alt) ? img.alt : nombre}</span>
        <a className="btn chico" href={img.src + (img.src.includes('?') ? '&' : '?') + 'descargar=1'} download={nombre}>⬇ Descargar</a>
        <a className="btn chico" href={img.src} target="_blank" rel="noopener">Abrir en otra pestaña</a>
        <button className="btn chico" onClick={onCerrar}>Cerrar</button>
      </div>
    </div>
  );
}
const md = txt => ({ __html: DOMPurify.sanitize(marked.parse(txt || '', { breaks: true })) });

// Versión de este bundle (hash que pone Vite en el nombre del archivo)
const MI_VERSION = (import.meta.url.match(/index-([\w-]+)\.js/) || [])[1] || 'dev';

// Los ids de chat pueden tener guiones (los de Cline: cline-…, cline-code-…)
const idDeHash = () => (location.hash.match(/^#\/c\/([\w-]+)/) || [])[1] || null;

function grupo(ts) {
  const d = new Date(ts * 1000), hoy = new Date();
  const dias = Math.floor((new Date(hoy.toDateString()) - new Date(d.toDateString())) / 864e5);
  if (dias <= 0) return 'Hoy';
  if (dias === 1) return 'Ayer';
  if (dias < 7) return 'Últimos 7 días';
  if (dias < 31) return 'Últimos 30 días';
  return d.toLocaleDateString('es-AR', { month: 'long', year: 'numeric' });
}

const hora = ts => new Date(ts * 1000).toLocaleString('es-AR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });

function Cronometro({ desde }) {
  const [, tick] = useState(0);
  useEffect(() => { const t = setInterval(() => tick(x => x + 1), 1000); return () => clearInterval(t); }, []);
  const s = Math.max(0, Math.floor(Date.now() / 1000 - desde));
  return <span>{s >= 60 ? `${Math.floor(s / 60)} min ${s % 60} s` : `${s} s`}</span>;
}

const ICONO = { inicio: '📨', modelo: '🧠', plan: '🗺️', herramienta: '🔧', resultado: '↳', razonamiento: '💭',
  fallo: '⚠️', espera: '⏳', listo: '✅', error: '⛔', verificacion: '🔎' };
const corto = m => String(m || '').replace(/^(ollama|nvidia)\//, '').replace(/^[\w.-]+\/(?=[^/]+$)/, '');

// Texto que se va "escribiendo" (efecto stream) cada vez que cambia
function Tipeo({ texto }) {
  const [n, setN] = useState(0);
  useEffect(() => {
    setN(0);
    const t = setInterval(() => setN(x => { if (x >= texto.length) { clearInterval(t); return x; } return x + 3; }), 16);
    return () => clearInterval(t);
  }, [texto]);
  return <>{texto.slice(0, n)}{n < texto.length && <span className="cursor">▍</span>}</>;
}

// Agentes (con su último modelo) y herramientas usadas, a partir de los eventos
function resumenEventos(eventos) {
  const agentes = {}, herramientas = {};
  for (const e of eventos) {
    if (e.agente && e.tipo === 'modelo') agentes[e.agente] = { modelo: e.modelo, estado: 'trabajando' };
    if (e.agente && ['listo', 'plan', 'verificacion'].includes(e.tipo) && agentes[e.agente]) agentes[e.agente].estado = 'listo';
    if (e.agente && e.tipo === 'fallo' && agentes[e.agente]) agentes[e.agente].estado = 'reintentando';
    if (e.tipo === 'herramienta' && e.herramienta) herramientas[e.herramienta] = (herramientas[e.herramienta] || 0) + 1;
  }
  return { agentes, herramientas };
}

function Chips({ eventos, vivo }) {
  const { agentes, herramientas } = resumenEventos(eventos);
  const nombre = a => a === 'orquestador' ? 'planificador' : a === 'sintesis' ? 'síntesis' : a === 'verificador' ? 'revisión' : a;
  return (
    <div className="chips">
      {Object.entries(agentes).map(([a, d]) => (
        <span key={a} className={`chip agente-chip ${vivo ? d.estado : 'listo'}`} title={d.modelo}>
          {vivo && d.estado === 'trabajando' && <i className="punto-vivo" />}{nombre(a)} · {corto(d.modelo)}
        </span>
      ))}
      {Object.entries(herramientas).map(([h, n]) => (
        <span key={h} className="chip herramienta-chip">🔧 {h}{n > 1 ? ` ×${n}` : ''}</span>
      ))}
    </div>
  );
}

function Pasos({ eventos, desde }) {
  return (
    <ol className="pasos">
      {eventos.map((e, i) => (
        <li key={i} className={`paso ${e.tipo}`}>
          <span className="paso-t">+{Math.max(0, Math.round(e.ts - desde))} s</span>
          <span className="paso-i">{ICONO[e.tipo] || '•'}</span>
          <span className="paso-x">{e.texto}</span>
        </li>
      ))}
    </ol>
  );
}

function EnCurso({ m }) {
  const [abierto, setAbierto] = useState(false);
  const ev = m.eventos || [];
  const ultimo = ev[ev.length - 1];
  return (
    <div className="en-curso">
      <div className="linea-estado">
        <span className="puntos"><i /><i /><i /></span>
        <span className={`linea-texto ${ultimo?.tipo || ''}`}>
          {ultimo ? <>{ICONO[ultimo.tipo] || '•'} <Tipeo texto={ultimo.texto} /></> : 'Los agentes están trabajando…'}
        </span>
        <span className="cronometro"><Cronometro desde={m.creado} /></span>
      </div>
      <Chips eventos={ev} vivo />
      {ev.length > 1 && (
        <button className="btn-link" onClick={() => setAbierto(a => !a)}>{abierto ? 'Ocultar pasos' : `Ver pasos (${ev.length})`}</button>
      )}
      {abierto && <Pasos eventos={ev} desde={m.creado} />}
    </div>
  );
}

function Mensaje({ m, onReintentar }) {
  const [verProceso, setVerProceso] = useState(false);
  if (m.rol === 'usuario') {
    return (
      <div className="msg usuario">
        <div className="burbuja">
          {m.adjunto && <div className="adjunto-chip">📎 {m.adjunto}</div>}
          {m.texto && <div className="texto-plano">{m.texto}</div>}
        </div>
      </div>
    );
  }
  if (m.estado === 'pendiente') {
    return <div className="msg asistente"><EnCurso m={m} /></div>;
  }
  if (m.estado === 'error') {
    return (
      <div className="msg asistente">
        <div className="error">
          <strong>No se pudo completar.</strong> {m.texto}
          <button className="btn chico" onClick={() => onReintentar(m.id)}>Reintentar</button>
        </div>
      </div>
    );
  }
  return (
    <div className="msg asistente">
      <div className="markdown" dangerouslySetInnerHTML={md(m.texto.replace(PIE_AGENTES, ''))}
        onClick={e => { if (e.target.tagName === 'IMG') { e.preventDefault(); verImagen(e.target.src, e.target.alt); } }} />
      <div className="meta">
        {m.agentes?.map((a, i) => (
          <span key={i} className={`agente ${a.proveedor || ''}`} title={a.modelo || ''}>
            {a.agente} · {(a.modelo || 'sin modelo').replace(/^(ollama|nvidia)\//, '')}
          </span>
        ))}
        {m.duracion != null && <span className="dato">{m.duracion} s</span>}
        {(() => {
          const v = (m.eventos || []).filter(e => e.tipo === 'verificacion').pop();
          if (!v) return null;
          const completo = /falta/i.test(v.texto);
          return <span className={`chip ${completo ? 'revision-chip' : 'ok-chip'}`} title={v.texto}>🔎 {completo ? 'completado tras revisión' : 'revisado: cumple lo pedido'}</span>;
        })()}
        {Object.entries(resumenEventos(m.eventos || []).herramientas).map(([h, n]) => (
          <span key={h} className="chip herramienta-chip">🔧 {h}{n > 1 ? ` ×${n}` : ''}</span>
        ))}
        {m.html_url && <a className="btn chico" href={m.html_url} target="_blank" rel="noopener">🌐 Abrir en HTML</a>}
        {m.eventos?.length > 1 && (
          <button className="btn chico fantasma" onClick={() => setVerProceso(v => !v)}>
            {verProceso ? 'Ocultar proceso' : `Proceso (${m.eventos.length} pasos)`}
          </button>
        )}
        <button className="btn chico fantasma" onClick={() => navigator.clipboard?.writeText(m.texto.replace(PIE_AGENTES, ''))}>Copiar</button>
      </div>
      {verProceso && <Pasos eventos={m.eventos} desde={m.eventos[0]?.ts || m.creado} />}
    </div>
  );
}

const ESTADO_MODELO = { disponible: ['ok', 'Disponible'], limite: ['aviso', 'Al límite por minuto'], pausa: ['aviso', 'En pausa por error'],
  agotado: ['mal', 'Cupo diario agotado'], 'sin usar': ['neutro', 'Fuera del router'] };

function PanelModelos({ chat, onCerrar }) {
  const [datos, setDatos] = useState(null);
  const [pestana, setPestana] = useState(chat?.mensajes?.length ? 'chat' : 'locales');
  const [error, setError] = useState('');
  const [sesion, setSesion] = useState(null);
  const cargar = useCallback(() => {
    setError('');
    api.modelos().then(setDatos).catch(e => setError(e.message));
    api.usoModelos(INICIO_SESION).then(d => setSesion(d.modelos)).catch(e => setError(e.message));
  }, []);
  useEffect(() => { cargar(); }, [cargar]);
  useEffect(() => { const f = e => e.key === 'Escape' && onCerrar(); addEventListener('keydown', f); return () => removeEventListener('keydown', f); }, [onCerrar]);

  // Modelos usados en este chat: de los agentes de cada respuesta y de los eventos (incluye planificador y síntesis)
  const usados = useMemo(() => {
    const c = {};
    for (const m of chat?.mensajes || []) {
      const vistos = new Set();
      for (const e of m.eventos || []) if (e.tipo === 'modelo' && e.modelo) vistos.add(`${e.modelo}|${e.agente}`);
      for (const a of m.agentes || []) if (a.modelo) vistos.add(`${a.modelo}|${a.agente}`);
      for (const k of vistos) {
        const [modelo, agente] = k.split('|');
        c[modelo] = c[modelo] || { usos: 0, agentes: new Set() };
        c[modelo].usos++; c[modelo].agentes.add(NOMBRE_SISTEMA[agente] || agente);
      }
    }
    return Object.entries(c).sort((a, b) => b[1].usos - a[1].usos);
  }, [chat]);

  const fecha = t => t ? new Date(t).toLocaleTimeString('es-AR', { hour: '2-digit', minute: '2-digit' }) : '';
  const Punto = ({ estado }) => <i className={`punto ${(ESTADO_MODELO[estado] || ['neutro'])[0]}`} title={(ESTADO_MODELO[estado] || [estado])[1]} />;

  return (
    <div className="modal-velo" onClick={onCerrar}>
      <div className="modal" onClick={e => e.stopPropagation()} role="dialog" aria-label="Modelos">
        <header className="modal-cab">
          <h2>Modelos</h2>
          <button className="btn chico fantasma" onClick={cargar}>Actualizar</button>
          <button className="btn icono" onClick={onCerrar} aria-label="Cerrar">✕</button>
        </header>
        <nav className="pestanas">
          {[['chat', `En este chat (${usados.length})`], ['sesion', `En esta sesión (${sesion?.length ?? '…'})`],
            ['locales', `Locales · Ollama (${datos?.locales.length ?? '…'})`],
            ['remotos', `Remotos · NVIDIA (${datos?.remotos.length ?? '…'})`]].map(([k, t]) => (
            <button key={k} className={pestana === k ? 'activa' : ''} onClick={() => setPestana(k)}>{t}</button>
          ))}
        </nav>
        <div className="modal-cuerpo">
          {error && <div className="aviso">{error}</div>}
          {datos?.errores?.map(e => <div key={e} className="aviso">{e}</div>)}
          {pestana === 'chat' && (usados.length ? (
            <table className="tabla-modelos">
              <thead><tr><th>Modelo</th><th>Tipo</th><th>Respuestas</th><th>Agentes</th></tr></thead>
              <tbody>{usados.map(([m, d]) => (
                <tr key={m}><td className="mono">{corto(m)}</td><td><span className={`chip ${m.startsWith('ollama/') ? 'ollama' : 'nvidia'}`}>{m.startsWith('ollama/') ? 'local' : 'remoto'}</span></td>
                  <td>{d.usos}</td><td>{[...d.agentes].join(', ')}</td></tr>))}</tbody>
            </table>
          ) : <p className="vacio">Todavía no se usaron modelos en este chat.</p>)}
          {pestana === 'sesion' && (!sesion ? <p className="vacio">Cargando…</p> : sesion.length ? (<>
            <p className="dato">Todos los chats, {textoSesion()}.</p>
            <table className="tabla-modelos">
              <thead><tr><th>Modelo</th><th>Tipo</th><th>Respuestas</th><th>Agentes</th><th>Último uso</th></tr></thead>
              <tbody>{sesion.map(m => (
                <tr key={m.modelo}><td className="mono">{corto(m.modelo)}</td>
                  <td><span className={`chip ${m.modelo.startsWith('ollama/') ? 'ollama' : 'nvidia'}`}>{m.modelo.startsWith('ollama/') ? 'local' : 'remoto'}</span></td>
                  <td>{m.usos}</td>
                  <td className="agentes-col">{m.agentes.map(a => NOMBRE_SISTEMA[a] || a).join(', ')}</td>
                  <td>{cuando(m.ultimo)}</td></tr>))}</tbody>
            </table>
          </>) : <p className="vacio">Todavía no se usaron modelos en esta sesión ({textoSesion()}).</p>)}
          {pestana === 'locales' && (!datos ? <p className="vacio">Cargando…</p> : (
            <table className="tabla-modelos">
              <thead><tr><th></th><th>Modelo</th><th>Tamaño</th><th>En memoria</th><th>Usos hoy</th><th>Agentes</th></tr></thead>
              <tbody>{datos.locales.map(m => (
                <tr key={m.id} className={m.en_router ? '' : 'apagado'}>
                  <td><Punto estado={m.en_router ? m.estado : 'sin usar'} /></td>
                  <td className="mono">{m.id}{m.nube && <span className="chip">nube</span>}<small>{[m.parametros, m.cuantizacion].filter(Boolean).join(' · ')}</small></td>
                  <td>{m.nube ? '—' : `${m.tamano_gb} GB`}</td>
                  <td>{m.cargado ? <span className="chip ok-chip">cargado · {m.vram_gb} GB VRAM</span> : <span className="dato">no</span>}</td>
                  <td>{m.usos_hoy || 0}</td>
                  <td className="agentes-col">{m.agentes.join(', ') || (m.en_router ? '' : 'no está en el router')}</td>
                </tr>))}</tbody>
            </table>
          ))}
          {pestana === 'remotos' && (!datos ? <p className="vacio">Cargando…</p> : (<>
            {datos.nvidia_rpm_global && (
              <p className="dato">Cuenta NVIDIA: {datos.nvidia_rpm_global.usados} de {datos.nvidia_rpm_global.limite} pedidos en el último minuto.</p>
            )}
            <table className="tabla-modelos">
              <thead><tr><th></th><th>Modelo</th><th>Hoy</th><th>Último min.</th><th>Último uso</th><th>Agentes</th></tr></thead>
              <tbody>{datos.remotos.map(m => (
                <tr key={m.id}>
                  <td><Punto estado={m.estado} /></td>
                  <td className="mono">{m.id}
                    {m.estado === 'pausa' && <small>En pausa hasta {fecha(m.cooldown_hasta)}</small>}
                    {m.ultimo_error && Date.now() - new Date(m.ultimo_error.at) < 30 * 60000 && <small className="error-texto" title={m.ultimo_error.error}>Último error ({fecha(m.ultimo_error.at)}): {m.ultimo_error.tipo}</small>}
                  </td>
                  <td>{m.usos_hoy}{m.rpd ? ` / ${m.rpd}` : ''}</td>
                  <td>{m.usos_minuto}{m.rpm ? ` / ${m.rpm}` : ''}</td>
                  <td>{fecha(m.ultimo_uso) || <span className="dato">nunca</span>}</td>
                  <td className="agentes-col">{m.agentes.join(', ') || (m.en_fallback ? 'respaldo general' : '')}</td>
                </tr>))}</tbody>
            </table>
          </>))}
        </div>
      </div>
    </div>
  );
}

// ---------- Paneles de agentes, herramientas y skills (mismo formato que Modelos) ----------
// Sesión = desde que se abrió la web en esta pestaña del navegador (sobrevive a recargar la página)
const INICIO_SESION = (() => {
  try {
    let v = sessionStorage.getItem('orquestador.sesion');
    if (!v) { v = String(Date.now() / 1000); sessionStorage.setItem('orquestador.sesion', v); }
    return Number(v);
  } catch { return Date.now() / 1000; }
})();
const textoSesion = () => `desde las ${new Date(INICIO_SESION * 1000).toLocaleTimeString('es-AR', { hour: '2-digit', minute: '2-digit' })}`;
const cuando = t => t ? new Date(t * (t < 1e12 ? 1000 : 1)).toLocaleString('es-AR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' }) : '';
const SKILL_NVIDIA = /github\.com\/NVIDIA\/skills\/tree\/main\/skills\/([\w.-]+)/g;
const LEER_SKILL = /leer_skill\(([\w.-]+)/;

// Uso dentro del chat abierto, a partir de los mensajes y sus eventos de progreso
function usoDelChat(chat) {
  const agentes = {}, herramientas = {}, propias = {}, nvidia = {};
  const sumar = (c, k, t) => { c[k] = c[k] || { usos: 0, ultimo: 0 }; c[k].usos++; c[k].ultimo = Math.max(c[k].ultimo, t || 0); };
  for (const m of chat?.mensajes || []) {
    const enEste = new Set();
    for (const a of m.agentes || []) if (a.agente) enEste.add(a.agente);
    for (const e of m.eventos || []) {
      if (e.tipo === 'modelo' && e.agente) enEste.add(e.agente);
      if (e.tipo === 'herramienta' && e.herramienta) {
        sumar(herramientas, e.herramienta, e.ts);
        const s = e.herramienta === 'leer_skill' && LEER_SKILL.exec(e.texto || '');
        if (s) sumar(propias, s[1], e.ts);
      }
    }
    if (m.rol === 'asistente' && (m.texto || '').includes('· síntesis →')) enEste.add('sintesis');
    for (const a of enEste) sumar(agentes, a, m.creado);
    if (m.rol === 'asistente') for (const id of new Set([...(m.texto || '').matchAll(SKILL_NVIDIA)].map(x => x[1]))) sumar(nvidia, id, m.creado);
  }
  return { agentes, herramientas, propias, nvidia };
}

function Modal({ titulo, pestanas, pestana, setPestana, onActualizar, onCerrar, children }) {
  useEffect(() => { const f = e => e.key === 'Escape' && onCerrar(); addEventListener('keydown', f); return () => removeEventListener('keydown', f); }, [onCerrar]);
  return (
    <div className="modal-velo" onClick={onCerrar}>
      <div className="modal" onClick={e => e.stopPropagation()} role="dialog" aria-label={titulo}>
        <header className="modal-cab">
          <h2>{titulo}</h2>
          <button className="btn chico fantasma" onClick={onActualizar}>Actualizar</button>
          <button className="btn icono" onClick={onCerrar} aria-label="Cerrar">✕</button>
        </header>
        <nav className="pestanas">
          {pestanas.map(([k, t]) => <button key={k} className={pestana === k ? 'activa' : ''} onClick={() => setPestana(k)}>{t}</button>)}
        </nav>
        <div className="modal-cuerpo">{children}</div>
      </div>
    </div>
  );
}

function useDatos(cargarApi) {
  const [datos, setDatos] = useState(null);
  const [error, setError] = useState('');
  const cargar = useCallback(() => { setError(''); cargarApi(INICIO_SESION).then(setDatos).catch(e => setError(e.message)); }, [cargarApi]);
  useEffect(() => { cargar(); }, [cargar]);
  return [datos, error, cargar];
}

function Buscador({ valor, onCambio, placeholder }) {
  return <input className="buscador-panel" value={valor} onChange={e => onCambio(e.target.value)} placeholder={placeholder} />;
}

// Alias de los agentes de sistema (generador/agentes/_sistema.json; el panel de Agentes los trae del servidor)
const NOMBRE_SISTEMA = { orquestador: 'Captain America', sintesis: 'Vision', verificador: 'Doctor Strange' };

function PanelAgentes({ chat, onCerrar }) {
  const [datos, error, cargar] = useDatos(api.agentes);
  const enChat = useMemo(() => usoDelChat(chat).agentes, [chat]);
  const [pestana, setPestana] = useState(Object.keys(enChat).length ? 'chat' : 'todos');
  const porId = useMemo(() => Object.fromEntries([...(datos?.agentes || []), ...(datos?.sistema || [])].map(a => [a.id, a])), [datos]);
  const delChat = Object.entries(enChat).sort((a, b) => b[1].usos - a[1].usos);
  const deSesion = [...(datos?.agentes || []), ...(datos?.sistema || [])].filter(a => a.sesion?.usos).sort((a, b) => b.sesion.usos - a.sesion.usos);
  return (
    <Modal titulo="Agentes" onCerrar={onCerrar} onActualizar={cargar} pestana={pestana} setPestana={setPestana}
      pestanas={[['chat', `En este chat (${delChat.length})`], ['sesion', `En esta sesión (${datos ? deSesion.length : '…'})`],
        ['todos', `Todos (${datos?.agentes.length ?? '…'})`]]}>
      {error && <div className="aviso">{error}</div>}
      {pestana === 'sesion' && (!datos ? <p className="vacio">Cargando…</p> : deSesion.length ? (<>
        <p className="dato">Todos los chats, {textoSesion()}.</p>
        <table className="tabla-modelos">
          <thead><tr><th>Agente</th><th>Rol</th><th>Respuestas</th><th>Último uso</th></tr></thead>
          <tbody>{deSesion.map(a => (
            <tr key={a.id}><td><b>{a.nombre}</b><small className="mono">{a.id}</small></td>
              <td className="agentes-col">{a.rol}</td><td>{a.sesion.usos}</td><td>{cuando(a.sesion.ultimo)}</td></tr>))}</tbody>
        </table>
      </>) : <p className="vacio">Todavía no respondió ningún agente en esta sesión ({textoSesion()}).</p>)}
      {pestana === 'chat' && (delChat.length ? (
        <table className="tabla-modelos">
          <thead><tr><th>Agente</th><th>Rol</th><th>Respuestas</th><th>Último uso</th></tr></thead>
          <tbody>{delChat.map(([id, u]) => (
            <tr key={id}><td><b>{porId[id]?.nombre || NOMBRE_SISTEMA[id] || id}</b><small className="mono">{id}</small></td>
              <td className="agentes-col">{porId[id]?.rol || ''}</td><td>{u.usos}</td><td>{cuando(u.ultimo)}</td></tr>))}</tbody>
        </table>
      ) : <p className="vacio">Todavía no respondió ningún agente en este chat.</p>)}
      {pestana === 'todos' && (!datos ? <p className="vacio">Cargando…</p> : (
        <table className="tabla-modelos">
          <thead><tr><th>Agente</th><th>Rol y alcance</th><th>Skills</th><th>Modelos</th><th>Memoria</th><th>Usos</th><th>Último uso</th></tr></thead>
          <tbody>
            {datos.agentes.map(a => (
              <tr key={a.id} title={a.cuando ? `Se le asigna: ${a.cuando}` : ''}>
                <td><b>{a.nombre}</b><small className="mono">{a.id}</small>{a.personaje && <small>{a.personaje}</small>}</td>
                <td className="agentes-col">{a.rol}<small>{a.alcance}</small></td>
                <td className="agentes-col">
                  {a.skills.length > 0 && <span className="chip">{a.skills.length} del proyecto</span>}
                  {a.skills_inline > 0 && <span className="chip">{a.skills_inline} propias</span>}
                  {a.categorias_nvidia.length > 0 && <small>NVIDIA: {a.categorias_nvidia.join(', ')}</small>}
                </td>
                <td className="mono agentes-col">{corto(a.modelos?.nvidia?.[0] || '')}<small>{(a.modelos?.ollama || []).map(corto).join(', ') || 'locales por defecto'}</small></td>
                <td>{a.memoria?.activa ? `${a.memoria.ventana} msj.` : 'no'}</td>
                <td>{a.usos}</td>
                <td>{cuando(a.ultimo_uso) || <span className="dato">nunca</span>}</td>
              </tr>))}
            {datos.sistema.map(a => (
              <tr key={a.id}><td><b>{a.nombre}</b><small className="mono">{a.id}</small>{a.personaje && <small>{a.personaje}</small>}</td>
                <td className="agentes-col">{a.rol}<small>Agente de sistema</small></td><td></td>
                <td className="mono agentes-col">{corto(a.modelos?.nvidia?.[0] || '')}</td><td>—</td>
                <td>{a.usos}</td><td>{cuando(a.ultimo_uso) || <span className="dato">nunca</span>}</td></tr>))}
          </tbody>
        </table>
      ))}
    </Modal>
  );
}

function PanelHerramientas({ chat, onCerrar }) {
  const [datos, error, cargar] = useDatos(api.herramientas);
  const enChat = useMemo(() => usoDelChat(chat).herramientas, [chat]);
  const [pestana, setPestana] = useState(Object.keys(enChat).length ? 'chat' : 'todas');
  const desc = useMemo(() => Object.fromEntries((datos?.herramientas || []).map(h => [h.nombre, h.descripcion])), [datos]);
  const delChat = Object.entries(enChat).sort((a, b) => b[1].usos - a[1].usos);
  const primera = t => (t || '').split('\n')[0];
  const deSesion = (datos?.herramientas || []).filter(h => h.sesion?.usos).sort((a, b) => b.sesion.usos - a.sesion.usos);
  return (
    <Modal titulo="Herramientas" onCerrar={onCerrar} onActualizar={cargar} pestana={pestana} setPestana={setPestana}
      pestanas={[['chat', `En este chat (${delChat.length})`], ['sesion', `En esta sesión (${datos ? deSesion.length : '…'})`],
        ['todas', `Todas · MCP (${datos?.herramientas.length ?? '…'})`]]}>
      {error && <div className="aviso">{error}</div>}
      {pestana === 'sesion' && (!datos ? <p className="vacio">Cargando…</p> : deSesion.length ? (<>
        <p className="dato">Todos los chats, {textoSesion()}.</p>
        <table className="tabla-modelos">
          <thead><tr><th>Herramienta</th><th>Para qué</th><th>Usos</th><th>Último uso</th></tr></thead>
          <tbody>{deSesion.map(h => (
            <tr key={h.nombre}><td className="mono">{h.nombre}</td><td className="agentes-col" title={h.descripcion}>{primera(h.descripcion)}</td>
              <td>{h.sesion.usos}</td><td>{cuando(h.sesion.ultimo)}</td></tr>))}</tbody>
        </table>
      </>) : <p className="vacio">Todavía no se usaron herramientas en esta sesión ({textoSesion()}).</p>)}
      {datos?.errores?.map(e => <div key={e} className="aviso">{e}</div>)}
      {pestana === 'chat' && (delChat.length ? (
        <table className="tabla-modelos">
          <thead><tr><th>Herramienta</th><th>Para qué</th><th>Usos</th><th>Último uso</th></tr></thead>
          <tbody>{delChat.map(([n, u]) => (
            <tr key={n}><td className="mono">{n}</td><td className="agentes-col" title={desc[n]}>{primera(desc[n])}</td><td>{u.usos}</td><td>{cuando(u.ultimo)}</td></tr>))}</tbody>
        </table>
      ) : <p className="vacio">Todavía no se usaron herramientas en este chat.</p>)}
      {pestana === 'todas' && (!datos ? <p className="vacio">Cargando…</p> : (
        <table className="tabla-modelos">
          <thead><tr><th>Herramienta</th><th>Para qué</th><th>Usos</th><th>Último uso</th></tr></thead>
          <tbody>{datos.herramientas.map(h => (
            <tr key={h.nombre} className={h.usos ? '' : 'apagado'}><td className="mono">{h.nombre}</td>
              <td className="agentes-col" title={h.descripcion}>{primera(h.descripcion)}</td><td>{h.usos}</td>
              <td>{cuando(h.ultimo_uso) || <span className="dato">nunca</span>}</td></tr>))}</tbody>
        </table>
      ))}
    </Modal>
  );
}

function PanelSkills({ chat, onCerrar }) {
  const [datos, error, cargar] = useDatos(api.skills);
  const uso = useMemo(() => usoDelChat(chat), [chat]);
  const delChat = [...Object.entries(uso.propias).map(([id, u]) => ({ id, tipo: 'proyecto', ...u })),
    ...Object.entries(uso.nvidia).map(([id, u]) => ({ id, tipo: 'NVIDIA', ...u }))].sort((a, b) => b.usos - a.usos);
  const [pestana, setPestana] = useState(delChat.length ? 'chat' : 'proyecto');
  const [filtro, setFiltro] = useState('');
  const coincide = s => !filtro || `${s.id} ${s.descripcion} ${s.agente || ''} ${(s.agentes || []).join(' ')} ${s.categoria || ''}`.toLowerCase().includes(filtro.toLowerCase());
  const info = useMemo(() => Object.fromEntries([...(datos?.propias || []), ...(datos?.nvidia || [])].map(s => [s.id, s])), [datos]);
  const nvidiaFiltradas = (datos?.nvidia || []).filter(coincide);
  const deSesion = [...(datos?.propias || []).map(s => ({ ...s, tipo: 'proyecto' })), ...(datos?.nvidia || []).map(s => ({ ...s, tipo: 'NVIDIA' }))]
    .filter(s => s.sesion?.usos).sort((a, b) => b.sesion.usos - a.sesion.usos);
  return (
    <Modal titulo="Skills" onCerrar={onCerrar} onActualizar={cargar} pestana={pestana} setPestana={setPestana}
      pestanas={[['chat', `En este chat (${delChat.length})`], ['sesion', `En esta sesión (${datos ? deSesion.length : '…'})`],
        ['proyecto', `Del proyecto (${datos?.propias.length ?? '…'})`], ['nvidia', `NVIDIA (${datos?.nvidia.length ?? '…'})`]]}>
      {error && <div className="aviso">{error}</div>}
      {datos?.errores?.map(e => <div key={e} className="aviso">{e}</div>)}
      {pestana === 'sesion' && (!datos ? <p className="vacio">Cargando…</p> : deSesion.length ? (<>
        <p className="dato">Todos los chats, {textoSesion()}.</p>
        <table className="tabla-modelos">
          <thead><tr><th>Skill</th><th>Tipo</th><th>Para qué</th><th>Usos</th><th>Último uso</th></tr></thead>
          <tbody>{deSesion.map(s => (
            <tr key={s.tipo + s.id}><td className="mono">{s.id}</td>
              <td><span className={`chip ${s.tipo === 'NVIDIA' ? 'nvidia' : 'ollama'}`}>{s.tipo}</span></td>
              <td className="agentes-col">{(s.descripcion || '').slice(0, 160)}</td><td>{s.sesion.usos}</td><td>{cuando(s.sesion.ultimo)}</td></tr>))}</tbody>
        </table>
      </>) : <p className="vacio">Todavía no se usaron skills en esta sesión ({textoSesion()}).</p>)}
      {(pestana === 'proyecto' || pestana === 'nvidia') && <Buscador valor={filtro} onCambio={setFiltro} placeholder="Buscar por id, descripción, agente o categoría…" />}
      {pestana === 'chat' && (delChat.length ? (
        <table className="tabla-modelos">
          <thead><tr><th>Skill</th><th>Tipo</th><th>Para qué</th><th>Usos</th><th>Último uso</th></tr></thead>
          <tbody>{delChat.map(s => (
            <tr key={s.tipo + s.id}><td className="mono">{s.id}</td>
              <td><span className={`chip ${s.tipo === 'NVIDIA' ? 'nvidia' : 'ollama'}`}>{s.tipo}</span></td>
              <td className="agentes-col">{info[s.id]?.descripcion?.slice(0, 160) || ''}</td><td>{s.usos}</td><td>{cuando(s.ultimo)}</td></tr>))}</tbody>
        </table>
      ) : <p className="vacio">Todavía no se usaron skills en este chat (se cuentan las que los agentes leen y las de NVIDIA que citan).</p>)}
      {pestana === 'proyecto' && (!datos ? <p className="vacio">Cargando…</p> : (
        <table className="tabla-modelos">
          <thead><tr><th>Skill</th><th>Para qué</th><th>Fuente</th><th>Agentes</th><th>Lecturas</th><th>Último uso</th></tr></thead>
          <tbody>{datos.propias.filter(coincide).map(s => (
            <tr key={s.id} className={s.usos ? '' : 'apagado'}>
              <td className="mono">{s.id}</td>
              <td className="agentes-col" title={s.descripcion}>{s.descripcion.slice(0, 160)}{s.descripcion.length > 160 ? '…' : ''}</td>
              <td className="agentes-col">{s.fuente.startsWith('http') ? <a href={s.fuente} target="_blank" rel="noreferrer">{s.autor}</a> : s.autor}<small>{s.licencia}</small></td>
              <td className="agentes-col">{s.agentes.join(', ')}</td>
              <td>{s.usos}</td><td>{cuando(s.ultimo_uso) || <span className="dato">nunca</span>}</td>
            </tr>))}</tbody>
        </table>
      ))}
      {pestana === 'nvidia' && (!datos ? <p className="vacio">Cargando…</p> : (<>
        {nvidiaFiltradas.length > 150 && <p className="dato">Mostrando 150 de {nvidiaFiltradas.length}: usá el buscador para filtrar.</p>}
        <table className="tabla-modelos">
          <thead><tr><th>Skill</th><th>Para qué</th><th>Categoría</th><th>Agente</th><th>Citas</th><th>Último uso</th></tr></thead>
          <tbody>{nvidiaFiltradas.slice(0, 150).map(s => (
            <tr key={s.id} className={s.usos ? '' : 'apagado'}>
              <td className="mono"><a href={`https://github.com/NVIDIA/skills/tree/main/skills/${s.id}`} target="_blank" rel="noreferrer">{s.id}</a></td>
              <td className="agentes-col">{s.descripcion}</td><td className="agentes-col">{s.categoria}</td><td>{s.agente}</td>
              <td>{s.usos}</td><td>{cuando(s.ultimo_uso) || <span className="dato">nunca</span>}</td>
            </tr>))}</tbody>
        </table>
      </>))}
    </Modal>
  );
}

// Pantalla de ingreso: pide la clave de acceso (WEB_ACCESS_TOKEN del .env) y la prueba contra la API
function Ingreso({ onOk }) {
  const [valor, setValor] = useState('');
  const [error, setError] = useState('');
  const [probando, setProbando] = useState(false);
  async function entrar(e) {
    e.preventDefault();
    setProbando(true); setError('');
    clave.guardar(valor.trim());
    try { await api.chats(); onOk(); } catch { clave.borrar(); setError('La clave no es correcta.'); }
    finally { setProbando(false); }
  }
  return (
    <div className="ingreso">
      <form className="ingreso-caja" onSubmit={entrar}>
        <span className="logo" />
        <h1>Orquestador</h1>
        <p>Ingresá la clave de acceso (<code>WEB_ACCESS_TOKEN</code> del archivo <code>.env</code>).</p>
        <input type="password" autoFocus value={valor} onChange={e => setValor(e.target.value)} placeholder="Clave de acceso" autoComplete="current-password" />
        {error && <div className="aviso">{error}</div>}
        <button className="btn primario ancho" disabled={!valor.trim() || probando}>{probando ? 'Verificando…' : 'Entrar'}</button>
      </form>
    </div>
  );
}

export default function App() {
  const [autorizado, setAutorizado] = useState(true);
  useEffect(() => {
    const f = () => setAutorizado(false);
    addEventListener('no-autorizado', f);
    return () => removeEventListener('no-autorizado', f);
  }, []);
  const [chats, setChats] = useState([]);
  const [q, setQ] = useState('');
  const [actualId, setActualId] = useState(idDeHash());
  const [chat, setChat] = useState(null);
  const [texto, setTexto] = useState('');
  const [adjunto, setAdjunto] = useState(null);
  const [enviando, setEnviando] = useState(false);
  const [aviso, setAviso] = useState('');
  const [menu, setMenu] = useState(false);
  const [editando, setEditando] = useState(false);
  const [verModelos, setVerModelos] = useState(false);
  const [panel, setPanel] = useState(null);   // 'agentes' | 'herramientas' | 'skills'
  const [imagen, setImagen] = useState(null);
  useEffect(() => {
    const f = e => setImagen(e.detail);
    addEventListener('ver-imagen', f);
    return () => removeEventListener('ver-imagen', f);
  }, []);
  const [versionNueva, setVersionNueva] = useState(false);

  // Si el servidor tiene una versión más nueva de la web, avisar para recargar
  useEffect(() => {
    if (MI_VERSION === 'dev') return;
    const revisar = () => api.salud().then(h => setVersionNueva(h.version && h.version !== MI_VERSION)).catch(() => {});
    revisar();
    const t = setInterval(revisar, 60000);
    addEventListener('focus', revisar);
    return () => { clearInterval(t); removeEventListener('focus', revisar); };
  }, []);
  const fin = useRef(null), archivo = useRef(null), entrada = useRef(null);

  const cargarLista = useCallback(() => api.chats(q).then(setChats).catch(e => setAviso(e.message)), [q]);
  const cargarChat = useCallback(id => {
    if (!id) { setChat(null); return Promise.resolve(); }
    return api.chat(id).then(setChat).catch(() => { setChat(null); location.hash = ''; });
  }, []);

  useEffect(() => { const t = setTimeout(cargarLista, 250); return () => clearTimeout(t); }, [cargarLista]);
  useEffect(() => {
    const f = () => setActualId(idDeHash());
    addEventListener('hashchange', f);
    return () => removeEventListener('hashchange', f);
  }, []);
  useEffect(() => { cargarChat(actualId); setMenu(false); setEditando(false); setAviso(''); }, [actualId, cargarChat]);

  // Mientras haya respuestas pendientes: el chat abierto cada 1 s (progreso en vivo) y la lista cada 3 s
  const pendiente = chat?.mensajes?.some(m => m.estado === 'pendiente');
  const hayPendientesLista = chats.some(c => c.pendientes > 0);
  useEffect(() => {
    if (!pendiente) return;
    const t = setInterval(() => cargarChat(chat.id), 1000);
    return () => clearInterval(t);
  }, [pendiente, chat?.id, cargarChat]);
  useEffect(() => {
    if (!pendiente && !hayPendientesLista) return;
    const t = setInterval(cargarLista, 3000);
    return () => clearInterval(t);
  }, [pendiente, hayPendientesLista, cargarLista]);

  const cantidad = chat?.mensajes?.length || 0;
  useEffect(() => { fin.current?.scrollIntoView({ behavior: 'smooth' }); }, [cantidad, pendiente]);

  const ir = id => { location.hash = id ? `#/c/${id}` : ''; };

  async function enviar(t = texto) {
    if ((!t.trim() && !adjunto) || enviando) return;
    setEnviando(true); setAviso('');
    try {
      let id = chat?.id;
      if (!id) id = (await api.crear()).id;
      const c = await api.enviar(id, t, adjunto);
      setChat(c); setTexto(''); setAdjunto(null);
      if (id !== actualId) ir(id);
      cargarLista();
    } catch (e) { setAviso(e.message); }
    finally { setEnviando(false); entrada.current?.focus(); }
  }

  async function elegirArchivo(e) {
    const f = e.target.files?.[0];
    e.target.value = '';
    if (!f) return;
    if (f.size > 20 * 1024 * 1024) { setAviso('El archivo supera los 20 MB.'); return; }
    setAdjunto(await leerArchivo(f));
  }

  async function renombrar(id, actual) {
    const t = prompt('Nuevo título del chat', actual);
    if (!t || t === actual) return;
    await api.renombrar(id, t);
    cargarLista(); if (id === chat?.id) cargarChat(id);
  }

  async function borrar(id) {
    if (!confirm('¿Borrar este chat y todas sus respuestas?')) return;
    await api.borrar(id);
    if (id === chat?.id) ir(null);
    cargarLista();
  }

  async function reintentar(msgId) {
    try { setChat(await api.reintentar(msgId)); cargarLista(); } catch (e) { setAviso(e.message); }
  }

  const grupos = useMemo(() => {
    const g = [];
    for (const c of chats) {
      const n = grupo(c.actualizado);
      if (!g.length || g[g.length - 1].nombre !== n) g.push({ nombre: n, chats: [] });
      g[g.length - 1].chats.push(c);
    }
    return g;
  }, [chats]);

  if (!autorizado) return <Ingreso onOk={() => { setAutorizado(true); setAviso(''); cargarLista(); cargarChat(actualId); }} />;

  return (
    <div className={`app ${menu ? 'menu-abierto' : ''}`}>
      <aside className="lateral">
        <div className="marca">
          <span className="logo" />
          <div><strong>Orquestador</strong><small>NVIDIA + Ollama · n8n</small></div>
        </div>
        <button className="btn primario ancho" onClick={() => { ir(null); setChat(null); setTimeout(() => entrada.current?.focus()); }}>＋ Nuevo chat</button>
        <input className="buscar" placeholder="Buscar en chats y respuestas…" value={q} onChange={e => setQ(e.target.value)} />
        <nav className="lista">
          {!chats.length && <p className="vacio">{q ? 'Sin resultados.' : 'Todavía no hay chats.'}</p>}
          {grupos.map(g => (
            <section key={g.nombre}>
              <h4>{g.nombre}</h4>
              {g.chats.map(c => (
                <div key={c.id} className={`item ${c.id === chat?.id ? 'activo' : ''}`} onClick={() => ir(c.id)}>
                  <div className="item-titulo">
                    {c.pendientes > 0 && <span className="punto-vivo" title="Respuesta en curso" />}
                    {c.titulo}
                  </div>
                  <div className="item-sub">{c.ultimo || 'Sin mensajes'}</div>
                  <div className="item-acciones" onClick={e => e.stopPropagation()}>
                    <button title="Renombrar" onClick={() => renombrar(c.id, c.titulo)}>✎</button>
                    <button title="Borrar" onClick={() => borrar(c.id)}>🗑</button>
                  </div>
                </div>
              ))}
            </section>
          ))}
        </nav>
      </aside>
      <div className="velo" onClick={() => setMenu(false)} />

      <main className="principal">
        <header className="cabecera">
          <button className="btn icono menu-btn" onClick={() => setMenu(true)} aria-label="Chats">☰</button>
          {chat ? (
            editando ? (
              <input className="titulo-edit" autoFocus defaultValue={chat.titulo}
                onBlur={async e => { setEditando(false); if (e.target.value.trim() && e.target.value !== chat.titulo) { await api.renombrar(chat.id, e.target.value); cargarChat(chat.id); cargarLista(); } }}
                onKeyDown={e => { if (e.key === 'Enter') e.target.blur(); if (e.key === 'Escape') setEditando(false); }} />
            ) : (
              <h1 title="Doble clic para renombrar" onDoubleClick={() => setEditando(true)}>{chat.titulo}</h1>
            )
          ) : <h1>Nuevo chat</h1>}
          {chat && <span className="fecha">Creado {hora(chat.creado)}</span>}
          <div className="botones-paneles">
            <button className="btn chico" onClick={() => setVerModelos(true)} title="Modelos usados y disponibles">🧠 Modelos</button>
            <button className="btn chico" onClick={() => setPanel('agentes')} title="Agentes usados y disponibles">🦸 Agentes</button>
            <button className="btn chico" onClick={() => setPanel('herramientas')} title="Herramientas usadas y disponibles">🔧 Herramientas</button>
            <button className="btn chico" onClick={() => setPanel('skills')} title="Skills usadas y disponibles">📚 Skills</button>
          </div>
        </header>
        {verModelos && <PanelModelos chat={chat} onCerrar={() => setVerModelos(false)} />}
        {panel === 'agentes' && <PanelAgentes chat={chat} onCerrar={() => setPanel(null)} />}
        {panel === 'herramientas' && <PanelHerramientas chat={chat} onCerrar={() => setPanel(null)} />}
        {panel === 'skills' && <PanelSkills chat={chat} onCerrar={() => setPanel(null)} />}
        {imagen && <VisorImagen img={imagen} onCerrar={() => setImagen(null)} />}
        {versionNueva && (
          <div className="version-nueva">
            Hay una versión nueva de la interfaz.
            <button className="btn chico primario" onClick={() => location.reload()}>Recargar</button>
          </div>
        )}

        <div className="conversacion">
          {!chat?.mensajes?.length ? (
            <div className="bienvenida">
              <h2>¿Qué necesitás?</h2>
              <p>El orquestador reparte el pedido entre agentes especialistas (NVIDIA) y modelos locales (Ollama), y puede generar PDF, Word, Excel y Markdown con gráficos.</p>
              <div className="ejemplos">
                {EJEMPLOS.map(e => <button key={e} onClick={() => enviar(e)}>{e}</button>)}
              </div>
            </div>
          ) : chat.mensajes.map(m => <Mensaje key={m.id} m={m} onReintentar={reintentar} />)}
          <div ref={fin} />
        </div>

        <footer className="redactor">
          {aviso && <div className="aviso" onClick={() => setAviso('')}>{aviso}</div>}
          {adjunto && (
            <div className="adjunto-chip quitar">📎 {adjunto.nombre}
              <button onClick={() => setAdjunto(null)} aria-label="Quitar adjunto">✕</button>
            </div>
          )}
          <div className="caja">
            <button className="btn icono" title="Adjuntar archivo (PDF, Excel, CSV, Word…)" onClick={() => archivo.current?.click()}>📎</button>
            <input ref={archivo} type="file" hidden onChange={elegirArchivo} />
            <textarea ref={entrada} rows={1} value={texto} placeholder={chat ? 'Seguí la conversación…' : 'Escribí tu pedido…'}
              onChange={e => { setTexto(e.target.value); e.target.style.height = 'auto'; e.target.style.height = Math.min(e.target.scrollHeight, 220) + 'px'; }}
              onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); enviar(); } }} />
            <button className="btn primario" disabled={enviando || (!texto.trim() && !adjunto)} onClick={() => enviar()}>
              {enviando ? '…' : 'Enviar'}
            </button>
          </div>
          <small className="ayuda">Enter envía · Shift+Enter salto de línea · Al retomar un chat se envían los últimos mensajes como contexto.</small>
        </footer>
      </main>
    </div>
  );
}
