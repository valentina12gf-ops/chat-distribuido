FROM python:3.12-slim
WORKDIR /srv
ENV PYTHONUNBUFFERED=1
# Solo usa la biblioteca estándar de Python: no hay requirements ni instalación de paquetes.
COPY app ./app
CMD ["python", "-m", "app.main"]
