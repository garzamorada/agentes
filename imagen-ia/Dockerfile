FROM python:3.12-slim
WORKDIR /app
# PyTorch con CUDA 12.8 (la GPU llega por el runtime NVIDIA de Docker Desktop; driver >= 570)
RUN pip install --no-cache-dir torch==2.10.0 --index-url https://download.pytorch.org/whl/cu128
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py ./
# Pesos de los modelos: se descargan la primera vez a este volumen
ENV HF_HOME=/modelos \
    HF_HUB_DISABLE_TELEMETRY=1 \
    DATA_DIR=/data
EXPOSE 8094
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8094"]
