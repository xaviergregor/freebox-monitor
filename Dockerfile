FROM python:3.11-slim

LABEL maintainer="Xavier Gregor"
LABEL description="Freebox Monitoring - API + Web Interface"

WORKDIR /app

# Installer les dépendances système
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copier les fichiers de requirements
COPY requirements.txt .

# Installer les dépendances Python
RUN pip install --no-cache-dir -r requirements.txt

# Copier le script Python standalone (HTML intégré)
COPY freebox_monitor_standalone.py /app/freebox_monitor.py

# Créer le dossier pour le token
RUN mkdir -p /app/data

# Exposer le port
EXPOSE 5000

# Variables d'environnement
ENV PYTHONUNBUFFERED=1
ENV FLASK_ENV=production

# Healthcheck
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:5000/api/info || exit 1

# Lancer l'application
CMD ["python", "freebox_monitor.py"]
