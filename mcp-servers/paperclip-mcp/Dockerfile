FROM python:3.12-slim

# Install direct from git so README.md is present during hatchling metadata build
RUN pip install --no-cache-dir \
    "git+https://github.com/Wizarck/paperclip-mcp.git@master"

EXPOSE 9011
CMD ["paperclip-mcp", "--host", "0.0.0.0", "--port", "9011"]
