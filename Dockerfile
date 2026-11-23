# API de la Base de Empresas para Cloud Run. Se construye desde la raíz del repo
# (incluye db/ para poder correr las migraciones como Cloud Run job con la misma imagen).
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8080
WORKDIR /srv
COPY api/requirements.txt api/requirements.txt
RUN pip install --no-cache-dir -r api/requirements.txt
COPY api/app api/app
COPY db db
WORKDIR /srv/api
# WORKERS: 2 en la API de la web; 1 en el servicio de tareas (empresas-tareas, D52), que corre las cargas pesadas
ENV WORKERS=2
CMD exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --workers ${WORKERS} --proxy-headers
