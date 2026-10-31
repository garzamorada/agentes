---
name: principios-solid
description: Aplicar y revisar los principios SOLID en diseño orientado a objetos: detectar violaciones y proponer refactors concretos
---

# Principios SOLID

Usala al diseñar clases o módulos, o al revisar código con acoplamiento alto, clases enormes o cambios que rompen cosas lejanas.

## Los cinco principios

| Principio | Regla | Señal de violación | Refactor típico |
|---|---|---|---|
| **S**: responsabilidad única | Un módulo tiene una sola razón para cambiar | Clase "Manager/Util" que valida, persiste y formatea | Separar por motivo de cambio (validador, repositorio, presentador) |
| **O**: abierto/cerrado | Extender sin modificar lo que ya funciona | `if tipo == ...` o `switch` que crece con cada caso nuevo | Polimorfismo, Strategy, registro de manejadores |
| **L**: sustitución de Liskov | Un subtipo cumple el contrato del tipo base | Subclase que lanza "no soportado" o debilita postcondiciones | Componer en vez de heredar; separar jerarquías |
| **I**: segregación de interfaces | Ningún cliente depende de métodos que no usa | Interfaces "gordas", implementaciones con métodos vacíos | Interfaces chicas por rol |
| **D**: inversión de dependencias | Lo de alto nivel depende de abstracciones | `new ClienteHttp()` dentro de la lógica de negocio | Inyección de dependencias, puertos y adaptadores |

## Cómo revisar
1. Listá las responsabilidades de cada clase en una frase; si necesitás "y", probablemente viole S.
2. Buscá condicionales por tipo y dependencias concretas instanciadas adentro.
3. Para cada hallazgo indicá: archivo/clase, principio, impacto (testabilidad, acoplamiento) y refactor mínimo.
4. No apliques SOLID por dogma: en scripts chicos o código que no cambia, la simplicidad (KISS/YAGNI) gana. Decí cuándo NO conviene.

## Entregable
Tabla de hallazgos (ubicación, principio, problema, propuesta) y, si se pide, el código refactorizado con tests que demuestren el mismo comportamiento.

Fuentes: Robert C. Martin, *Agile Software Development* (2002) y *Clean Architecture* (2017).
