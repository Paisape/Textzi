FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
# Runs as a non-root user rather than the image's default root -- if a dependency vulnerability
# ever led to arbitrary file write/RCE, this removes root-in-container as an extra blast-radius
# layer. /app/uploads is where uploaded files/local archives are written (see config.py's
# uploads_dir and the uploads_data volume), so it needs to be owned by that user, not just /app.
# gosu lets docker-entrypoint.sh start as root (needed to fix the existing uploads_data volume's
# ownership -- see that script's own comment for why) and then drop to appuser before the real
# process runs, without wrapping it in a shell that would swallow signals.
RUN apt-get update && apt-get install -y --no-install-recommends gosu && rm -rf /var/lib/apt/lists/*
RUN useradd --create-home --uid 1000 appuser && mkdir -p /app/uploads && chown -R appuser:appuser /app
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh
EXPOSE 8000
ENTRYPOINT ["docker-entrypoint.sh"]
# --no-access-log: uvicorn's default access log prints the full request line, including query
# strings -- a real leak for GET /v1/sms/send-url, whose api_key travels as a query param. The
# app's own DB-backed ApiLog (main.py) already covers legitimate request auditing without ever
# storing the query string, so this loses no real visibility.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
