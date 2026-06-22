FROM docker.m.daocloud.io/library/python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        bash \
        bubblewrap \
        ca-certificates \
        curl \
        git \
        nodejs \
        npm \
        procps \
        ripgrep \
    && npm install -g @larksuite/cli@latest \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /root/newman

COPY backend ./backend
COPY plugins ./plugins
COPY scripts ./scripts
COPY skills ./skills
COPY newman.yaml ./newman.yaml

RUN mkdir -p backend_data outputs test_runtimespace \
    && python -m pip install --upgrade pip \
    && python -m pip install -e ./backend

EXPOSE 8005

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8005"]
