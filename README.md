# Agentes

Orquestador multi-agente local sobre **n8n**: un planificador divide cada pedido en subtareas, las reparte entre
agentes especialistas que corren **en paralelo**, integra las respuestas y un verificador revisa que se cumpla todo
lo pedido antes de entregarlo. Usa modelos de **NVIDIA** (API remota) y **Ollama** (locales, en la GPU), herramientas
propias por **MCP**, generación de documentos e imágenes, y una **web local** con el historial de chats.

- [Funcionalidades](#funcionalidades)
- [Arquitectura](#arquitectura)
- [Modelos elegidos y por qué](#modelos-elegidos-y-por-qué)
- [Requisitos del sistema](#requisitos-del-sistema)
- [Instalación](#instalación)
- [Usar desde VS Code (Cline)](#usar-desde-vs-code-cline)
- [Seguridad](#seguridad)
- [Mantenimiento](#mantenimiento)

---

## Funcionalidades

### Orquestación
- **Planificación**: el orquestador divide el pedido en hasta 3 subtareas y elige agente y complejidad para cada una.
- **Agentes en paralelo**: cada subtarea es una ejecución separada del agente especialista (webhook de n8n).
- **Síntesis**: si respondieron varios agentes, el orquestador integra todo en una sola respuesta.
- **Verificación**: un verificador controla que la respuesta cumpla todo lo pedido; si falta algo, el agente lo
  completa (una vez).
- **Memoria por chat**: cada agente recuerda los últimos intercambios del chat (separada por agente y por subtarea).
- **Adjuntos**: PDF, Word, Excel, CSV, JSON, HTML y texto se convierten a texto y se suman al pedido.

### Agentes
14 agentes con nombre propio, uno por archivo en [generador/agentes/](generador/agentes) (ver
[Cómo se define un agente](#cómo-se-define-un-agente)). Usan el catálogo de **430 skills de NVIDIA** de su área y/o
**55 skills del proyecto** auditadas ([skills/](skills/README.md)).

| Agente | id | Rol | Skills |
|---|---|---|---|
| **Stiuso** | `seguridad` | Ciberseguridad (código e infraestructura) y análisis funcional | 16 del proyecto (Trail of Bits, OWASP, modelado de amenazas, contenedores, requerimientos) + NVIDIA Cybersecurity |
| **Coulson** | `calidad` | Calidad de software: QA, UX, pruebas funcionales y no funcionales | 16 del proyecto (plan de pruebas, ISO 25010, heurísticas UX, accesibilidad, Playwright, Jest, pytest) |
| **Nick Fury** | `arquitectura` | Desarrollo y arquitectura: SOLID, patrones, código limpio, TDD, documentación | 16 del proyecto (SOLID, código limpio, patrones, ADR, refactor, TDD, documentación) |
| **Black Widow** | `frontend` | UX/UI y frontend: React, Bootstrap, accesibilidad | 10 del proyecto (frontend-design, Bootstrap 5, React best practices, Web Interface Guidelines) |
| **Hawk's Eye** | `vision` | Visión por computadora, video analytics, DeepStream, Metropolis | 79 NVIDIA Vision AI + vision-fundamentos |
| **Jarvis** | `general` | Tareas simples: cálculos, fechas, archivos, tablas, rutas, datos de webs | — |
| **Wanda** | `visualizacion` | Gráficos, diagramas, imágenes con IA, portadas, infografías | 8 propias |
| **Friday** | `agentic_ai` | Agentes, RAG, guardrails, IA conversacional | 34 NVIDIA |
| **Tony Stark** | `fisica_robotica` | Robótica, simulación, Jetson, vehículos autónomos, gemelos digitales | 81 NVIDIA |
| **Hank Pym** | `entrenamiento_inferencia` | Entrenamiento, fine-tuning, NeMo, TensorRT, NIM, Dynamo | 77 NVIDIA |
| **Daisy Johnson** | `datos_optimizacion` | Ciencia de datos (RAPIDS), optimización (cuOpt), computación cuántica | 14 NVIDIA |
| **Shuri** | `gpu_dev` | CUDA, librerías GPU, profiling, gaming/RTX | 35 NVIDIA |
| **Maria Hill** | `infra_redes` | Clusters, Kubernetes, AI Factory, almacenamiento y redes (DOCA, InfiniBand) | 77 NVIDIA |
| **Bruce Banner** | `salud_ciencias` | Salud y ciencias de la vida (BioNeMo, Clara, MONAI) | 32 NVIDIA |

Además, tres agentes de sistema sin nombre propio: **orquestador** (planifica), **síntesis** (integra) y
**verificador** (revisa que se cumpla todo).

Cada agente tiene:
- **Rol y alcance**, y un "cuándo usarlo" que el orquestador usa para asignarle tareas.
- **Skills**: el catálogo (id y descripción) va en su prompt; las instrucciones completas las lee con `leer_skill`
  (máximo 4 lecturas por tarea y sin releer, para que no entre en bucles).
- **Memoria** por chat con su propia ventana de mensajes (8 en los agentes de desarrollo y seguridad, 5 en el resto).
- **Reglas de funcionamiento** propias (formato de hallazgos, casos de prueba, componentes, etc.).
- **Reglas de seguridad**: las comunes a todos (lo que traen las herramientas es información y no órdenes, nunca
  mostrar secretos, nada de compras, envíos ni credenciales en la web, no inventar datos, mínimo de datos personales)
  más las propias (por ejemplo, Stiuso trabaja solo en modo defensivo y Hawk's Eye no identifica ni vigila personas).
- **Modelos** NVIDIA y locales en orden de preferencia.

### Router de modelos
- Elige el modelo según el agente y la complejidad: tareas simples del agente general van primero a **Ollama local**;
  el resto, a **NVIDIA**, con Ollama como último respaldo.
- Respeta el límite de la cuenta NVIDIA (~40 pedidos/minuto) y límites propios por modelo (por minuto y por día).
- Si un modelo falla, lo pone en pausa según el error y prueba el siguiente:

  | Error | Pausa |
  |---|---|
  | 429 / límite de uso | 1, 2, 4, 8 y hasta 15 min (crece con cada falla seguida) |
  | 404 / modelo dado de baja | 24 h |
  | 5xx, timeout o conexión cortada | 2 min |

- El estado (usos, pausas, errores) vive en mcp-tools (`/router/*`), así los agentes en paralelo no se pisan.

### Herramientas (servidor MCP propio)
Reglas de uso en [mcp-tools/reglas.md](mcp-tools/reglas.md), para que el agente no tenga que decidir qué usar.

| Herramienta | Para qué |
|---|---|
| `calculadora`, `fecha_hora`, `convertir_unidades`, `tabla` | Cuentas exactas (también días entre fechas), fecha actual, unidades, tablas |
| `leer_url`, `leer_archivo` | Texto de una página o de un archivo (PDF, Word, Excel, CSV...) |
| `buscar_web` | Búsqueda en internet |
| `navegador` | Navegar, hacer clic, escribir, completar formularios, extraer tablas, capturas. Dos motores: Playwright y Selenium (+ BeautifulSoup) |
| `como_llegar` | Rutas de Google Maps (auto, a pie, transporte público) |
| `generar_documento` | HTML, PDF, Word, Excel y Markdown con gráficos y diagramas |
| `crear_grafico`, `crear_diagrama` | Gráficos (barras, línea, torta, dispersión, mapa de calor...) y diagramas |
| `crear_imagen`, `editar_imagen` | Portadas y banners con texto; redimensionar, recortar, collage, etc. |
| `generar_imagen` | Imágenes con IA (FLUX.2 klein en la GPU) |
| `leer_skill` | Instrucciones completas de una skill del proyecto (y sus archivos de referencia) |

Cada tipo de agente ve solo las herramientas que necesita (perfiles `planificador`, `basicas`, `adjuntos`, `todas`).

### Web local (http://localhost:8095)
- Registro de chats para consultarlos y retomarlos (renombrar, borrar, reintentar).
- **Progreso en vivo** en una línea: plan, razonamiento, agentes, modelos y herramientas que se están usando.
- Botón **Modelos**: modelos locales y remotos, su uso, pausas y errores.
- Muestra imágenes y links de descarga de los archivos generados; cada respuesta queda también como HTML.

### Desde VS Code con Cline
El orquestador se puede usar como "modelo" de la extensión [Cline](https://marketplace.visualstudio.com/items?itemName=saoudrizwan.claude-dev)
gracias a una API compatible con OpenAI en `http://localhost:8095/v1` (ver [Usar desde VS Code (Cline)](#usar-desde-vs-code-cline)).

---

## Arquitectura

```mermaid
flowchart LR
  U[Navegador] --> W[orquestador-web<br/>FastAPI + React<br/>:8095]
  W -- webhook --> O[n8n · Orquestador<br/>planificar · repartir · sintetizar · verificar]
  O -- "HTTP en paralelo" --> A1[n8n · Agente especialista]
  O -- "HTTP en paralelo" --> A2[n8n · Agente especialista]
  A1 --> R{Router de modelos}
  R -- API --> N[NVIDIA<br/>build.nvidia.com]
  R --> L[ollama<br/>GPU :11434]
  A1 -- MCP --> M[mcp-tools<br/>herramientas + estado del router<br/>:8092]
  M --> D[doc-service<br/>documentos y gráficos<br/>:8090]
  M --> I[imagen-ia<br/>FLUX.2 klein · GPU<br/>:8094]
  M --> WEB[(Internet)]
  A1 & M -. eventos de progreso .-> W
  D -- /files --> U
```

| Servicio | Qué es | Puerto | RAM máx. |
|---|---|---|---|
| `n8n-container` | n8n 2.x: workflows del orquestador y los agentes, credenciales cifradas | 5678 | 2 GB |
| `n8n-runners` | Ejecuta los nodos de código de n8n (task runners) | — | 1 GB |
| `ollama` | Modelos locales en la GPU (volumen `agentes_ollama`) | 11434 | 6 GB |
| `imagen-ia` | Imágenes con IA en la GPU (volumen `agentes_imagen_modelos`) | 8094 | 6 GB |
| `mcp-tools` | Servidor MCP (Python): herramientas, navegador Chromium/Chrome, estado del router | 8092 | 3 GB |
| `doc-service` | Genera HTML, PDF, Word, Excel y MD; sirve `/files` | 8090 | 1 GB |
| `orquestador-web` | Web local (FastAPI + React, chats en SQLite) y API compatible con OpenAI para Cline (`/v1`) | 8095 | 512 MB |

**GPU compartida**: Ollama e imagen-ia usan la misma GPU. Antes de cargar FLUX, imagen-ia le pide a Ollama que
libere sus modelos y, tras 3 minutos sin uso, libera la VRAM para que Ollama la vuelva a usar.

### Carpetas

| Carpeta | Contenido |
|---|---|
| `generador/agentes` | Un JSON por agente: nombre, rol, skills, reglas, seguridad, memoria y modelos |
| `generador` | `build/gen.py` genera los workflows de n8n (`workflows/*.json`); código JS del router en `build/*.js` |
| `skills` | Skills auditadas que leen los agentes (montadas en mcp-tools como `/skills`); fuentes y auditoría en `fuentes.json` |
| `mcp-tools` | Servidor MCP y reglas de las herramientas |
| `imagen-ia` | Servicio de imágenes con IA (diffusers) |
| `doc-service` | Generador de documentos y gráficos |
| `orquestador-web` | Backend FastAPI y frontend React |
| `n8n/n8n_data` | Datos de n8n (workflows, credenciales cifradas, historial) — no se sube a git |
| `documentos_generados` | Archivos que generan los agentes — no se sube a git |

### Workflows de n8n

| Workflow | Para qué |
|---|---|
| NVIDIA · Agente especialista (router de LLM) | Elige el modelo, usa las herramientas MCP, memoria por chat, avisa el progreso. Webhooks `agente-especialista` y `estado-modelos` |
| NVIDIA · Orquestador (webhook para la web) | `POST /webhook/orquestador`: planifica, reparte en paralelo, sintetiza y verifica |
| NVIDIA · Orquestador multi-agente | El mismo orquestador para el chat de n8n (Open chat) |
| NVIDIA · Proxy de LLM (orquestador de código) | `POST /webhook/llm-proxy`: reenvía mensajes y herramientas de Cline a la API de NVIDIA con la credencial de n8n (lo usa `orquestador-codigo`) |

Para cambiarlos: editar `generador/agentes/*.json` o `generador/build/*` y correr `python generador/build/gen.py`; los JSON quedan en
`generador/workflows/` y se importan pegándolos en n8n (revisar que el selector de modelo, la memoria y el nodo MCP
sigan conectados al agente) y **publicar** (los webhooks usan la versión publicada).

### Cómo se define un agente

Cada archivo `generador/agentes/<id>.json` tiene esta estructura (ejemplo resumido de Stiuso):

```json
{
  "id": "seguridad",
  "nombre": "Stiuso",
  "personaje": "Jaime Stiuso, histórico jefe de operaciones de inteligencia argentino",
  "rol": "Analista de ciberseguridad y analista funcional",
  "alcance": "seguridad en código, seguridad de infraestructura, modelado de amenazas y análisis funcional",
  "cuando_usarlo": "revisar la seguridad de código, configuraciones o pipelines; modelar amenazas; relevar requerimientos",
  "skills_nvidia": { "fuente": "https://github.com/NVIDIA/skills", "categorias": ["Cybersecurity"] },
  "skills": ["security-review", "threat-model-analyst", "seguridad-contenedores-infra", "analisis-funcional"],
  "skills_inline": [],
  "reglas": ["Cada hallazgo lleva: ubicación, severidad, evidencia, impacto y corrección concreta."],
  "seguridad": ["Trabajo defensivo: no escribas exploits operativos ni malware."],
  "memoria": { "activa": true, "ventana": 8 },
  "modelos": {
    "nvidia": ["nvidia/nemotron-3-ultra-550b-a55b", "deepseek-ai/deepseek-v4.1-flash"],
    "ollama": ["ollama/qwen3:14b", "ollama/gemma4:12b"]
  }
}
```

| Campo | Para qué |
|---|---|
| `id` | Identificador que usa el orquestador en el plan (igual al nombre del archivo) |
| `nombre`, `personaje`, `rol`, `alcance` | Identidad del agente en su prompt y en la web |
| `cuando_usarlo` | Le dice al orquestador qué tareas asignarle |
| `skills_nvidia.categorias` | Categorías del catálogo de NVIDIA (`generador/build/skills.json`); cada una va en un solo agente |
| `skills` | Ids de carpetas de `skills/` que el agente puede leer con `leer_skill` |
| `skills_inline` | Skills cortas escritas directo en el prompt (`id — descripción`) |
| `reglas` | Reglas de funcionamiento propias |
| `seguridad` | Reglas de seguridad propias (se suman a las comunes de `SEGURIDAD_COMUN` en `gen.py`) |
| `memoria` | Si recuerda el chat y cuántos mensajes |
| `modelos` | Modelos NVIDIA y locales en orden de preferencia (`null` en `ollama` usa los locales por defecto); cada modelo tiene que tener sus límites en `config_modelos.js` |

Para crear un agente nuevo: copiar un JSON, cambiar el `id` y el nombre del archivo, completar los campos, correr
`gen.py` y actualizar los tres workflows en n8n. `gen.py` valida que existan las skills y los modelos, y que cada
categoría de NVIDIA esté en un solo agente.

---

## Modelos elegidos y por qué

La configuración está en [generador/build/config_modelos.js](generador/build/config_modelos.js). Velocidades medidas
en esta PC en octubre de 2026.

### Locales (Ollama, RTX 3060 12 GB)

| Modelo | Disco | Uso | Por qué |
|---|---|---|---|
| `nemotron-3.5-bolt:e4b` | 7,9 GB | Primero para tareas simples | Rápido (~100 tok/s), buen tool calling. Entra en la GPU junto con nano |
| `nemotron-3-nano:4b` | 2,8 GB | Segundo para tareas simples | Muy liviano; las subtareas en paralelo se alternan entre bolt y nano para no hacer cola |
| `qwen3:14b` | 9,3 GB | Código, infraestructura y respaldo | El de mejor calidad para razonar y programar que entra en 12 GB |
| `gemma4:12b` | 8 GB | Visión y respaldo | Entiende imágenes |

Se desinstalaron `gemma4:latest`, `glm4`, `llama3.1:8b` y `qwen2.5-coder:7b` (~23 GB): quedaban cubiertos por
estos cuatro con mejor calidad o velocidad, y casi no los elegía el router. También se sacó `deepseek-v4-flash:cloud`
(servido por ollama.com, con cuota propia): NVIDIA ya cubre ese rol.

### Remotos (API de NVIDIA)

| Rol | Primer modelo | Por qué |
|---|---|---|
| Orquestador (planificar) y síntesis | `nemotron-3-ultra-550b-a55b` | El mejor siguiendo instrucciones y armando el plan JSON |
| Verificador, agente general, visualización | `nemotron-3.5-lightning-30b-a3b` | MoE rápido; ultra tardaba más de 100 s en revisar |
| Visión | `nemotron-3.5-super-vl-120b-a12b` | Modelo de visión y lenguaje |
| Entrenamiento e inferencia | `deepseek-v4.1-flash` | Rápido y bueno en temas técnicos |
| Datos y optimización | `gpt-oss-20b` | Rápido y bueno con números |
| Desarrollo GPU | `step-5-preview` | Fuerte en código (si se cuelga queda en pausa y sigue `minimax-m3.1-flash`) |
| Infraestructura y redes | `minimax-m3.1-flash` | Rápido, buen tool calling |
| Stiuso (seguridad) y Nick Fury (arquitectura) | `nemotron-3-ultra-550b-a55b` | Razonamiento profundo para revisar código y decidir arquitectura; local: `qwen3:14b` |
| Coulson (calidad) | `deepseek-v4.1-flash` | Rápido para armar planes y casos de prueba extensos |
| Black Widow (frontend) | `deepseek-v4.1-flash` | Buen código React; `minimax-m3.1-flash` de respaldo |

Cada agente tiene 4 modelos en orden de preferencia, y después una lista general de respaldo (`fallbackGeneral`).
`mistral-large-4`, `glm-5.3`, `gemma-4-31b`, `laguna` y `nano-omni` quedaron como respaldo porque tardaban más de 45 s.

### Imágenes

| Modelo | Por qué |
|---|---|
| **FLUX.2 [klein] 4B** (Black Forest Labs, Apache 2.0) | Sigue mejor el prompt que SDXL y escribe bien textos cortos (carteles, títulos). Con el text encoder Qwen3-4B en 4 bits (NF4) y el transformer en bf16 entra en 12 GB. ~17 s por imagen de 1024×1024 con el modelo cargado; ~1,5 min la primera carga. Las imágenes se generan de a una y hasta ~1 megapíxel (juntas o más grandes desbordan la VRAM) |
| SDXL-Lightning (alternativa, `IMAGEN_MODELO=sdxl-lightning`) | ~4 s, pero peor calidad y sin texto legible. Sus pesos no están descargados: se bajan (~7 GB) la primera vez que se use |

Los modelos "Downloadable" de build.nvidia.com (contenedores NIM) piden GPUs RTX 40/50 o superiores y no corren en
la RTX 3060 (Ampere); FLUX.2 klein se usa con sus pesos abiertos de Hugging Face y `diffusers`.

---

## Requisitos del sistema

### Equipo usado (de referencia)
- Windows 11 Pro, AMD Ryzen 7 5700G, 32 GB de RAM
- NVIDIA GeForce RTX 3060 de 12 GB (driver 576)
- Docker Desktop 4.86 con WSL 2

### Mínimos

| Recurso | Mínimo | Notas |
|---|---|---|
| GPU | NVIDIA con 12 GB de VRAM | Para FLUX y los modelos locales de 8–9 GB. Driver ≥ 570 (CUDA 12.8). Con 8 GB: usar solo los modelos chicos y `FLUX_TRANSFORMER=nf4` |
| RAM | 32 GB recomendados | Los contenedores suman ~20 GB de tope; WSL está limitado a 12 GB + 4 GB de swap |
| Disco | ~100 GB libres | Ollama ~28 GB, FLUX ~16 GB, imágenes de Docker ~35 GB, más documentos y caché |
| Software | Docker Desktop con WSL 2 y soporte de GPU NVIDIA | Ollama e imagen-ia usan `deploy.resources.devices` con `driver: nvidia` |
| Cuenta | API key de NVIDIA (build.nvidia.com) | Gratuita, ~40 pedidos/minuto |
| Red | Internet | API de NVIDIA, búsquedas, navegación y la primera descarga de modelos |

### Límites de WSL (`%USERPROFILE%\.wslconfig`)

```ini
[wsl2]
memory=12GB
swap=4GB

[experimental]
autoMemoryReclaim=gradual
sparseVhd=true
```

---

## Instalación

```bash
cp .env.default .env      # completar las claves (ver Seguridad)
docker compose up -d --build
docker exec ollama ollama pull nemotron-3.5-bolt:e4b
docker exec ollama ollama pull nemotron-3-nano:4b
docker exec ollama ollama pull qwen3:14b
docker exec ollama ollama pull gemma4:12b
```

Después, en n8n (http://localhost:5678):
1. Crear la credencial **"OpenAI account"** con la API key de NVIDIA y la URL base `https://integrate.api.nvidia.com/v1`.
2. Crear la credencial **"Ollama account"** con la URL `http://ollama:11434`.
3. Importar los tres JSON de `generador/workflows/`, elegir esas credenciales en los nodos de modelo (los JSON traen
   los IDs de esta instalación, en `generador/build/ids.json`) y publicarlos.

Los pesos de FLUX (~16 GB) se descargan solos la primera vez que se pide una imagen.

Para generar cada clave:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Reconstruir un solo servicio después de cambiar su código, por ejemplo la web:

```bash
docker compose up -d --build orquestador-web
```

---

## Usar desde VS Code (Cline)

`orquestador-web` expone una API compatible con OpenAI (`GET /v1/models` y `POST /v1/chat/completions`, con
streaming) para usar el orquestador y sus agentes desde la extensión **Cline** de VS Code. Hay dos modelos:

| Model ID | Qué hace | Edita archivos |
|---|---|---|
| `orquestador` | El orquestador de siempre: planifica, reparte entre agentes, sintetiza y verifica. Responde con texto (explicaciones, revisiones, código para copiar) | No |
| `orquestador-codigo` | Un equipo de especialistas arma el plan y un modelo ejecutor trabaja **dentro del proyecto** con las herramientas de Cline: lee, crea y edita archivos y ejecuta comandos (con tu aprobación) | Sí |

### Configuración

1. Copiar la clave de Cline del `.env` (no la pegues en ningún otro lado):

   ```bash
   grep CLINE_API_KEY .env
   ```

2. En VS Code, abrir Cline y entrar a la configuración (ícono de engranaje) → **API Configuration**.
3. Completar:

   | Campo | Valor |
   |---|---|
   | API Provider | `OpenAI Compatible` |
   | Base URL | `http://localhost:8095/v1` |
   | API Key | el valor de `CLINE_API_KEY` |
   | Model ID | `orquestador-codigo` (edita el proyecto) u `orquestador` (solo responde) |

4. En **Model Configuration** (si aparece): desmarcar **Supports Images** (las imágenes no se envían al orquestador),
   y dejar un **Context Window** amplio (por ejemplo 128000) para que Cline no recorte la conversación.
5. Guardar (**Done**) y escribir una tarea en el chat de Cline. Para probar la conexión sin VS Code:

   ```bash
   curl -H "Authorization: Bearer <CLINE_API_KEY>" http://localhost:8095/v1/models
   ```

Si VS Code corre en otra PC, hay que publicar el puerto de la web fuera de `127.0.0.1` (`BIND_IP` en `.env`) y usar
la IP de esta PC en la Base URL; hacelo solo en una red de confianza.

### Cómo funciona `orquestador-codigo` (edita el proyecto)

```mermaid
flowchart LR
  C[Cline en VS Code] -- "cada turno: conversación + herramientas" --> W[orquestador-web /v1]
  W -- "1 vez por tarea" --> P[Orquestador n8n: elige especialistas]
  P --> E1[Especialista líder<br/>ej. Nick Fury]
  P --> E2[Especialista de apoyo<br/>ej. Coulson]
  E1 & E2 -- plan técnico con sus skills --> W
  W -- "conversación + guía del equipo" --> X[Ejecutor<br/>deepseek / minimax / ultra / laguna]
  X -- "read_file, replace_in_file, write_to_file, execute_command..." --> C
  C -- "ejecuta con tu aprobación y devuelve el resultado" --> W
```

1. **Equipo (al empezar la tarea):** el planificador del orquestador elige hasta 2 especialistas que programan
   (Nick Fury, Black Widow, Stiuso, Coulson...). Cada uno arma un **plan técnico** con sus skills: archivos a tocar,
   pasos, decisiones de diseño, pruebas y riesgos. Se guarda para toda la tarea.
   Si el planificador no responde en 45 s, el equipo se elige por palabras de la tarea (React/CSS/UI → Black Widow,
   seguridad → Stiuso, tests → Coulson; Nick Fury lidera por defecto) y cada especialista tiene hasta 150 s para su plan.
2. **Ejecutor (cada turno):** recibe la conversación completa de Cline (con sus herramientas) más la **guía del
   equipo**: los planes, las reglas de funcionamiento y las reglas de seguridad de los especialistas y del ejecutor
   (leer antes de editar, cambios mínimos, nada destructivo, sin secretos en el código, verificar antes de entregar).
   Responde con una herramienta de Cline; Cline la ejecuta **pidiéndote aprobación** (salvo lo que tengas en
   auto-approve) y le devuelve el resultado. El ciclo sigue hasta `attempt_completion`.
   Si el modelo responde sin una herramienta de Cline (o en su propio formato), se le pide una vez que reintente, y
   se limpian los tokens internos que algunos modelos dejan en el texto.
3. **Modelos:** el ejecutor prueba en orden `CLINE_EJECUTORES` (por defecto deepseek-v4.1-flash, minimax-m3.1-flash,
   nemotron-3-ultra y laguna-xs-2.1) con el **router compartido** (cupos y pausas). Los modelos de NVIDIA se llaman por
   el workflow **"NVIDIA · Proxy de LLM"** de n8n (`/webhook/llm-proxy`), así la API key sigue guardada solo en n8n.
4. **Registro:** cada tarea es un chat **"Cline (código): …"** en la web, con el equipo, los planes y cada herramienta
   que usó el ejecutor, turno por turno. En Cline, el progreso se ve como razonamiento.

Recomendaciones: dejá **sin auto-approve** los comandos (`execute_command`) y revisá cada diff antes de aceptarlo;
para tareas grandes, empezá en modo **Plan** y pasá a **Act** cuando el plan te convenza.

### Cómo funciona `orquestador` (solo responde)

- Cada tarea de Cline es un chat de la web llamado **"Cline: …"**: queda en el historial de http://localhost:8095,
  con el progreso, y los agentes recuerdan los mensajes anteriores de esa tarea.
- Se envía el pedido (la tarea o la respuesta que le escribís a Cline), los archivos que menciones con **@**
  (por ejemplo `@/src/app.py`), el proyecto abierto y los archivos visibles. El resto del contexto que arma Cline
  (lista de archivos, instrucciones de sus herramientas) no se envía.
- Mientras trabajan los agentes, Cline muestra el progreso (plan, agentes, modelos y herramientas) como razonamiento.
- La respuesta vuelve como **entrega de la tarea** (`attempt_completion`) en modo **Act**, o como **respuesta del plan**
  (`plan_mode_respond`) en modo **Plan**; funciona con las herramientas en XML de Cline y con tool calling nativo.
- Podés seguir la conversación respondiendo en Cline: el pedido nuevo sigue en el mismo chat.

### Limitaciones

- **`orquestador`** no edita archivos ni ejecuta comandos: entrega el código en la respuesta. Para que revise código,
  mencioná los archivos con **@**. Para editar, usá `orquestador-codigo`.
- **`orquestador-codigo`**: el primer turno de cada tarea tarda más (el equipo arma su plan, de 30 s a algunos minutos);
  los siguientes, lo que tarde el modelo ejecutor. Los modelos locales (Ollama) no se usan como ejecutores: el prompt
  de Cline es demasiado largo para el contexto que entra en 12 GB de VRAM.
- Las respuestas tardan lo que tarda el orquestador (de segundos a varios minutos según los agentes y modelos).
- Un pedido a la vez por tarea: si mandás otro mientras sigue el anterior, la API responde 409.

---

## Seguridad

- Todos los puertos escuchan solo en `127.0.0.1` (`BIND_IP` en `.env`).
- Toda la configuración está en `.env` (fuera de git); `.env.default` es la plantilla sin datos.
- Cada servicio tiene su clave:

| Servicio | Qué protege | Cómo se manda |
|---|---|---|
| n8n (webhooks `orquestador`, `agente-especialista`, `estado-modelos`) | `N8N_WEBHOOK_TOKEN` | header `X-API-Key` |
| imagen-ia (`POST /generar`) | `IMAGEN_IA_API_KEY` | header `X-API-Key` (lo usa el MCP) |
| mcp-tools (`/mcp` y `/router`) | `MCP_API_KEY` | `Authorization: Bearer`, `X-API-Key` o `?key=` (n8n lo pone en la URL desde `$env`; en los logs aparece como `key=***`) |
| doc-service (`POST /documento`, `/imagen`) | `DOC_SERVICE_API_KEY` | header `X-API-Key` (las descargas `/files` quedan libres en localhost para abrir los links) |
| orquestador-web (`/api/*`) | `WEB_ACCESS_TOKEN` | la interfaz la pide al entrar y la manda en `X-API-Key` |
| orquestador-web (`/api/eventos`) | `WEB_EVENTOS_TOKEN` | header `X-API-Key` (lo usan n8n y el MCP) |
| orquestador-web (`/v1/*`, API para Cline) | `CLINE_API_KEY` | `Authorization: Bearer` (lo pone Cline como API Key) |

- n8n lee claves y URLs con `$env` (`N8N_BLOCK_ENV_ACCESS_IN_NODE=false`): no quedan escritas en los workflows.
  Contra: cualquier workflow de esta instancia puede leer esas variables.
- La API key de NVIDIA está cifrada dentro de n8n con `N8N_ENCRYPTION_KEY`.
- Ollama no tiene autenticación: escucha solo en `127.0.0.1` y en la red interna de Docker; no lo expongas fuera de la PC.
- El navegador del MCP bloquea direcciones de la red interna y de los contenedores.

---

## Mantenimiento

```bash
docker exec ollama ollama list        # modelos instalados
docker exec ollama ollama ps          # modelos cargados en la GPU
docker system df                      # espacio usado por Docker
```

**Recuperar espacio en Windows**: el disco virtual de Docker (`%LOCALAPPDATA%\Docker\wsl\disk\docker_data.vhdx`) no
se achica solo al borrar modelos o imágenes. Para devolver el espacio: `docker builder prune -f`, cerrar Docker
Desktop (`docker desktop stop` y `wsl --shutdown`) y, en PowerShell como administrador:

```powershell
Mount-VHD -Path "$env:LOCALAPPDATA\Docker\wsl\disk\docker_data.vhdx" -ReadOnly
Optimize-VHD -Path "$env:LOCALAPPDATA\Docker\wsl\disk\docker_data.vhdx" -Mode Full
Dismount-VHD -Path "$env:LOCALAPPDATA\Docker\wsl\disk\docker_data.vhdx"
```

**Si n8n da "Task request timed out"**: `docker compose restart n8n-runners`.
