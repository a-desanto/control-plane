FROM python:3.12-slim

# System deps:
#   poppler-utils  — pdf2image uses pdftoppm
#   libgl1         — OpenCV runtime
#   libglib2.0-0   — OpenCV/gthread runtime
#   libgomp1       — PaddlePaddle OpenMP
RUN apt-get update && apt-get install -y --no-install-recommends \
    poppler-utils \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .

# PaddleOCR resolves model dirs via HOME (~/.paddleocr/whl/...).
# Setting HOME here keeps models inside the volume mount at /app/models.
ENV HOME=/app/models \
    PADDLE_HOME=/app/models

EXPOSE 4006

HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=3 \
  CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:4006/health')" || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "4006"]
