# Debian 12: la versión de Playwright usada no soporta todavía Debian 13
FROM python:3.12-slim-bookworm
WORKDIR /app
COPY requirements.txt ./
# Chromium de Playwright con sus dependencias del sistema y fuentes
RUN pip install --no-cache-dir -r requirements.txt \
 && playwright install --with-deps chromium \
 && rm -rf /var/lib/apt/lists/*
# Segundo motor (Selenium): Chromium y chromedriver de Debian, con versiones que coinciden entre sí
RUN apt-get update \
 && apt-get install -y --no-install-recommends chromium chromium-driver \
 && rm -rf /var/lib/apt/lists/*
ENV CHROMIUM_BIN=/usr/bin/chromium \
    CHROMEDRIVER_BIN=/usr/bin/chromedriver \
    SE_AVOID_STATS=true
COPY *.py reglas.md ./
# URLs y claves llegan por variables de entorno (docker-compose.yml + .env)
ENV DATA_DIR=/data
EXPOSE 8092
CMD ["python", "server.py"]
