# mcp-tools

Servidor **MCP** propio (Python, `mcp` FastMCP, Streamable HTTP) con **todas** las herramientas de los agentes de n8n.
Reemplaza a los nodos de código de n8n (calculadora, fecha, unidades, tablas), al sub-workflow "Leer archivo o URL",
al de "Generar documento" y al navegador web.

- Endpoint MCP: `http://mcp-tools:8092/mcp` (desde n8n) · `http://localhost:8092/mcp` (desde esta PC)
- Requiere `MCP_API_KEY` (del `.env`): `Authorization: Bearer <clave>`, header `X-API-Key` o `?key=<clave>`
- Salud: `GET /health` · Reglas de uso: `GET /reglas`

## Herramientas

| Herramienta | Qué hace |
|---|---|
| `calculadora` | Cuentas exactas (AST seguro): `0.15*2340`, `15% de 2340`, `sqrt()`, `round()`… |
| `fecha_hora` | Fecha y hora actual (Argentina por defecto) |
| `convertir_unidades` | Longitud, masa, volumen, área, tiempo, datos, velocidad, energía, presión, temperatura |
| `tabla` | JSON → tabla Markdown o CSV |
| `leer_url` | Archivo por URL → texto (PDF, Word, Excel xlsx/xls, CSV, JSON, TXT) |
| `leer_archivo` | Archivo en base64 → texto (adjuntos del chat; lo usa el orquestador) |
| `generar_documento` | HTML, PDF, Word, Excel y MD con gráficos y diagramas (llama a **doc-service**) |
| `buscar_web` | Búsqueda web (DuckDuckGo, respaldo Bing) |
| `navegador` | Chromium real: abrir, leer, clic, escribir, **completar** (formularios de varios campos), **extraer** (BeautifulSoup: tablas, listas, enlaces, títulos, campos, metadatos o selector CSS), tecla, desplazar, captura, atrás, cerrar. Dos motores: `playwright` (por defecto) y `selenium` (respaldo) |
| `crear_grafico` | Gráfico PNG/SVG: barras, horizontales, apiladas, línea, área, torta, dona, dispersión, histograma, mapa de calor (lo dibuja doc-service) |
| `crear_diagrama` | Diagramas visuales (flujos, organigramas, arquitecturas) en PNG/SVG |
| `generar_imagen` | Imágenes nuevas con IA (fotos, ilustraciones, logos) vía el servicio `imagen-ia` |
| `como_llegar` | Rutas de Google Maps: colectivo/subte/tren, auto, a pie o bici, con el detalle de la mejor opción |
| `crear_imagen` | Portadas, banners y placas con texto (Pillow, sin IA) |
| `editar_imagen` | Redimensionar, recortar, texto, collage, convertir, rotar, grises, borde |

## Reglas de uso

`reglas.md` es la **única fuente**: el servidor la publica como `instructions` del MCP y el generador de los
workflows de n8n la copia en el prompt de los agentes. Si la cambiás, reconstruí la imagen y regenerá los workflows.

## Parámetros de la URL

- `?sesion=<id>`: pestaña del navegador (n8n pone el id de ejecución: cada agente tiene la suya y la conserva entre llamadas).
- `&perfil=`: qué herramientas se listan.
  - `todas` (por defecto): modelos de NVIDIA.
  - `basicas`: calculadora, fecha_hora, convertir_unidades, tabla (modelos locales de Ollama, que se confunden con muchas).
  - `planificador`: solo fecha_hora (orquestador y síntesis, para que planifiquen y no resuelvan la tarea).
  - `adjuntos`: solo leer_archivo.

## Seguridad del navegador, leer_url y editar_imagen

- Solo `http`/`https` y sitios públicos: bloquea localhost, IPs privadas y los contenedores de la red Docker
  (también en redirecciones y en cada recurso que carga la página; en Selenium vía Chrome DevTools `Network.setBlockedURLs`).
- No escribe (ni con `escribir` ni con `completar`) en campos de contraseña, tarjeta, CBU/CVU, tokens, etc. No descarga archivos. No resuelve CAPTCHAs.
- Las capturas se guardan en `documentos_generados/web-.../` y las sirve doc-service (`http://localhost:8090/files/...`).

## Levantar / actualizar

Todo se levanta con el `docker-compose.yml` de la carpeta raíz del proyecto.
Desde ahí, para reconstruir solo este servicio después de cambiar el código:

```bash
docker compose up -d --build mcp-tools
```

## Usarlo desde otro cliente MCP (Claude Desktop, Cursor, etc.)

Agregar un servidor MCP de tipo HTTP con la URL `http://localhost:8092/mcp` y el header
`Authorization: Bearer <MCP_API_KEY>`.
