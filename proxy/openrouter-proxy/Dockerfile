FROM python:3.12-slim

RUN pip install uv --quiet

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen

COPY proxy.py .

EXPOSE 4001

CMD ["uv", "run", "python", "proxy.py"]
