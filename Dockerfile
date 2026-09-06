FROM python:3.13-slim AS build
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        build-essential libffi-dev zlib1g-dev libpng-dev \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /src
COPY pyproject.toml README.md ./
COPY src ./src
RUN python -m venv /venv \
 && /venv/bin/pip install --no-cache-dir --upgrade pip \
 && /venv/bin/pip install --no-cache-dir .[server] \
 && /venv/bin/pip uninstall -y pip setuptools \
 && find /venv -type d -name __pycache__ -print0 | xargs -0 rm -rf

FROM python:3.13-slim
RUN apt-get update \
 && apt-get install -y --no-install-recommends libpng16-16 \
 && rm -rf /var/lib/apt/lists/*
ENV PATH=/venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TC002_HOST=0.0.0.0 \
    TC002_PORT=8008 \
    TC002_DATA_DIR=/data
COPY --from=build /venv /venv
VOLUME /data
EXPOSE 8008
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8008/api/health')"
CMD ["tc002-server"]
