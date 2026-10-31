# 1) Build del frontend React
FROM node:22-alpine AS web
WORKDIR /web
COPY frontend/package.json ./
RUN npm install --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# 2) Backend FastAPI que sirve la API y el build
FROM python:3.12-slim
WORKDIR /app
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/app.py ./
COPY --from=web /web/dist ./static
# URLs y claves llegan por variables de entorno (docker-compose.yml + .env)
ENV DB_PATH=/data/chats.db
VOLUME /data
EXPOSE 8095
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8095"]
