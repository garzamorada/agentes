# Agentes

Orquestador multi-agente sobre n8n con modelos de NVIDIA (remotos) y Ollama (locales), herramientas propias por MCP,
generador de documentos y una web local con el registro de chats.

| Carpeta | Qué es | Puerto |
|---|---|---|
| `n8n/n8n_data` | Datos de n8n: workflows, credenciales (cifradas con la clave de `config`), historial | http://localhost:5678 |
| `mcp-tools` | Servidor MCP (Python) con todas las herramientas de los agentes + navegador Chromium | http://localhost:8092/mcp |
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

Corre fuera de Docker (programa de Windows); n8n lo usa en `http://192.168.65.254:11434`
(la IP del host vista desde Docker, IPv4; se configura en `OLLAMA_URL`). Los modelos están en `%USERPROFILE%\.ollama\models`.

## Seguridad

- Todos los puertos escuchan solo en `127.0.0.1` (`BIND_IP` en `.env`).
- Cada servicio tiene su clave, que vive solo en `.env`:

| Servicio | Qué protege | Cómo se manda |
|---|---|---|
| n8n (webhooks `orquestador`, `agente-especialista`, `estado-modelos`) | `N8N_WEBHOOK_TOKEN` | header `X-API-Key` |
| mcp-tools (`/mcp`) | `MCP_API_KEY` | `Authorization: Bearer`, `X-API-Key` o `?key=` (n8n lo pone en la URL desde `$env`; en los logs aparece como `key=***`) |
| doc-service (`POST /documento`) | `DOC_SERVICE_API_KEY` | header `X-API-Key` (las descargas `/files` quedan libres en localhost para abrir los links) |
| orquestador-web (`/api/*`) | `WEB_ACCESS_TOKEN` | la interfaz la pide al entrar y la manda en `X-API-Key` |
| orquestador-web (`/api/eventos`) | `WEB_EVENTOS_TOKEN` | header `X-API-Key` (lo usan n8n y el MCP) |

- n8n lee claves y URLs con `$env` (`N8N_BLOCK_ENV_ACCESS_IN_NODE=false`): no quedan escritas en los workflows.
  Contra: cualquier workflow de esta instancia puede leer esas variables.
- La API key de NVIDIA está cifrada dentro de n8n (credencial "OpenAI account") con `N8N_ENCRYPTION_KEY`.
- Ollama no tiene autenticación: si lo exponés fuera de la PC, protegelo aparte.

## Workflows de n8n

| Workflow | Para qué |
|---|---|
| NVIDIA · Agente especialista (router de LLM) | Elige el modelo (NVIDIA/Ollama), usa las herramientas MCP, memoria por chat, avisa el progreso a la web. Webhooks `agente-especialista` y `estado-modelos` |
| NVIDIA · Orquestador (webhook para la web) | `POST /webhook/orquestador`: planifica, reparte agentes en paralelo, sintetiza y verifica que se cumpla todo |
| NVIDIA · Orquestador multi-agente | El mismo orquestador para el chat de n8n (Open chat) |

Para cambiarlos: editar `generador/build/*` y correr `python generador/build/gen.py`; los JSON quedan en
`generador/workflows/` y se importan pegándolos en n8n (después de pegar el agente, revisar que el selector de
modelo, la memoria y el nodo MCP sigan conectados al nodo del agente y publicar).
