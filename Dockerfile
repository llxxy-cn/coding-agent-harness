FROM python:3.12-slim AS build

WORKDIR /build

COPY pyproject.toml README.md MANIFEST.in ./
COPY src ./src

RUN python -m pip wheel --no-cache-dir --wheel-dir /wheels ".[dev]"


FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TMPDIR=/tmp

RUN apt-get update \
    && apt-get install --no-install-recommends -y git \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 cah \
    && useradd --uid 10001 --gid cah --create-home --home-dir /app --shell /usr/sbin/nologin cah \
    && mkdir -p /app /tmp \
    && chmod 1777 /tmp

COPY --from=build /wheels /wheels
RUN python -m pip install --no-cache-dir --no-index --find-links=/wheels coding-agent-harness pytest \
    && rm -rf /wheels

WORKDIR /app
EXPOSE 8000
USER 10001:10001

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; response = urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2); assert response.status == 200 and response.read() == b'ok'"]

ENTRYPOINT ["coding-agent-harness", "web"]
