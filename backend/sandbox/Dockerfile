FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    bash \
    ca-certificates \
    curl \
    git \
  && rm -rf /var/lib/apt/lists/*

RUN useradd -m -u 10001 newman
USER newman
WORKDIR /workspace

CMD ["bash"]
