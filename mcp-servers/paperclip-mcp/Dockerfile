FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
    "git+https://github.com/Wizarck/paperclip-mcp.git@master"

EXPOSE 9011
CMD ["paperclip-mcp", "--host", "0.0.0.0", "--port", "9011"]
