# ============================================================
# ATLAS OS - Dockerfile (API / Workers)
# Base: Python 3.11 slim
# ============================================================

FROM python:3.11-slim

LABEL maintainer="Atlas OS"
LABEL description="Atlas OS - Autonomous Media Operating System"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /atlas

# 1. Instala os pacotes do sistema
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        curl \
        ffmpeg \
        imagemagick \
        fonts-liberation \
        fonts-dejavu \
    && rm -rf /var/lib/apt/lists/*

# 2. HACK DEFINITIVO DO IMAGEMAGICK
# Entra no arquivo original do sistema e troca TODAS as restrições de "none" para "read|write"
RUN if [ -f /etc/ImageMagick-6/policy.xml ]; then \
        sed -i 's/rights="none"/rights="read|write"/g' /etc/ImageMagick-6/policy.xml; \
    fi

COPY requirements.txt .
RUN pip install --upgrade pip \
    && pip install -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
