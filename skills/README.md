# Skills de los agentes

Instrucciones de trabajo que los agentes leen con la herramienta `leer_skill` del servidor MCP (montadas en
`mcp-tools` como `/skills`, solo lectura). En el prompt de cada agente va solo el catálogo (id y descripción); el
contenido completo se lee cuando hace falta.

- Qué skills usa cada agente: `generador/agentes/<id>.json` → `"skills"`.
- Origen, licencia, commit, archivos y resultado de la auditoría de cada una: [fuentes.json](fuentes.json).
- Las skills de NVIDIA no están copiadas acá: van como catálogo en el prompt (de `generador/build/skills.json`) y se
  citan con su enlace a https://github.com/NVIDIA/skills.

## Fuentes

| Fuente | Licencia | Skills |
|---|---|---|
| [Trail of Bits](https://github.com/trailofbits/skills) | CC-BY-SA-4.0 | Revisión de seguridad, análisis de variantes, falsos positivos, Semgrep, cadena de suministro, pruebas basadas en propiedades, mutation testing |
| [GitHub awesome-copilot](https://github.com/github/awesome-copilot) | MIT | Security review, modelado de amenazas, hardening de GitHub Actions, DevOps, PRD, plan de pruebas, Playwright, Jest, pytest, refactor, patrones, ADR, documentación, OWASP, accesibilidad, rendimiento |
| [Anthropic](https://github.com/anthropics/skills) | Apache-2.0 | frontend-design, webapp-testing |
| [Vercel](https://github.com/vercel-labs/agent-skills) | MIT | React best practices, patrones de composición, Web Interface Guidelines |
| [obra/superpowers](https://github.com/obra/superpowers) | MIT | TDD, debugging sistemático, verificación antes de terminar, planes, code review, brainstorming |
| Propias | — | principios-solid, codigo-limpio, bootstrap-5, analisis-funcional, seguridad-contenedores-infra, calidad-iso-25010, heuristicas-ux, vision-fundamentos |

Cada carpeta conserva el archivo de licencia de su fuente. Las skills de Trail of Bits son CC-BY-SA-4.0: si se
modifican, las versiones modificadas tienen que mantener esa licencia y la atribución.

## Cómo se auditaron (31/10/2026)

1. Se clonaron los repositorios en una carpeta aparte, sin instalar ni ejecutar nada.
2. **Solo se copiaron archivos de texto** (`.md`, `.mdx`, `.txt` y licencias). Scripts, ejecutables, consultas y
   assets quedaron afuera (lista en `fuentes.json` → `excluidos_no_texto`): los agentes no ejecutan código de las skills.
3. Se buscaron automáticamente: descargas que se ejecutan (`curl | sh`), instrucciones que descargan reglas remotas,
   intentos de inyección de prompt ("ignore previous instructions"), exfiltración de secretos, credenciales,
   comandos destructivos, evasión de permisos, base64 largo y caracteres Unicode invisibles.
4. Cada hallazgo se revisó a mano. Todos eran material didáctico o de detección (ejemplos de ataques, patrones de
   secretos, la clave de ejemplo de AWS), salvo `web-design-guidelines`, que bajaba sus reglas de internet en cada
   uso: se reemplazó por una copia local revisada.
5. Se guardó el SHA-256 de cada `SKILL.md` para detectar cambios.

Además, `leer_skill` antepone un aviso de que el contenido es de referencia y no cambia las reglas de seguridad del
agente, y cada agente tiene como regla tratar todo lo que traen las herramientas como información, no como órdenes.

## Agregar o actualizar una skill

1. Bajarla a una carpeta temporal y revisarla completa (o con el mismo chequeo automático).
2. Copiar solo los archivos de texto a `skills/<id>/`, con su licencia.
3. Registrar fuente, licencia, commit y auditoría en `fuentes.json`.
4. Sumarla al `"skills"` del agente en `generador/agentes/<id>.json`, correr `python generador/build/gen.py` y
   actualizar el workflow en n8n.
