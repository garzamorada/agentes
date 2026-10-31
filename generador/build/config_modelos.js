// ================== ROUTER DE MODELOS (NVIDIA + OLLAMA) ==================
// Elige el LLM según la especialidad del agente, la complejidad de la tarea
// y el uso registrado. Si un modelo falla o se agota, "Registrar fallo" lo
// marca y vuelve acá para probar el siguiente de la lista.
//
// - Agente general con tarea "simple": primero modelos locales de Ollama, después NVIDIA.
// - Resto: primero NVIDIA, después Ollama como último respaldo.
// - NVIDIA da ~40 requests/minuto POR CUENTA (compartido entre modelos).
// - rpm / rpd por modelo son límites "blandos" propios, editables.
// IDs: "nvidia/..." van por la API de NVIDIA; "ollama/<modelo>" por Ollama local.

const CONFIG = {
  globalRpmNvidia: 36,    // margen bajo el límite de 40 RPM de la cuenta NVIDIA
  maxIntentos: 8,         // modelos distintos a probar por pedido
  maxEsperaSeg: 60,       // espera máxima si todos están en cooldown
  maxEsperas: 3,
  models: {
    'mistralai/mistral-large-4-1t-a52b':       { rpm: 12, rpd: 1500 },
    'nvidia/nemotron-3-ultra-550b-a55b':       { rpm: 12, rpd: 1500 },
    'z-ai/glm-5.3-flash':                      { rpm: 15, rpd: 2000 },
    'deepseek-ai/deepseek-v4.1-flash':         { rpm: 15, rpd: 2000 },
    'minimaxai/minimax-m3.1-flash':            { rpm: 15, rpd: 2000 },
    'stepfun-ai/step-5-preview':               { rpm: 10, rpd: 1000 },
    'poolside/laguna-xs-2.1':                  { rpm: 15, rpd: 2000 },
    'nvidia/nemotron-3.5-super-vl-120b-a12b':  { rpm: 12, rpd: 1500 },
    'nvidia/nemotron-3-nano-omni-30b-a3b-reasoning': { rpm: 20, rpd: 3000 },
    'nvidia/nemotron-3.5-lightning-30b-a3b':   { rpm: 25, rpd: 5000 },
    'nvidia/nemotron-3.5-bolt-e4b':            { rpm: 30, rpd: 5000 },
    'meta/muse-glimmer-30b':                   { rpm: 20, rpd: 3000 },
    'google/gemma-4-31b-it':                   { rpm: 20, rpd: 3000 },
    'openai/gpt-oss-20b':                      { rpm: 25, rpd: 5000 },
    // Ollama local: sin cuota, el límite real es tu GPU (OLLAMA_NUM_PARALLEL)
    'ollama/nemotron-3.5-bolt:e4b':            { rpm: 30 },
    'ollama/nemotron-3-nano:4b':               { rpm: 30 },
    'ollama/qwen3:14b':                        { rpm: 30 },
    'ollama/gemma4:12b':                       { rpm: 30 },
  },
  // Orden de preferencia de modelos de cada agente: sale de generador/agentes/<id>.json ("modelos"); gen.py lo inserta acá.
  // Medido 30/10/2026: mistral-large-4 es lento (~20s+ razonando); glm-5.3, gemma-4, laguna y nano-omni tardaron >45s,
  // por eso quedan como respaldo. Para orquestador, síntesis y verificador, ver AGENTES_SISTEMA en gen.py.
  agents: __MODELOS_NVIDIA__,
  // Modelos locales (todos soportan tool calling). Instalados (31/10/2026):
  // nemotron-3.5-bolt:e4b (7,9 GB) y nemotron-3-nano:4b (2,8 GB) entran juntos en la GPU de 12 GB y se alternan
  // por "slot"; qwen3:14b (9,3 GB) es el de mejor calidad para razonar y código; gemma4:12b (8 GB) entiende imágenes.
  ollama: {
    default: ['ollama/nemotron-3.5-bolt:e4b', 'ollama/nemotron-3-nano:4b', 'ollama/qwen3:14b', 'ollama/gemma4:12b'],
    ...__MODELOS_OLLAMA__,
  },
  // Si se agota toda la lista del agente, sigue con estos
  fallbackGeneral: [
    'nvidia/nemotron-3-ultra-550b-a55b', 'deepseek-ai/deepseek-v4.1-flash', 'minimaxai/minimax-m3.1-flash',
    'nvidia/nemotron-3.5-super-vl-120b-a12b', 'openai/gpt-oss-20b', 'nvidia/nemotron-3.5-lightning-30b-a3b',
    'nvidia/nemotron-3.5-bolt-e4b', 'mistralai/mistral-large-4-1t-a52b', 'z-ai/glm-5.3-flash', 'google/gemma-4-31b-it',
  ],
};
