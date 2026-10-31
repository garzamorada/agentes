---
name: seguridad-contenedores-infra
description: Revisar la seguridad de Docker, Compose, Kubernetes y servidores: imágenes, secretos, red, permisos y exposición
---

# Seguridad en contenedores e infraestructura

Usala al revisar Dockerfiles, docker-compose, manifiestos de Kubernetes o la configuración de servidores.

## Checklist
**Imágenes**
- Base mínima y con versión fija (idealmente por digest); sin `latest` en producción.
- Usuario no root (`USER`), sin herramientas de compilación en la imagen final (multi-stage).
- Escaneo de vulnerabilidades (Trivy, Grype, Docker Scout) y SBOM.

**Secretos**
- Nunca en el Dockerfile, en la imagen ni en el repo: variables desde un `.env` fuera de git, Docker/K8s secrets o un gestor (Vault).
- `.dockerignore` que excluya `.env`, `.git`, llaves y credenciales.

**Red y exposición**
- Publicar puertos solo en `127.0.0.1` si el uso es local; nada administrativo expuesto a internet.
- Redes separadas por función; TLS para el tráfico entre hosts.
- Autenticación en cada servicio (API keys o tokens) aunque esté en una red interna.

**Ejecución**
- `read_only: true`, `cap_drop: [ALL]`, `no-new-privileges`, límites de memoria y CPU.
- No montar `/var/run/docker.sock` salvo necesidad justificada; nada de `privileged`.
- Kubernetes: `securityContext` (runAsNonRoot, allowPrivilegeEscalation: false), NetworkPolicies, RBAC mínimo.

**Operación**
- Logs sin secretos (enmascarar claves en URLs), actualizaciones regulares, backups probados.

## Entregable
Hallazgos por severidad (crítica, alta, media, baja) con archivo y línea, el riesgo concreto y la corrección (fragmento de configuración).

Fuentes: CIS Docker Benchmark; OWASP Docker Security Cheat Sheet; NSA/CISA Kubernetes Hardening Guide.
