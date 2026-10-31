# Agentes

Orquestador multi-agente sobre n8n con modelos de NVIDIA (remotos) y Ollama (locales), herramientas propias por MCP,
generador de documentos y una web local con el registro de chats.

| Carpeta | Qué es | Puerto |
|---|---|---|
| `n8n/n8n_data` | Datos de n8n: workflows, credenciales (cifradas con la clave de `config`), historial | http://localhost:5678 |
| `mcp-tools` | Servidor MCP (Python) con todas las herramientas: cálculo, archivos, web (Playwright + Selenium), gráficos e imágenes | http://localhost:8092/mcp |
| `imagen-ia` | Imágenes con IA: FLUX.2 klein 4B (o SDXL-Lightning) en la GPU; comparte la GPU con Ollama | http://localhost:8094 |
| `ollama` (contenedor) | Modelos locales con la GPU NVIDIA; los modelos están en el volumen de Docker `agentes_ollama` | http://localhost:11434 |
| `doc-service` | Genera HTML, PDF, Word, Excel y MD con gráficos y diagramas | http://localhost:8090 |
| `orquestador-web` | Web local (FastAPI + React): chats, progreso en vivo, modelos | http://localhost:8095 |
| `documentos_generados` | Archivos que generan los agentes (y capturas del navegador) | `/files/...` de doc-service |
| `generador` | Script que genera los workflows de n8n (`build/gen.py`) y sus JSON (`workflows/`) | — |

## Levantar

Desde la carpeta del proyecto:

```bash
cp .env.default .env      # y completá las claves (ver abajo)
docker compose up -d --build
```

Todos los contenedores están en la red `agentes_default` y se llaman por nombre
(`n8n-container`, `mcp-tools`, `doc-service`, `orquestador-web`).
Toda la configuración (puertos, URLs, claves) está en `.env`; `.env.default` es la plantilla sin datos
que se sube a git. Para generar cada clave:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Reconstruir un solo servicio después de cambiar su código, por ejemplo la web:

```bash
docker compose up -d --build orquestador-web
```

## Ollama

Corre en el contenedor `ollama` con la GPU (requiere Docker Desktop con soporte NVIDIA). n8n y la web lo usan en
`http://ollama:11434` (credencial "Ollama account" de n8n y `OLLAMA_URL`). Los modelos están en el volumen
`agentes_ollama` (más rápido que una carpeta de Windows). Comandos útiles:

```bash
docker exec ollama ollama list
docker exec ollama ollama pull <modelo>
docker exec ollama ollama ps
```

## Seguridad

- Todos los puertos escuchan solo en `127.0.0.1` (`BIND_IP` en `.env`).
- Cada servicio tiene su clave, que vive solo en `.env`:

| Servicio | Qué protege | Cómo se manda |
|---|---|---|
| n8n (webhooks `orquestador`, `agente-especialista`, `estado-modelos`) | `N8N_WEBHOOK_TOKEN` | header `X-API-Key` |
| imagen-ia (`POST /generar`) | `IMAGEN_IA_API_KEY` | header `X-API-Key` (lo usa el MCP) |
| mcp-tools (`/mcp`) | `MCP_API_KEY` | `Authorization: Bearer`, `X-API-Key` o `?key=` (n8n lo pone en la URL desde `$env`; en los logs aparece como `key=***`) |
| doc-service (`POST /documento`) | `DOC_SERVICE_API_KEY` | header `X-API-Key` (las descargas `/files` quedan libres en localhost para abrir los links) |
| orquestador-web (`/api/*`) | `WEB_ACCESS_TOKEN` | la interfaz la pide al entrar y la manda en `X-API-Key` |
| orquestador-web (`/api/eventos`) | `WEB_EVENTOS_TOKEN` | header `X-API-Key` (lo usan n8n y el MCP) |

- n8n lee claves y URLs con `$env` (`N8N_BLOCK_ENV_ACCESS_IN_NODE=false`): no quedan escritas en los workflows.
  Contra: cualquier workflow de esta instancia puede leer esas variables.
- La API key de NVIDIA está cifrada dentro de n8n (credencial "OpenAI account") con `N8N_ENCRYPTION_KEY`.
- Ollama no tiene autenticación: escucha solo en `127.0.0.1` y en la red interna de Docker; no lo expongas fuera de la PC.

## Workflows de n8n

| Workflow | Para qué |
|---|---|
| NVIDIA · Agente especialista (router de LLM) | Elige el modelo (NVIDIA/Ollama), usa las herramientas MCP, memoria por chat, avisa el progreso a la web. Webhooks `agente-especialista` y `estado-modelos` |
| NVIDIA · Orquestador (webhook para la web) | `POST /webhook/orquestador`: planifica, reparte agentes en paralelo, sintetiza y verifica que se cumpla todo |
| NVIDIA · Orquestador multi-agente | El mismo orquestador para el chat de n8n (Open chat) |

Para cambiarlos: editar `generador/build/*` y correr `python generador/build/gen.py`; los JSON quedan en
`generador/workflows/` y se importan pegándolos en n8n (después de pegar el agente, revisar que el selector de
modelo, la memoria y el nodo MCP sigan conectados al nodo del agente y publicar).

## Imágenes con IA (`imagen-ia`)

- Modelo por defecto: **FLUX.2 [klein] 4B** de Black Forest Labs (Apache 2.0), con el text encoder Qwen3-4B en 4 bits (NF4)
  y el transformer en bf16 para que entre en los 12 GB de la RTX 3060. Pesos (~16 GB) en el volumen `agentes_imagen_modelos`.
- Velocidad en la RTX 3060: ~17 s por imagen de 1024×1024 con el modelo cargado; cargarlo desde el disco tarda ~1,5 min.
  Varias imágenes se generan de a una (juntas desbordan la VRAM).
- Escribe bien textos cortos dentro de la imagen (carteles, títulos de pocas palabras).
- Alternativa más liviana y rápida (~4 s, peor calidad y sin texto): `IMAGEN_MODELO=sdxl-lightning` en `.env`.
  Si la VRAM no alcanza: `FLUX_TRANSFORMER=nf4`.
- Comparte la GPU con Ollama: antes de cargar le pide que libere sus modelos y, tras 3 minutos sin uso, libera la VRAM.
- Los modelos "Downloadable" de build.nvidia.com (contenedores NIM) piden GPUs RTX 40/50 o superiores: no corren en la RTX 3060;
  FLUX.2 klein se usa con sus pesos abiertos de Hugging Face y `diffusers`.
