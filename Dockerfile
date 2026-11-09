FROM python:3.12-slim AS builder 
WORKDIR /build
RUN python -m venv /opt/venv
COPY requirements.txt .
RUN /opt/venv/bin/python -m pip install --no-cache-dir -r requirements.txt

FROM  python:3.12-slim AS runtime
ENV PATH="/opt/venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY get_info.py .
ENTRYPOINT ["python", "get_info.py"]
