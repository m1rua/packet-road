# syntax=docker/dockerfile:1
FROM python:3.12-slim-bookworm@sha256:935c3c5b12357a7e10caa9c1e6ca5692344d97cf229832ef584be2cec9fc03df
ARG APP_REVISION=development
LABEL org.opencontainers.image.source="https://github.com/m1rua/packet-road" \
      org.opencontainers.image.revision=$APP_REVISION \
      org.opencontainers.image.version="0.2.0"
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 APP_REVISION=$APP_REVISION
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends iproute2 traceroute \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt pyproject.toml ./
COPY src ./src
# Optional combined CA bundle for builds in a TLS-inspecting development environment.
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then export PIP_CERT=/run/secrets/proxy_ca; fi; \
    pip install --no-cache-dir .
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/ready',timeout=2)"]
CMD ["uvicorn", "packet_road.api:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-access-log"]
