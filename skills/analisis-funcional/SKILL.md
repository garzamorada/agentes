---
name: analisis-funcional
description: Relevar y documentar requerimientos: actores, casos de uso, historias de usuario con criterios de aceptación, reglas de negocio y trazabilidad
---

# Análisis funcional

Usala para convertir un pedido o una idea en requerimientos claros y verificables, o para revisar si un sistema cumple lo especificado.

## Proceso
1. **Contexto**: objetivo de negocio, alcance (qué entra y qué no), supuestos y restricciones.
2. **Actores** y sistemas externos.
3. **Requerimientos funcionales** numerados (RF-01...), cada uno verificable; **no funcionales** (RNF-01...) con métrica (ver la skill calidad-iso-25010).
4. **Casos de uso** (flujo principal, alternativos y excepciones) o **historias de usuario**: "Como <rol> quiero <acción> para <beneficio>".
5. **Criterios de aceptación** en Gherkin: `Dado ... Cuando ... Entonces ...`, con casos borde y errores.
6. **Reglas de negocio** separadas de la interfaz (RN-01...).
7. **Requerimientos de seguridad** desde el inicio: autenticación, autorización por rol, datos sensibles, auditoría, retención.
8. **Matriz de trazabilidad**: requerimiento → caso de uso → prueba.
9. **Preguntas abiertas**: lo ambiguo se lista, no se inventa.

## Calidad de un requerimiento
Necesario, sin ambigüedad ("rápido" → "responde en menos de 2 s en el p95"), verificable, factible y priorizado (MoSCoW).

Fuentes: ISO/IEC/IEEE 29148 (ingeniería de requerimientos); Mike Cohn, *User Stories Applied*.
