FROM python:3.12-alpine

RUN apk add --no-cache dumb-init && \
    pip install --no-cache-dir httpx structlog

WORKDIR /app
COPY src/ /app/src/

ENV PYTHONUNBUFFERED=1

ENTRYPOINT ["dumb-init", "--"]
CMD ["python", "-m", "src.watchdog"]
