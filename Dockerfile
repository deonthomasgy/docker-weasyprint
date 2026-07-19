FROM python:3.12-slim-bookworm AS builder

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        gcc \
        libffi-dev \
        libxml2-dev \
        libxslt1-dev \
        zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY requirements.txt .
RUN pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt


FROM python:3.12-slim-bookworm AS weasyprint-base

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        fonts-font-awesome \
        libcairo2 \
        libgdk-pixbuf-2.0-0 \
        libpango-1.0-0 \
        libpangocairo-1.0-0 \
        libpangoft2-1.0-0 \
        shared-mime-info \
    && rm -rf /var/lib/apt/lists/*


FROM weasyprint-base AS xlsx-base

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libreoffice-calc-nogui \
        unoconv \
    && rm -rf /var/lib/apt/lists/*


FROM weasyprint-base AS pdf

WORKDIR /usr/src/app

COPY requirements.txt ./
COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir --no-index --find-links=/wheels -r requirements.txt \
    && rm -rf /wheels

COPY wsgi.py ./

EXPOSE 5001

# Single sync worker keeps idle RSS low (~55MiB). Parallelism comes from running
# multiple containers per host. No --max-requests so bulk /zip is never interrupted.
# Hosts restart these containers nightly to bound sticky Cairo RSS.
ENV WEB_CONCURRENCY=1
CMD gunicorn --bind 0.0.0.0:5001 --worker-class sync --workers ${WEB_CONCURRENCY} wsgi:app


FROM xlsx-base AS xlsx

WORKDIR /usr/src/app

COPY requirements.txt ./
COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir --no-index --find-links=/wheels -r requirements.txt \
    && rm -rf /wheels

COPY wsgi.py ./

EXPOSE 5001

# Single sync worker keeps idle RSS low (~55MiB). Parallelism comes from running
# multiple containers per host. No --max-requests so bulk /zip is never interrupted.
# Hosts restart these containers nightly to bound sticky Cairo RSS.
ENV WEB_CONCURRENCY=1
CMD gunicorn --bind 0.0.0.0:5001 --worker-class sync --workers ${WEB_CONCURRENCY} wsgi:app
