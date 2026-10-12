# Build context is the repository root: the API needs context_repo/, sample_app/ and policies/.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 LAB_ROOT=/srv LAB_DATA_DIR=/data
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*

WORKDIR /srv/backend
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app
COPY backend/pyproject.toml .
COPY context_repo /srv/context_repo
COPY sample_app /srv/sample_app
COPY policies /srv/policies

RUN useradd --create-home lab && mkdir -p /data && chown -R lab:lab /data /srv
USER lab
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --retries=10 CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
