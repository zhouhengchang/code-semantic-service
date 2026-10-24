# ============================================================
# fal.ai MCP Server 镜像
# ------------------------------------------------------------
# 两种构建目标：
#   1) proxy（默认）：容器内只跑 MCP 转发，推理走外部 OLLAMA_HOST
#      —— 镜像小（~200MB）、启动快，适合已有稳定 Ollama 主机的场景
#   2) standalone：容器内自带 Ollama + 模型
#      —— 镜像大（1GB+），但 fal shared mode 才能真正计量"你的算力成本"
#      构建：docker build --build-arg WITH_OLLAMA=1 -t code-refactor-mcp .
# ============================================================
FROM python:3.11-slim

ARG WITH_OLLAMA=0
ARG OLLAMA_MODEL=deepseek-coder

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    MCP_TRANSPORT=streamable-http \
    MCP_PORT=8080 \
    CORE_BASE_URL=http://127.0.0.1:8000 \
    OLLAMA_HOST=http://127.0.0.1:11434 \
    OLLAMA_MODEL=${OLLAMA_MODEL}

WORKDIR /app

# 基础系统依赖（curl 用于健康检查与 Ollama 安装）
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Python 依赖先装，利用层缓存
COPY adapters/fal_mcp/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# standalone 模式下额外安装 Ollama
RUN if [ "$WITH_OLLAMA" = "1" ]; then \
        curl -fsSL https://ollama.com/install.sh | sh ; \
    fi

# 拷贝源码（core + 适配层共享同一份核心服务）
COPY core/ /app/core/
COPY adapters/fal_mcp/ /app/adapters/fal_mcp/
COPY config/ /app/config/

COPY adapters/fal_mcp/docker-entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/health || exit 1

ENTRYPOINT ["/app/entrypoint.sh"]
