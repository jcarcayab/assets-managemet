# Runtime image for the trading-swing host. The React app is built on the developer machine
# (frontend/dist) so the small server never runs a Node build; only Python deps install here.
FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app/backend

COPY backend/requirements.txt ./
RUN pip install -r requirements.txt

COPY backend/ ./
COPY frontend/dist /app/frontend/dist

# uid 1000 = the host's ubuntu user, so the bind-mounted ./data stays writable from both sides.
RUN DEBUG=1 python manage.py collectstatic --noinput \
    && useradd --uid 1000 --create-home app \
    && mkdir -p /data && chown -R app /app /data
USER app

EXPOSE 8000
CMD ["sh", "-c", "python manage.py migrate --noinput && exec gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 1 --threads 4 --worker-class gthread --timeout 120 --access-logfile -"]
