"""Genera los workflows de n8n: herramientas, agente especialista (router NVIDIA + Ollama) y orquestador.

IDs de workflows y credenciales en ids.json.
"""
import json, uuid, pathlib

B = pathlib.Path(__file__).parent
OUT = B.parent / 'workflows'
OUT.mkdir(exist_ok=True)
skills = json.load(open(B / 'skills.json', encoding='utf-8'))
js = lambda n: (B / n).read_text(encoding='utf-8')
IDS = json.load(open(B / 'ids.json', encoding='utf-8'))
# Reglas de uso de herramientas: las mismas que publica el servidor MCP (mcp-tools/reglas.md)
MCP_DIR = B.parent.parent / 'mcp-tools'   # agentes/mcp-tools
REGLAS = (MCP_DIR / 'reglas.md').read_text(encoding='utf-8').strip()
# URLs y claves: n8n las lee de su entorno ($env, ver docker-compose.yml y .env); no quedan escritas en los workflows
MCP_URL = '{{ $env.MCP_URL }}'
MCP_KEY = 'key={{ $env.MCP_API_KEY }}'
DOC_URL = '={{ $env.DOC_SERVICE_URL }}/documento'
AGENTE_URL = '={{ $env.N8N_AGENTE_URL }}'


def cabecera(variable):
    """Header X-API-Key con el valor de una variable de entorno de n8n."""
    return {'sendHeaders': True, 'headerParameters': {'parameters': [{'name': 'X-API-Key', 'value': '={{ $env.%s }}' % variable}]}}
WEBHOOK_PATH = 'agente-especialista'

AGENTS = {
    'agentic_ai': ('Agente de IA agéntica', 'agentes, RAG, guardrails, IA conversacional y ciberseguridad',
                   ['Agentic AI', 'Conversational AI', 'Cybersecurity']),
    'fisica_robotica': ('Agente de IA física y robótica', 'robótica, simulación, Jetson, vehículos autónomos y gemelos digitales',
                        ['Physical AI', 'Robotics', 'Robotics Simulation', 'Simulation and Modeling', 'AV Simulation',
                         'In-Vehicle Computing', 'Digital Twins']),
    'vision': ('Agente de visión', 'visión por computadora, video analytics, DeepStream, Metropolis, VSS',
               ['Vision AI']),
    'entrenamiento_inferencia': ('Agente de entrenamiento e inferencia', 'entrenamiento, fine-tuning, NeMo, TensorRT, NIM, Dynamo, despliegue de modelos',
                                 ['Training AI', 'Inference AI']),
    'datos_optimizacion': ('Agente de datos y optimización', 'ciencia de datos (RAPIDS), optimización (cuOpt) y computación cuántica',
                           ['Data Science', 'Decision Optimization', 'Quantum Computing']),
    'gpu_dev': ('Agente de desarrollo GPU', 'CUDA, librerías GPU, profiling, gaming/RTX',
                ['GPU Development', 'Gaming']),
    'infra_redes': ('Agente de infraestructura y redes', 'clusters, Kubernetes, AI Factory, almacenamiento y redes (DOCA, Spectrum, InfiniBand)',
                    ['Infrastructure', 'AI Factory', 'AI Storage', 'Networking']),
    'salud_ciencias': ('Agente de salud y ciencias', 'salud, ciencias de la vida (BioNeMo, Clara, MONAI) y otros dominios',
                       ['Healthcare, Life Sciences and Other']),
}
for k, (_, _, cats) in AGENTS.items():
    for c in cats:
        assert c in skills, c
assert sum(len(skills[c]) for a in AGENTS.values() for c in a[2]) == sum(len(v) for v in skills.values())

catalog = {
    k: {'nombre': n, 'alcance': a,
        'skills': [f'{sid} — {d}' for c in cats for sid, d in skills[c]]}
    for k, (n, a, cats) in AGENTS.items()
}
# Skills propias del proyecto (no son de NVIDIA): visualización con las herramientas del MCP
catalog['visualizacion'] = {
    'nombre': 'Agente de gráficos e imágenes',
    'alcance': 'gráficos de datos, diagramas, imágenes generadas con IA, portadas y banners, edición de imágenes y capturas, infografías',
    'propias': True,
    'skills': [
        'grafico-elegir-tipo — Elegir el gráfico según la pregunta: comparar, evolución, partes de un total, relación, distribución o grilla',
        'grafico-crear — Gráfico PNG/SVG con crear_grafico: barras, horizontales, apiladas, línea, área, torta, dona, dispersión, histograma, mapa de calor',
        'grafico-desde-datos — Graficar datos de un adjunto, una tabla del usuario o una página web (navegador → extraer tablas), citando la fuente',
        'diagrama-crear — Flujos, procesos, organigramas, arquitecturas y mapas conceptuales con crear_diagrama (nunca Mermaid ni ASCII)',
        'imagen-ia — Imágenes nuevas con IA (FLUX.2 klein en la GPU; escribe textos cortos) con generar_imagen: fotos, ilustraciones, logos, fondos, escenas',
        'imagen-portada — Portadas, banners y placas para redes con texto legible con crear_imagen (tamaños y colores a medida)',
        'imagen-editar — Redimensionar, recortar, agregar texto, collage, convertir, rotar, grises y borde con editar_imagen',
        'infografia-documento — Informes visuales: varios gráficos y diagramas en un PDF, Word, Excel o HTML con generar_documento',
    ],
}
catalog['general'] = {'nombre': 'Agente general', 'skills': [],
                      'alcance': 'tareas simples que no requieren skills de NVIDIA: cálculos, conversiones, fechas, leer o resumir PDF/Excel/CSV/web, armar tablas o planillas'}

PROMPT_JS = '''// Catálogo de agentes (skills NVIDIA agrupadas por especialidad) y armado del prompt de sistema.
const AGENTES = __CATALOG__;

const HERRAMIENTAS = __REGLAS__;

const j0 = $input.item.json;
// Llamado por webhook: exige el token (header X-API-Key = N8N_WEBHOOK_TOKEN). Por Execute Workflow (interno) no hace falta.
if (j0.headers && j0.body !== undefined && (j0.headers['x-api-key'] || '') !== $env.N8N_WEBHOOK_TOKEN) {
  throw new Error('No autorizado: falta o es incorrecto el header X-API-Key');
}
// Llega por Execute Workflow (json directo) o por el webhook (json.body)
const j = j0.body && typeof j0.body === 'object' && j0.body.prompt !== undefined ? j0.body : j0;
const agent = AGENTES[j.agent] || ['orquestador', 'sintesis', 'verificador'].includes(j.agent) ? j.agent : 'general';
let systemPrompt;

if (agent === 'orquestador') {
  const lista = Object.entries(AGENTES)
    .map(([k, a]) => `- ${k}: ${a.nombre} (${a.alcance}).` + (a.skills.length ? `\\n  Skills: ${a.skills.map(s => s.split(' — ')[0]).join(', ')}` : ''))
    .join('\\n');
  systemPrompt = `Sos el ORQUESTADOR de un equipo de agentes especialistas en el ecosistema NVIDIA.
Tu único trabajo es planificar: dividir el pedido del usuario en 1 a 3 subtareas y asignar cada una al agente más adecuado.
Las subtareas se ejecutan EN PARALELO, así que cada una debe ser independiente y autocontenida.

Agentes disponibles:
${lista}

Todos los agentes tienen herramientas (servidor MCP): calculadora, fecha/hora, conversor de unidades, tablas, lector de archivos por URL,
búsqueda web, navegador real (abrir páginas, hacer clic, completar formularios, extraer tablas, capturas de pantalla),
cómo llegar con Google Maps (colectivo, subte, auto, a pie), gráficos, diagramas, imágenes generadas con IA
y generador de documentos (HTML, PDF, Word, Excel con gráficos, Markdown). Tú no ves esas herramientas, pero los agentes sí.
Si el pedido necesita datos actuales de internet (precios, noticias, versiones) o capturas, indicalo en la tarea ("buscá en la web…").
Si el usuario pide un archivo o un gráfico, asigná su creación a UN solo agente (el que tiene el contenido) y escribí en su tarea
qué formatos generar con generar_documento (por ejemplo "generá un PDF y un Excel con gráfico de barras").

Para cada subtarea indicá su complejidad:
- "simple": preguntas cortas, cálculos, conversiones, fechas, resumir o extraer datos de un archivo, armar una tabla. Las resuelve un modelo local chico.
- "compleja": diseño técnico, código extenso, razonamiento profundo, elegir entre muchas skills de NVIDIA,
  o generar documentos/informes con gráficos (PDF, Word, Excel), porque requieren armar datos estructurados.

Respondé SOLO con JSON válido, sin texto extra, con este formato:
{"plan":[{"agente":"<id del agente>","tarea":"<instrucción concreta y autocontenida>","complejidad":"simple|compleja"}]}
Reglas:
- Elegí el agente cuya lista de skills contiene las skills que resuelven el pedido (por ejemplo, Jetson → fisica_robotica).
- Todo lo que mencione productos, herramientas o skills de NVIDIA va a un agente especialista, NUNCA a "general".
- "general" es solo para partes que no necesitan skills de NVIDIA (cálculos, fechas, conversiones, archivos, tablas).
- Gráficos, diagramas, imágenes generadas con IA (fotos, ilustraciones, logos), portadas, banners, infografías o
  editar imágenes y capturas → "visualizacion".
- Rutas y "cómo llegar" (colectivo, subte, auto, a pie), datos de una página web o completar un formulario web → "general"
  con complejidad "compleja", indicando en la tarea que use la herramienta (como_llegar, navegador).
- NUNCA planifiques una tarea de "explicar que no se puede" o "decir qué herramientas hay": los agentes pueden navegar,
  completar formularios, buscar rutas y generar imágenes. Si el usuario pide "reintentá", repetí su pedido anterior
  (está en la conversación previa) como tarea concreta. Si además hay que
  conseguir los datos (de la web o de un archivo), que lo haga el mismo agente en la misma tarea.
- Si el pedido tiene partes de distinto tipo, separalas en subtareas distintas para que corran en paralelo.
- Usá el mínimo de subtareas necesario. Si el pedido es simple y de un solo tipo, una sola.
- Cubrí TODO lo pedido: cada pregunta, dato, cantidad y entregable (formatos de archivo, gráficos, diagramas, capturas)
  tiene que quedar escrito explícitamente en alguna tarea. Al final se revisa que la respuesta cumpla todo.

Ejemplo: "¿cuántos días faltan para Navidad? y ¿qué skill uso para un Jetson?" →
{"plan":[{"agente":"general","tarea":"Calcular cuántos días faltan desde hoy hasta el 25 de diciembre","complejidad":"simple"},{"agente":"fisica_robotica","tarea":"Indicar qué skill de NVIDIA sirve para revisar la salud de un Jetson","complejidad":"simple"}]}`;
} else if (agent === 'sintesis') {
  systemPrompt = `Sos el orquestador. Recibís el pedido original del usuario y las respuestas de los agentes especialistas.
Integralas en una única respuesta clara, en español, sin repetir contenido, conservando los IDs de skills, enlaces y TODOS los links de descarga de archivos tal cual.
Si algún agente no pudo responder, decilo brevemente.
No inventes skills: mencioná solo IDs de skills que aparezcan en las respuestas de los agentes.
No dejes afuera ningún punto del pedido: cada cosa que pidió el usuario tiene que estar respondida o entregada.`;
} else if (agent === 'verificador') {
  systemPrompt = `Sos el VERIFICADOR del orquestador. Revisás si una respuesta cumple TODO lo que pidió el usuario, antes de entregarla.

Revisá punto por punto:
1. Cada pregunta o tarea del pedido tiene su respuesta (si pidió varias cosas, que estén todas).
2. Los entregables pedidos están: archivos en el formato pedido (PDF, Word, Excel, HTML, MD) con su link de descarga,
   gráficos, diagramas, capturas de pantalla, tablas, código, cantidades ("3 opciones", "10 ítems").
3. Los datos concretos pedidos (precios, fechas, cálculos, comparaciones) aparecen con valores, no solo explicaciones,
   y lo que viene de la web tiene su fuente.
4. Si es un pedido de seguimiento (por ejemplo "agregale gráficos"), lo nuevo tiene que estar incorporado.
No evalúes estilo ni redacción, no pidas mejoras opcionales y no inventes requisitos que el usuario no pidió.
Un link a un archivo cuenta como entregado: no podés abrirlo.
Tampoco podés ver imágenes: si la respuesta muestra la imagen pedida (![...](url)) generada con una herramienta,
lo visual (texto dentro de la imagen, estilo, colores) cuenta como entregado; no pidas regenerarla.

Respondé SOLO con JSON válido, sin texto extra:
{"cumple":true|false,"faltantes":["<lo que falta, concreto>"],"instruccion":"<qué tiene que hacer el agente para completarlo>"}
Si cumple, devolvé {"cumple":true,"faltantes":[],"instruccion":""}.`;
} else if (agent === 'visualizacion') {
  const a = AGENTES[agent];
  systemPrompt = `Sos el ${a.nombre} de un equipo de agentes. Tu especialidad: ${a.alcance}.

Tus skills (propias del proyecto). Formato: id — descripción.
${a.skills.join('\\n')}

${HERRAMIENTAS}

Cómo trabajar:
1. Conseguí datos reales antes de graficar: del pedido, del adjunto o de la web (navegador con accion="extraer" objetivo="tablas").
   Nunca inventes números. Si faltan datos, decilo y pedilos.
2. Elegí el tipo de gráfico con la guía de visualización y armá un JSON correcto (etiquetas y valores de igual largo).
3. Mostrá cada imagen en la respuesta con ![título](url) y agregá una o dos líneas que expliquen qué muestra.
4. Si piden un archivo (PDF, Word, Excel), poné los gráficos dentro con generar_documento (graficos_json) en vez de sueltos.
Respondé en español.`;
} else if (agent === 'general') {
  systemPrompt = `Sos el Agente general de un equipo de agentes. Resolvés tareas simples de forma directa y breve, en español.

${HERRAMIENTAS}

Si hay un archivo adjunto, su texto viene en el mensaje. Mostrá los resultados de las herramientas tal cual, sin inventar datos.
No respondas sobre skills o productos de NVIDIA: eso lo hacen los agentes especialistas. Si te lo piden, decí que no te corresponde.`;
} else {
  const a = AGENTES[agent];
  systemPrompt = `Sos el ${a.nombre} de un equipo de agentes NVIDIA. Tu especialidad: ${a.alcance}.

Tenés estas skills oficiales de NVIDIA (https://github.com/NVIDIA/skills). Formato: id — descripción.
${a.skills.join('\\n')}

${HERRAMIENTAS}

Cómo trabajar:
1. Elegí las skills más relevantes para la tarea (por id) y explicá por qué.
2. Resolvé la tarea con pasos concretos, comandos o código cuando corresponda, respetando los requisitos de cada skill.
3. Citá cada skill usada con su enlace: https://github.com/NVIDIA/skills/tree/main/skills/<id>
4. Usá SOLO ids que estén en la lista de arriba; nunca inventes skills.
5. Si la tarea no corresponde a tu especialidad, decilo y sugerí qué tipo de agente la cubre.
Respondé en español.`;
}

return { json: {
  agent,
  prompt: j.prompt,
  contexto: j.contexto,
  complejidad: j.complejidad === 'simple' ? 'simple' : 'compleja',
  slot: Number(j.slot) || 0,
  session_id: j.session_id || j.sessionId || null,
  fase: j.fase || null,   // 'correccion' cuando el verificador pidió completar algo
  systemPrompt,
} };
'''.replace('__CATALOG__', json.dumps(catalog, ensure_ascii=False, indent=1)).replace('__REGLAS__', json.dumps(REGLAS, ensure_ascii=False))

nid = lambda: str(uuid.uuid4())


def node(name, type_, version, pos, params=None, **extra):
    return {'parameters': params or {}, 'id': nid(), 'name': name, 'type': type_, 'typeVersion': version,
            'position': pos, **extra}


def code(name, src, pos, each=True):
    p = {'jsCode': src}
    if each:
        p['mode'] = 'runOnceForEachItem'
    return node(name, 'n8n-nodes-base.code', 2, pos, p)


def note(text, pos, w=420, h=260):
    return node('Nota', 'n8n-nodes-base.stickyNote', 1, pos, {'content': text, 'width': w, 'height': h})


def conn(*pairs):
    """(origen, salida, destino[, tipo, entrada])"""
    c = {}
    for src, out, dst, *rest in pairs:
        typ = rest[0] if rest else 'main'
        idx = rest[1] if len(rest) > 1 else 0
        o = c.setdefault(src, {}).setdefault(typ, [])
        while len(o) <= out:
            o.append([])
        o[out].append({'node': dst, 'type': typ, 'index': idx})
    return c


def cond(left, value, op='equals', typ='string'):
    operator = {'type': typ, 'operation': op}
    if op in ('exists', 'notExists', 'empty', 'notEmpty', 'true', 'false'):
        operator['singleValue'] = True
    return {'options': {'caseSensitive': True, 'leftValue': '', 'typeValidation': 'loose', 'version': 2},
            'conditions': [{'id': nid(), 'leftValue': left, 'rightValue': value, 'operator': operator}],
            'combinator': 'and'}


def switch(name, field, values, pos, fallback=None):
    params = {'rules': {'values': [{'conditions': cond('={{ $json.%s }}' % field, v), 'renameOutput': True,
                                    'outputKey': v} for v in values]},
              'options': {}}
    if fallback:
        params['options'] = {'fallbackOutput': 'extra', 'renameFallbackOutput': fallback}
    return node(name, 'n8n-nodes-base.switch', 3.2, pos, params)


def trigger_inputs(names, pos):
    return node('Entrada', 'n8n-nodes-base.executeWorkflowTrigger', 1.1, pos,
                {'inputSource': 'workflowInputs', 'workflowInputs': {'values': [{'name': n} for n in names]}})


def mapper(values, convert=True):
    """Parámetro resourceMapper para pasar campos a un sub-workflow con entradas definidas."""
    return {'mappingMode': 'defineBelow', 'value': values, 'matchingColumns': [],
            'schema': [{'id': k, 'displayName': k, 'required': False, 'defaultMatch': False, 'display': True,
                        'canBeUsedToMatch': True, 'type': 'string', 'removed': False} for k in values],
            'attemptToConvertTypes': False, 'convertFieldsToString': convert}


def wf(name, nodes, connections, **settings):
    return {'name': name, 'nodes': nodes, 'connections': connections,
            'settings': {'executionOrder': 'v1', **settings}}


# ============ Agente especialista con router (NVIDIA + Ollama) y herramientas ============
nvidia_llm = node('NVIDIA LLM', '@n8n/n8n-nodes-langchain.lmChatOpenAi', 1.2, [860, 520],
                  {'model': {'__rl': True, 'value': '={{ $json.modelName }}', 'mode': 'id'},
                   'options': {'maxRetries': 0, 'timeout': 120000, 'maxTokens': 4096, 'temperature': 0.3}},
                  credentials={'openAiApi': IDS['nvidia_cred']})
ollama_llm = node('Ollama local', '@n8n/n8n-nodes-langchain.lmChatOllama', 1, [1000, 620],
                  {'model': '={{ $json.modelName }}',
                   'options': {'temperature': 0.3, 'numCtx': 8192, 'keepAlive': '15m', 'think': False}})
if IDS.get('ollama_cred'):
    ollama_llm['credentials'] = {'ollamaApi': IDS['ollama_cred']}
selector = node('Elegir proveedor', '@n8n/n8n-nodes-langchain.modelSelector', 1, [880, 360],
                {'numberInputs': 2, 'rules': {'rule': [
                    {'modelIndex': 1, 'conditions': cond('={{ $json.provider }}', 'nvidia')},
                    {'modelIndex': 2, 'conditions': cond('={{ $json.provider }}', 'ollama')}]}})


def tool_code(name, desc, src, pos, example=None):
    p = {'description': desc, 'jsCode': src}
    if example:
        p.update({'specifyInputSchema': True, 'schemaType': 'fromJson', 'jsonSchemaExample': json.dumps(example, ensure_ascii=False, indent=1)})
    return node(name, '@n8n/n8n-nodes-langchain.toolCode', 1.3, pos, p)


def tool_wf(name, desc, wid, inputs, pos, fijos=None):
    """inputs: {campo: descripción} o {campo: (descripción, valor por defecto)} para campos opcionales.
    fijos: {campo: valor o expresión} que no elige el modelo."""
    def from_ai(k, d):
        if isinstance(d, tuple):
            return "={{ $fromAI('%s', `%s`, 'string', '%s') }}" % (k, d[0], d[1])
        return "={{ $fromAI('%s', `%s`, 'string') }}" % (k, d)
    return node(name, '@n8n/n8n-nodes-langchain.toolWorkflow', 2.2, pos,
                {'name': name, 'description': desc, 'source': 'database',
                 'workflowId': {'__rl': True, 'value': wid, 'mode': 'id'},
                 'workflowInputs': mapper({**{k: from_ai(k, d) for k, d in inputs.items()}, **(fijos or {})}),
                 })


# Todas las herramientas vienen del servidor MCP propio (contenedor mcp-tools).
# ?sesion= da a cada ejecución del agente su propia pestaña del navegador.
tools = [
    node('Herramientas (MCP)', '@n8n/n8n-nodes-langchain.mcpClientTool', 1.4, [1300, 400],
         # perfil: el planificador y la síntesis solo ven fecha_hora; los modelos locales, las herramientas básicas
         {'endpointUrl': '=' + MCP_URL + '?' + MCP_KEY + "&sesion={{ $execution.id }}&chat={{ $json.session_id || '' }}&agente={{ $json.agent }}&perfil={{ ['orquestador', 'sintesis', 'verificador'].includes($json.agent)"
                         " ? 'planificador' : $json.provider === 'ollama' ? 'basicas' : 'todas' }}",
          'serverTransport': 'httpStreamable',
          'include': 'except', 'excludeTools': ['leer_archivo'], 'options': {'timeout': 120000}}),
]

sub_nodes = [
    node('Webhook (llamadas en paralelo)', 'n8n-nodes-base.webhook', 2, [0, 100],
         {'httpMethod': 'POST', 'path': WEBHOOK_PATH, 'responseMode': 'lastNode', 'options': {}}, webhookId=nid()),
    node('Entrada (agente, prompt)', 'n8n-nodes-base.executeWorkflowTrigger', 1.1, [0, 300], {'inputSource': 'passthrough'}),
    code('Catálogo y prompt del agente', PROMPT_JS, [220, 200]),
    code('Elegir modelo', js('config_modelos.js') + chr(10) + js('elegir_modelo.js'), [440, 200]),
    # Estado de los modelos para la web (botón "Modelos"): configuración del router + uso registrado
    node('Webhook (estado de modelos)', 'n8n-nodes-base.webhook', 2, [0, 760],
         {'httpMethod': 'GET', 'path': 'estado-modelos', 'responseMode': 'lastNode', 'options': {}}, webhookId=nid()),
    code('Estado de modelos', js('config_modelos.js') + chr(10) + js('estado_modelos.js'), [220, 760], each=False),
    switch('¿Qué hacer?', 'action', ['llamar', 'esperar', 'agotado'], [660, 200]),
    node('Agente especialista', '@n8n/n8n-nodes-langchain.agent', 1.7, [960, 100],
         {'promptType': 'define', 'text': '={{ $json.prompt }}',
          # El contexto va al mensaje de sistema: la memoria guarda solo el pedido y la respuesta
          'options': {'systemMessage': '={{ $json.systemPrompt }}{{ $json.contexto ? "\\n\\n## Contexto\\n" + $json.contexto : "" }}',
                      'maxIterations': 10}},
         onError='continueErrorOutput'),
    # Memoria por chat + agente; sin ID de sesión (o en la síntesis) queda una memoria descartable de esta ejecución.
    # Si el plan tiene varias subtareas del mismo agente corriendo en paralelo, la segunda en adelante (slot > 0)
    # usa su propia memoria para no mezclarse con la primera.
    node('Simple Memory', '@n8n/n8n-nodes-langchain.memoryBufferWindow', 1.4, [1100, 360],
         {'sessionIdType': 'customKey', 'contextWindowLength': 5,
          'sessionKey': "={{ $json.session_id && !['sintesis', 'verificador'].includes($json.agent) ? $json.session_id + ':' + $json.agent"
                        " + ($json.slot ? ':' + $json.slot : '') : 'sin-memoria:' + $execution.id + ':' + $json.agent + ':' + $json.slot }}"}),
    selector, nvidia_llm, ollama_llm, *tools,
    # Respuesta vacía (pasa con modelos locales chicos): se trata como falla y se prueba el siguiente modelo
    node('¿Respondió algo?', 'n8n-nodes-base.if', 2.2, [1240, -60],
         {'conditions': cond("={{ String($json.output ?? '').replace(/<\/?think>/g, '').trim() }}", '', 'notEmpty'), 'options': {}}),
    code('Registrar éxito', js('registrar_exito.js'), [1460, -60]),
    code('Registrar fallo (pasar al siguiente)', js('registrar_fallo.js'), [1360, 160]),
    node('Esperar cupo', 'n8n-nodes-base.wait', 1.1, [660, 460],
         {'amount': '={{ $json.waitSeconds }}', 'unit': 'seconds'}, webhookId=nid()),
    code('Sin modelos disponibles', js('sin_modelos.js'), [960, -120]),
    note('## Router de LLM (NVIDIA + Ollama)\n- **Elegir modelo** decide modelo y proveedor por especialidad y complejidad: el agente *general* con tareas simples va primero a Ollama local; los especialistas, a NVIDIA.\n- **Elegir proveedor** (Model Selector) usa NVIDIA u Ollama según `provider`.\n- Respeta ~40 RPM de NVIDIA y límites rpm/rpd por modelo. Si un modelo falla (429/404/5xx/timeout), **Registrar fallo** le pone cooldown y prueba el siguiente.\n- El **webhook** permite que el orquestador lance varios agentes en paralelo (requiere el workflow publicado).',
         [0, -260], w=520, h=300),
]
sub_pairs = [
    ('Webhook (llamadas en paralelo)', 0, 'Catálogo y prompt del agente'),
    ('Webhook (estado de modelos)', 0, 'Estado de modelos'),
    ('Entrada (agente, prompt)', 0, 'Catálogo y prompt del agente'),
    ('Catálogo y prompt del agente', 0, 'Elegir modelo'),
    ('Elegir modelo', 0, '¿Qué hacer?'),
    ('¿Qué hacer?', 0, 'Agente especialista'),
    ('¿Qué hacer?', 1, 'Esperar cupo'),
    ('¿Qué hacer?', 2, 'Sin modelos disponibles'),
    ('Agente especialista', 0, '¿Respondió algo?'),
    ('¿Respondió algo?', 0, 'Registrar éxito'),
    ('¿Respondió algo?', 1, 'Registrar fallo (pasar al siguiente)'),
    ('Agente especialista', 1, 'Registrar fallo (pasar al siguiente)'),
    ('Registrar fallo (pasar al siguiente)', 0, 'Elegir modelo'),
    ('Esperar cupo', 0, 'Elegir modelo'),
    ('NVIDIA LLM', 0, 'Elegir proveedor', 'ai_languageModel', 0),
    ('Ollama local', 0, 'Elegir proveedor', 'ai_languageModel', 1),
    ('Elegir proveedor', 0, 'Agente especialista', 'ai_languageModel', 0),
    ('Simple Memory', 0, 'Agente especialista', 'ai_memory', 0),
] + [(t['name'], 0, 'Agente especialista', 'ai_tool', 0) for t in tools]
sub = wf('NVIDIA · Agente especialista (router de LLM)', sub_nodes, conn(*sub_pairs), callerPolicy='workflowsFromSameOwner')

# ============ Orquestador ============
def call_sub(name, pos):
    return node(name, 'n8n-nodes-base.executeWorkflow', 1.2, pos,
                {'workflowId': {'__rl': True, 'value': IDS['sub'], 'mode': 'id'}, 'mode': 'once',
                 'options': {'waitForSubWorkflow': True}})


PREP = '''// Mensaje del chat + primer archivo adjunto (si hay) en base64
const it = $input.first();
const msg = it.json.chatInput || it.json.mensaje || it.json.message || '';
let adjunto = null;
const key = Object.keys(it.binary || {})[0];
if (key) {
  const b = it.binary[key];
  const buf = await this.helpers.getBinaryDataBuffer(0, key);
  adjunto = { base64: buf.toString('base64'), nombre: b.fileName || 'archivo', mime: b.mimeType || '' };
}
return [{ json: { agent: 'orquestador', prompt: msg, mensaje_original: msg, complejidad: 'compleja', adjunto, session_id: it.json.sessionId || null } }];'''

ADJ = '''// Suma el texto del adjunto al pedido
const pedido = $('Preparar pedido').first().json;
// Resultado de la herramienta MCP leer_archivo: {archivo, tipo, truncado, texto}
const r = $input.first().json;
const sc = r.structuredContent;
const a = (sc && (sc.result || sc)) || r.content?.[0]?.text || {};
const textoAdjunto = `Archivo adjunto "${a.archivo}" (${a.tipo}${a.truncado ? ', recortado' : ''}):\\n${a.texto}`;
return [{ json: { ...pedido, adjunto: null, textoAdjunto, prompt: `${pedido.mensaje_original}\\n\\n${textoAdjunto}` } }];'''

PARSE = '''// Convierte el plan JSON del orquestador en un ítem por subtarea.
const VALIDOS = ['general','visualizacion','agentic_ai','fisica_robotica','vision','entrenamiento_inferencia','datos_optimizacion','gpu_dev','infra_redes','salud_ciencias'];
const original = $('Preparar pedido').first().json.mensaje_original;
let adjunto = '';
try { adjunto = $('Agregar texto del adjunto').first().json.textoAdjunto || ''; } catch (e) {}
const r = $input.first().json;
let plan = [];
try {
  const txt = String(r.output || '').replace(/```(json)?/g, '');
  const m = txt.match(/\\{[\\s\\S]*\\}/);
  plan = JSON.parse(m ? m[0] : txt).plan || [];
} catch (e) {}
plan = plan.filter(p => VALIDOS.includes(p.agente)).slice(0, 3);
if (!plan.length) plan = [{ agente: 'general', tarea: original, complejidad: 'simple' }];
// slot: posición entre las subtareas del mismo agente, para repartirlas entre los modelos locales
const vistos = {};
// Documentos e informes con gráficos siempre como "compleja" (los modelos locales chicos arman mal los datos)
const DOC = /\\b(pdf|word|docx|excel|xlsx|planilla|informe|reporte|gr[aá]fico|markdown|documento)s?\\b/i;
// Búsquedas y navegación web también (encadenan varias llamadas a herramientas)
const WEB = /\\b(busc[aáeé]\\w*|web|internet|naveg\\w*|captur\\w*|screenshot|sitio|p[aá]gina|precio|cotizaci[oó]n|noticia|maps?|mapa|ruta|llegar|colectivo|subte|tren|recorrido|imagen|im[aá]genes|foto|ilustraci[oó]n|logo)s?\\b|https?:\\/\\//i;
return plan.map(p => ({ json: {
  agent: p.agente,
  prompt: p.tarea,
  complejidad: p.complejidad === 'simple' && !DOC.test(`${p.tarea} ${original}`) && !WEB.test(`${p.tarea} ${original}`) ? 'simple' : 'compleja',
  slot: (vistos[p.agente] = (vistos[p.agente] ?? -1) + 1),
  session_id: $('Preparar pedido').first().json.session_id || null,
  contexto: `Pedido original del usuario: ${original}` + (adjunto ? `\\n\\n${adjunto}` : ''),
} }));'''

SYNTH_IN = '''const original = $('Preparar pedido').first().json.mensaje_original;
const res = $input.all().map(i => i.json);
const err = r => r.output || (r.error ? `Error: ${r.error.message || JSON.stringify(r.error)}` : 'sin respuesta');
// Con un solo agente que respondió bien no hace falta sintetizar
if (res.length === 1 && res[0].ok) {
  return [{ json: { saltar: true, directo: res[0].output } }];
}
const partes = res.map(r => `### ${r.agent || '?'} (modelo: ${r.model || 'ninguno'})\\nTarea: ${r.tarea || ''}\\n\\n${err(r)}`).join('\\n\\n---\\n\\n');
return [{ json: { saltar: false, agent: 'sintesis', complejidad: 'compleja', prompt: `Pedido original:\\n${original}\\n\\nRespuestas de los agentes:\\n\\n${partes}` } }];'''

OUT_JS = '''const esp = $('Ejecutar agentes en paralelo').all().map(i => i.json);
const j = $json;
const final = j.saltar ? j.directo : (j.ok ? j.output : esp.map(e => e.output || '').join('\\n\\n'));
const pie = esp.map(e => `${e.agent || '?'} → ${e.model || 'sin modelo'}${e.fallos_previos?.length ? ` (${e.fallos_previos.length} fallback)` : ''}`).join(' · ');
const sint = j.saltar ? '' : ` · síntesis → ${j.model || 'n/a'}`;
const pp = $('Preparar pedido').first().json;
const original = pp.mensaje_usuario || pp.mensaje_original;
const titulo = original.length > 90 ? original.slice(0, 87) + '...' : original;
return [{ json: { output: `${final}\\n\\n---\\n_Agentes: ${pie}${sint}_`, titulo: titulo || 'Respuesta' } }];'''

CHAT_JS = '''// Respuesta del chat + link a la versión HTML navegable (con descargas)
const base = $('Respuesta revisada').first().json;
const r = $json;
const link = r.html_url ? `\\n\\n🌐 **[Abrir la respuesta en HTML](${r.html_url})**` : '';
return [{ json: { output: base.output + link } }];'''

orq_nodes = [
    node('Chat', '@n8n/n8n-nodes-langchain.chatTrigger', 1.1, [0, 0], {'options': {'allowFileUploads': True}}, webhookId=nid()),
    code('Preparar pedido', PREP, [220, 0], each=False),
    node('¿Adjuntó archivo?', 'n8n-nodes-base.if', 2.2, [440, 0],
         {'conditions': cond('={{ $json.adjunto }}', '', 'exists', 'object'), 'options': {}}),
    node('Leer adjunto', '@n8n/n8n-nodes-langchain.mcpClient', 1.1, [660, -140],
         {'endpointUrl': '=' + MCP_URL + '?perfil=adjuntos&' + MCP_KEY, 'serverTransport': 'httpStreamable',
          'tool': {'__rl': True, 'mode': 'id', 'value': 'leer_archivo'}, 'inputMode': 'json',
          'jsonInput': '={{ JSON.stringify({ contenido_base64: $json.adjunto.base64, nombre: $json.adjunto.nombre, mime: $json.adjunto.mime || "" }) }}',
          'options': {'timeout': 120000}}),
    code('Agregar texto del adjunto', ADJ, [880, -140], each=False),
    call_sub('Orquestador: planificar', [1100, 0]),
    code('Repartir subtareas', PARSE, [1320, 0], each=False),
    node('Ejecutar agentes en paralelo', 'n8n-nodes-base.httpRequest', 4.2, [1540, 0],
         {'method': 'POST', 'url': AGENTE_URL, **cabecera('N8N_WEBHOOK_TOKEN'),
          'sendBody': True, 'specifyBody': 'json',
          'jsonBody': '={{ JSON.stringify({ agent: $json.agent, prompt: $json.prompt, contexto: $json.contexto, complejidad: $json.complejidad, slot: $json.slot, session_id: $json.session_id }) }}',
          'options': {'timeout': 900000}},
         onError='continueRegularOutput'),
    code('Preparar síntesis', SYNTH_IN, [1760, 0], each=False),
    node('¿Hace falta síntesis?', 'n8n-nodes-base.if', 2.2, [1980, 0],
         {'conditions': cond('={{ $json.saltar }}', '', 'false', 'boolean'), 'options': {}}),
    call_sub('Orquestador: sintetizar', [2200, -100]),
    code('Respuesta final', OUT_JS, [2420, 0], each=False),
    # Revisión: el verificador controla que la respuesta cumpla todo lo pedido; si falta algo, el agente principal lo completa (una vez)
    code('Preparar verificación', js('orq_verificar_preparar.js'), [2420, 260], each=False),
    call_sub('Orquestador: verificar', [2640, 260]),
    code('Evaluar verificación', js('orq_verificar_evaluar.js'), [2860, 260], each=False),
    node('¿Cumple todo?', 'n8n-nodes-base.if', 2.2, [3080, 260],
         {'conditions': cond('={{ $json.cumple }}', '', 'true', 'boolean'), 'options': {}}),
    node('Completar lo que falta', 'n8n-nodes-base.httpRequest', 4.2, [3300, 400],
         {'method': 'POST', 'url': AGENTE_URL, **cabecera('N8N_WEBHOOK_TOKEN'),
          'sendBody': True, 'specifyBody': 'json',
          'jsonBody': '={{ JSON.stringify({ agent: $json.agent, prompt: $json.prompt, contexto: $json.contexto, complejidad: $json.complejidad, fase: $json.fase, session_id: $json.session_id }) }}',
          'options': {'timeout': 900000}},
         onError='continueRegularOutput'),
    code('Respuesta revisada', js('orq_respuesta_revisada.js'), [3520, 0], each=False),
    node('Publicar respuesta HTML', 'n8n-nodes-base.httpRequest', 4.2, [3740, 0],
         {'method': 'POST', 'url': DOC_URL, **cabecera('DOC_SERVICE_API_KEY'), 'sendBody': True, 'specifyBody': 'json',
          'jsonBody': "={{ JSON.stringify({ titulo: $json.titulo, contenido_md: $json.output, formatos: 'html', nombre: 'respuesta' }) }}",
          'options': {'timeout': 60000}},
         onError='continueRegularOutput'),
    code('Mensaje del chat', CHAT_JS, [3960, 0], each=False),
    note('## Orquestador multi-agente\n1. Si adjuntás un archivo (PDF, Excel, CSV...), se convierte a texto.\n2. El orquestador divide el pedido en subtareas, elige agente y complejidad.\n3. Los agentes corren **en paralelo** (HTTP → webhook del agente). El agente general (tareas simples) usa Ollama local; los especialistas, NVIDIA.\n4. Si hubo más de un agente, el orquestador integra las respuestas.\n5. Un **verificador** revisa que la respuesta cumpla todo lo pedido; si falta algo, el agente principal lo completa (una vez).\n6. La respuesta se publica también como **HTML navegable** (doc-service) con los links de descarga.\n\nAbrí **Open chat** para probarlo.', [0, -320], w=520, h=280),
]
orq = wf('NVIDIA · Orquestador multi-agente', orq_nodes, conn(
    ('Chat', 0, 'Preparar pedido'),
    ('Preparar pedido', 0, '¿Adjuntó archivo?'),
    ('¿Adjuntó archivo?', 0, 'Leer adjunto'),
    ('¿Adjuntó archivo?', 1, 'Orquestador: planificar'),
    ('Leer adjunto', 0, 'Agregar texto del adjunto'),
    ('Agregar texto del adjunto', 0, 'Orquestador: planificar'),
    ('Orquestador: planificar', 0, 'Repartir subtareas'),
    ('Repartir subtareas', 0, 'Ejecutar agentes en paralelo'),
    ('Ejecutar agentes en paralelo', 0, 'Preparar síntesis'),
    ('Preparar síntesis', 0, '¿Hace falta síntesis?'),
    ('¿Hace falta síntesis?', 0, 'Orquestador: sintetizar'),
    ('¿Hace falta síntesis?', 1, 'Respuesta final'),
    ('Orquestador: sintetizar', 0, 'Respuesta final'),
    ('Respuesta final', 0, 'Preparar verificación'),
    ('Preparar verificación', 0, 'Orquestador: verificar'),
    ('Orquestador: verificar', 0, 'Evaluar verificación'),
    ('Evaluar verificación', 0, '¿Cumple todo?'),
    ('¿Cumple todo?', 0, 'Respuesta revisada'),
    ('¿Cumple todo?', 1, 'Completar lo que falta'),
    ('Completar lo que falta', 0, 'Respuesta revisada'),
    ('Respuesta revisada', 0, 'Publicar respuesta HTML'),
    ('Publicar respuesta HTML', 0, 'Mensaje del chat'),
))

# ============ Orquestador vía webhook (para la web local) ============
WEB_PATH = 'orquestador'
PREP_WEB = '''// Pedido de la web: { mensaje, historial: [{rol, texto}], adjunto: {base64, nombre, mime} }
const h = $input.first().json.headers || {};
if ((h['x-api-key'] || '') !== $env.N8N_WEBHOOK_TOKEN) throw new Error('No autorizado: falta o es incorrecto el header X-API-Key');
const b = $input.first().json.body || $input.first().json;
const msg = String(b.mensaje || b.message || '').trim();
const hist = (Array.isArray(b.historial) ? b.historial : []).slice(-8);
const histTxt = hist.map(h => `${h.rol === 'usuario' ? 'Usuario' : 'Asistente'}: ${String(h.texto || '').slice(0, 2000)}`).join('\\n\\n');
const original = histTxt
  ? `Conversación previa (contexto; respondé solo el pedido actual):\\n${histTxt}\\n\\nPedido actual del usuario: ${msg}`
  : msg;
const a = b.adjunto;
const adjunto = a && a.base64 ? { base64: a.base64, nombre: a.nombre || 'archivo', mime: a.mime || '' } : null;
const contexto = histTxt ? `Conversación previa (respondé solo el pedido actual):\n${histTxt}` : '';
return [{ json: { agent: 'orquestador', prompt: msg, contexto, mensaje_original: original, mensaje_usuario: msg, complejidad: 'compleja', adjunto,
  session_id: b.session_id ? String(b.session_id) : null } }];'''

WEB_OUT = '''// Respuesta JSON para la web
const base = $('Respuesta revisada').first().json;
const esp = $('Ejecutar agentes en paralelo').all().map(i => i.json);
return [{ json: {
  ok: true,
  respuesta: base.output,
  titulo: base.titulo,
  html_url: $json.html_url || null,
  verificacion: base.verificacion || null,
  agentes: esp.map(e => ({ agente: e.agent || '?', modelo: e.model || null, proveedor: e.proveedor || null, ok: !!e.ok })),
} }];'''

import copy
web_nodes = [copy.deepcopy(n) for n in orq_nodes if n['name'] not in ('Chat', 'Mensaje del chat', 'Nota')]
for n in web_nodes:
    n['id'] = nid()
    if n['name'] == 'Preparar pedido':
        n['parameters']['jsCode'] = PREP_WEB
web_nodes = [
    node('Webhook (web)', 'n8n-nodes-base.webhook', 2, [0, 0],
         {'httpMethod': 'POST', 'path': WEB_PATH, 'responseMode': 'lastNode', 'options': {}}, webhookId=nid()),
    *web_nodes,
    code('Respuesta para la web', WEB_OUT, [3960, 0], each=False),
    note('## Orquestador (webhook)\nCopia del orquestador multi-agente para la web local.\n\n`POST /webhook/orquestador`\n```json\n{"mensaje": "...", "historial": [{"rol": "usuario|asistente", "texto": "..."}],\n "adjunto": {"base64": "...", "nombre": "x.pdf", "mime": "application/pdf"}}\n```\nDevuelve `{ok, respuesta, titulo, html_url, agentes}`.', [0, -340], w=560, h=300),
]
orq_web = wf('NVIDIA · Orquestador (webhook para la web)', web_nodes, conn(
    ('Webhook (web)', 0, 'Preparar pedido'),
    *[(a, o, d) for a, o, d in [
        ('Preparar pedido', 0, '¿Adjuntó archivo?'),
        ('¿Adjuntó archivo?', 0, 'Leer adjunto'),
        ('¿Adjuntó archivo?', 1, 'Orquestador: planificar'),
        ('Leer adjunto', 0, 'Agregar texto del adjunto'),
        ('Agregar texto del adjunto', 0, 'Orquestador: planificar'),
        ('Orquestador: planificar', 0, 'Repartir subtareas'),
        ('Repartir subtareas', 0, 'Ejecutar agentes en paralelo'),
        ('Ejecutar agentes en paralelo', 0, 'Preparar síntesis'),
        ('Preparar síntesis', 0, '¿Hace falta síntesis?'),
        ('¿Hace falta síntesis?', 0, 'Orquestador: sintetizar'),
        ('¿Hace falta síntesis?', 1, 'Respuesta final'),
        ('Orquestador: sintetizar', 0, 'Respuesta final'),
        ('Respuesta final', 0, 'Preparar verificación'),
        ('Preparar verificación', 0, 'Orquestador: verificar'),
        ('Orquestador: verificar', 0, 'Evaluar verificación'),
        ('Evaluar verificación', 0, '¿Cumple todo?'),
        ('¿Cumple todo?', 0, 'Respuesta revisada'),
        ('¿Cumple todo?', 1, 'Completar lo que falta'),
        ('Completar lo que falta', 0, 'Respuesta revisada'),
        ('Respuesta revisada', 0, 'Publicar respuesta HTML'),
        ('Publicar respuesta HTML', 0, 'Respuesta para la web'),
    ]],
))
(OUT / 'orquestador_webhook.json').write_text(json.dumps(orq_web, ensure_ascii=False, indent=2), encoding='utf-8')
print('orquestador_webhook.json', len(orq_web['nodes']), 'nodos')

for fn, w in (('agente_especialista.json', sub), ('orquestador.json', orq)):
    (OUT / fn).write_text(json.dumps(w, ensure_ascii=False, indent=2), encoding='utf-8')
    print(fn, len(w['nodes']), 'nodos')
