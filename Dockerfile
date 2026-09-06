FROM python:3.13-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .[server]
ENV TC002_HOST=0.0.0.0 TC002_PORT=8008 TC002_DATA_DIR=/data
VOLUME /data
EXPOSE 8008
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8008/api/health')"
CMD ["tc002-server"]
