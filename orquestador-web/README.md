# orquestador-web

Interfaz web local para el **orquestador multi-agente** de n8n (NVIDIA + Ollama), con registro de chats
para consultarlos y retomarlos.

- **Backend:** FastAPI + SQLite (`data/chats.db`). Hace de proxy al webhook de n8n.
- **Frontend:** React (Vite), compilado dentro de la imagen y servido por el mismo FastAPI.
- **n8n:** workflow *NVIDIA · Orquestador (webhook para la web)*, `POST /webhook/orquestador` (tiene que estar **publicado**).
  El JSON del workflow se genera en `generador/workflows/orquestador_webhook.json`.

Abrir: <http://localhost:8095>

## Levantar / actualizar

Todo se levanta con el `docker-compose.yml` de la carpeta raíz del proyecto.
Desde ahí, para reconstruir solo este servicio después de cambiar el código:

```bash
docker compose up -d --build orquestador-web
```

## Cómo funciona

1. La web manda el mensaje (y el adjunto en base64, si hay) a `POST /api/chats/{id}/mensajes`.
2. El backend guarda el mensaje del usuario y uno del asistente en estado `pendiente`, y llama al webhook
   en segundo plano con los últimos 8 mensajes del chat como `historial` (así se puede retomar una conversación).
3. La web consulta cada 2,5 s hasta que la respuesta pasa a `ok` (con los agentes/modelos usados, la duración
   y el link a la versión HTML) o a `error` (con botón **Reintentar**).
4. Si el contenedor se reinicia con pedidos en curso, quedan como error y se pueden reintentar.

Los adjuntos no se guardan: solo queda el nombre en el registro (un reintento reenvía solo el texto).

## Progreso en vivo y modelos

- **Línea de estado:** mientras se responde, muestra el último paso (se va "escribiendo"), chips con los agentes
  activos y su modelo, y las herramientas usadas. "Ver pasos" despliega el recorrido completo con tiempos; en
  respuestas terminadas queda como "Proceso (N pasos)".
- Los pasos llegan a `POST /api/eventos` desde dos lugares:
  - n8n (router de modelos del agente especialista): modelo elegido, plan, reintentos, esperas, fin y el
    razonamiento cuando el modelo lo devuelve en `<think>`.
  - El servidor MCP (`mcp-tools`): cada herramienta que usa un agente y un resumen del resultado.
  Se asocian a la respuesta pendiente del chat (el `session_id` que manda la web es el id del chat).
- **Botón "Modelos":** usados en el chat, locales (Ollama: instalados, cargados en VRAM, usos de hoy) y remotos
  (NVIDIA: estado, usos de hoy y del último minuto contra sus límites, pausas por error, agentes que los usan).
  Lo arma `GET /api/modelos` con el webhook `GET /webhook/estado-modelos` del agente en n8n y la API de Ollama
  (`OLLAMA_URL`, por defecto `http://192.168.65.254:11434`).

El razonamiento no es un stream token a token: el nodo AI Agent de n8n no lo expone. Se ve paso a paso
(modelo, plan, herramientas, resultados) y, si el modelo lo devuelve, su razonamiento al terminar cada agente.

## API

Todo `/api/*` requiere el header `X-API-Key`: `WEB_ACCESS_TOKEN` (la interfaz lo pide al entrar), salvo
`/api/eventos`, que usa `WEB_EVENTOS_TOKEN`, y `/api/health`, que es libre (solo devuelve estado y versión).
Este backend llama a n8n con `N8N_WEBHOOK_TOKEN`.

| Método | Ruta | Uso |
|---|---|---|
| GET | `/api/chats?q=texto` | Lista de chats (busca en títulos y mensajes) |
| POST | `/api/chats` | Crear chat |
| GET | `/api/chats/{id}` | Chat con sus mensajes |
| PATCH | `/api/chats/{id}` | Renombrar (`{"titulo": "..."}`) |
| DELETE | `/api/chats/{id}` | Borrar chat |
| POST | `/api/chats/{id}/mensajes` | Enviar (`{"texto": "...", "adjunto": {"base64","nombre","mime"}}`) |
| POST | `/api/mensajes/{id}/reintentar` | Reintentar una respuesta con error |
| POST | `/api/eventos` | Paso de progreso (`{chat, tipo, texto, agente, modelo, herramienta}`) |
| GET | `/api/modelos` | Modelos locales y remotos con su estado |
| GET | `/api/health` | Estado y pedidos en curso |

Webhook de n8n (se puede usar directo desde otra app local):

```json
POST http://localhost:5678/webhook/orquestador
{"mensaje": "...", "historial": [{"rol": "usuario|asistente", "texto": "..."}],
 "adjunto": {"base64": "...", "nombre": "x.pdf", "mime": "application/pdf"}}
→ {"ok": true, "respuesta": "markdown", "titulo": "...", "html_url": "...", "agentes": [...]}
```

## Desarrollo del frontend

Con Node instalado: `cd frontend && npm install && npm run dev` (Vite en :5173, la API se redirige a :8095).
