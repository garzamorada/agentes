# doc-service

Generador de documentos para los agentes de n8n: recibe Markdown + gráficos y crea
HTML navegable, PDF, DOCX, XLSX (con gráficos nativos de Excel) y MD.

- Lo usan los workflows **Herramienta · Generar documento** (herramienta `generar_documento` de los agentes)
  y **NVIDIA · Orquestador multi-agente** (página HTML de cada respuesta).
- Archivos generados: `../documentos_generados`, descargables en `http://localhost:8090/files/...`

## Reconstruir y levantar

Todo se levanta con el `docker-compose.yml` de la carpeta raíz del proyecto.
Desde ahí, para reconstruir solo este servicio después de cambiar el código:

```bash
docker compose up -d --build doc-service
```

## API

`POST /documento` y `POST /imagen` requieren el header `X-API-Key: <DOC_SERVICE_API_KEY>` (del `.env`). `GET /files/...` y `/health` son libres.

`POST /imagen` → un gráfico o diagrama suelto en PNG/SVG: `{"grafico": {...}, "formatos": "png,svg", "nombre": "..."}`.
Tipos de gráfico (también en `graficos_json` de `/documento`): `barras`, `barras_horizontales`, `apiladas`, `linea`, `area`,
`torta`, `dona`, `dispersion` (etiquetas = valores X), `histograma` (solo `valores`) y `mapa_calor` (cada serie es una fila).
Opciones: `eje_x`, `eje_y`, `unidad`, `mostrar_valores`, `colores`. En Excel, dispersión, histograma y mapa de calor van como imagen.

| Campo | Descripción |
|---|---|
| `titulo` | Título del documento |
| `contenido_md` | Markdown (títulos, listas, tablas). `[[grafico:N]]` ubica el gráfico N |
| `formatos` | `"html,pdf,docx,xlsx,md"` (lista o texto separado por comas) |
| `graficos_json` | `[{"tipo":"bar|line|pie","titulo":"...","etiquetas":[...],"series":[{"nombre":"...","valores":[...]}]}]` |
| `nombre` | Opcional, nombre base de los archivos |

Si el JSON de gráficos viene roto lo intenta reparar; si no puede y el texto tiene `[[grafico:N]]`,
arma el gráfico con la primera tabla numérica del Markdown.

`GET /health` → `{"ok": true}`

## Diagramas (sin Mermaid ni árboles ASCII)

Los documentos nunca muestran código Mermaid ni árboles tipo consola. `diagramas.py` los dibuja con Graphviz:

- **Pedido explícito** en `graficos_json`:
  `{"tipo":"diagrama","titulo":"...","direccion":"TB|LR","nodos":[{"id":"a","texto":"Inicio","forma":"circulo"}],"flechas":[{"de":"a","a":"b","texto":"","estilo":"punteada"}]}`
  Formas: recuadro, circulo, globo, elipse, rombo, nota, cilindro, hexagono.
- **Conversión automática**: bloques ```` ```mermaid ```` (flowchart/graph, sequenceDiagram, mindmap) y árboles `├── └──` se reemplazan por diagramas.
- **Completado automático**: una sección "Diagrama / Flujo / Proceso" vacía se dibuja con los pasos numerados del texto; una sección
  "Estructura / Carpetas" con una lista de rutas suma un árbol visual.
- Diagramas horizontales largos pasan a vertical para que se lean en A4. En Excel van como imagen en su propia hoja.
