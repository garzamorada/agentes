# generador

Genera los workflows de n8n del proyecto como JSON (no hace falta editarlos a mano en n8n).

```bash
python build/gen.py          # escribe workflows/agente_especialista.json, orquestador.json y orquestador_webhook.json
```

- `build/gen.py`: arma los workflows (nodos, conexiones, prompts). Las reglas de herramientas las toma de
  `../mcp-tools/reglas.md`, así el MCP y los agentes usan el mismo texto.
- `build/config_modelos.js`: modelos y límites del router (NVIDIA + Ollama) por agente.
- `build/*.js`: código de los nodos Code (router, registro de éxito/fallo, verificación, estado de modelos).
- `build/ids.json`: IDs de los workflows y credenciales de **tu** instancia de n8n (no son secretos; en otra
  instalación hay que cambiarlos por los propios).
- `build/skills.json`: catálogo de skills de NVIDIA por categoría; se regenera con
  `python build/extract.py <catalogo.md>`.
- `build/serve.py`: servidor local para importar los JSON en n8n desde el navegador (`python build/serve.py workflows`).

Las URLs y claves no están en los workflows: n8n las lee de su entorno (`$env`, ver `../.env.default`).

Al importar el agente en n8n (pegar el JSON sobre el lienzo), revisar que **Elegir proveedor**, **Simple Memory**
y **Herramientas (MCP)** sigan conectados al nodo **Agente especialista** y publicar.
