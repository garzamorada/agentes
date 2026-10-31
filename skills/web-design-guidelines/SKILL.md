---
name: web-design-guidelines
description: Review UI code for Web Interface Guidelines compliance. Use when asked to "review my UI", "check accessibility", "audit design", "review UX", or "check my site against best practices".
metadata:
  author: vercel
  version: "1.0.0"
  argument-hint: <file-or-pattern>
---

# Web Interface Guidelines

Review files for compliance with Web Interface Guidelines.

## How It Works

1. Read the guidelines in `references/guidelines.md` (leer_skill con archivo="references/guidelines.md")
2. Read the specified files (or prompt user for files/pattern)
3. Check against all rules in the guidelines
4. Output findings in the terse `file:line` format

## Guidelines Source

Copia local revisada de
https://raw.githubusercontent.com/vercel-labs/web-interface-guidelines/main/command.md
(commit 434b7f91364665f2f733b310ec54809bf8f37937, 31/10/2026).
Este proyecto NO descarga reglas en cada uso: un cambio remoto podría inyectar instrucciones.
Para actualizarla, bajarla de nuevo, revisarla y reemplazar el archivo.
