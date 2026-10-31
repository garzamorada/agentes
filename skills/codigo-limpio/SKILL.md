---
name: codigo-limpio
description: Escribir y revisar código limpio: nombres, funciones, manejo de errores, duplicación, comentarios y tests legibles
---

# Código limpio

Usala al escribir código nuevo o revisar uno existente para que sea fácil de leer, cambiar y probar.

## Reglas
- **Nombres**: revelan intención (`dias_desde_ultima_compra`, no `d`); sin abreviaturas crípticas; verbos para funciones, sustantivos para datos.
- **Funciones**: cortas, una sola cosa, un nivel de abstracción; pocos parámetros (agrupá en un objeto si son más de 3); sin flags booleanos que cambien el comportamiento.
- **Efectos secundarios**: explícitos; separá consultas de comandos.
- **Errores**: excepciones con contexto en vez de códigos de retorno; nunca tragarlas en silencio; validá en los bordes del sistema.
- **Duplicación (DRY)**: extraé lógica repetida, pero no acoples cosas que solo se parecen por casualidad.
- **Comentarios**: explican el *por qué*, no el *qué*; borrá el código comentado.
- **Formato**: consistente con el estilo del proyecto y su linter (ruff, eslint, prettier).
- **Tests**: legibles (Arrange/Act/Assert), un concepto por test, nombres que describen el comportamiento.
- **Regla del boy scout**: dejá el código un poco mejor de lo que lo encontraste, sin cambios gratuitos fuera del alcance.

## Revisión
Para cada hallazgo: ubicación, regla, por qué importa y la versión corregida. Priorizá lo que afecta corrección y mantenimiento sobre lo cosmético.

Fuentes: Robert C. Martin, *Clean Code* (2008); Martin Fowler, *Refactoring* (2.ª ed., 2018).
