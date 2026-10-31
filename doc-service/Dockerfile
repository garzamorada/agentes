FROM python:3.12-slim

# Librerías de sistema: WeasyPrint (PDF), Graphviz (diagramas) y una fuente con acentos
RUN apt-get update \
 && apt-get install -y --no-install-recommends libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 fonts-dejavu-core graphviz \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py diagramas.py ./

ENV DATA_DIR=/data \
    PUBLIC_URL=http://localhost:8090 \
    MPLCONFIGDIR=/tmp/mpl
EXPOSE 8090
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8090"]
