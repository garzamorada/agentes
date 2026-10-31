---
name: calidad-iso-25010
description: Definir y evaluar requisitos no funcionales con el modelo ISO/IEC 25010: rendimiento, seguridad, usabilidad, confiabilidad, mantenibilidad, portabilidad
---

# Calidad no funcional (ISO/IEC 25010)

Usala para definir requisitos no funcionales medibles o para planificar y evaluar pruebas no funcionales.

## Características y cómo medirlas
| Característica | Ejemplo de criterio medible | Cómo se prueba |
|---|---|---|
| Eficiencia de desempeño | p95 < 500 ms con 200 usuarios concurrentes | k6, JMeter, Locust; Lighthouse para web |
| Compatibilidad | Funciona en Chrome, Firefox, Safari y Edge actuales | Matriz de navegadores, Playwright multi-browser |
| Usabilidad y accesibilidad | WCAG 2.2 AA sin errores críticos | axe, Lighthouse, prueba con teclado y lector de pantalla |
| Confiabilidad | Disponibilidad 99,5 % mensual; recuperación < 15 min | Pruebas de caos, failover, restauración de backups |
| Seguridad | Sin vulnerabilidades altas abiertas | SAST (Semgrep), DAST (OWASP ZAP), dependencias (pip-audit, npm audit) |
| Mantenibilidad | Cobertura ≥ 80 % en el dominio; complejidad ciclomática < 10 | Cobertura, linters, análisis estático |
| Portabilidad | Despliegue reproducible con un comando | Contenedores, IaC, prueba en un entorno limpio |

## Proceso
1. Traducir adjetivos ("rápido", "seguro") en métricas con umbral y condiciones.
2. Priorizar según el riesgo del negocio.
3. Definir herramienta, entorno y datos de prueba para cada criterio.
4. Informar el resultado con evidencia (números, capturas, reportes) y la brecha contra el umbral.

Fuente: ISO/IEC 25010:2023, modelo de calidad de producto.
