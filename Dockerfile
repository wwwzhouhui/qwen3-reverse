# Qwen FastAPI 逆向代理 Docker镜像
FROM python:3.11-slim

# 设置维护者信息
LABEL maintainer="75271002@qq.com"
LABEL version="0.0.1"
LABEL description="Qwen FastAPI Reverse Proxy with OpenAI-compatible API and multimodal support"

# 设置工作目录
WORKDIR /app

# 设置环境变量
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DEBIAN_FRONTEND=noninteractive

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    curl \
    wget \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# 创建非root用户
RUN groupadd -r qwenuser && useradd -r -g qwenuser qwenuser

# 复制requirements文件并安装Python依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用代码
COPY qwen_reverse_fastapi.py .
COPY entrypoint.sh .

# 创建必要的目录并设置权限
RUN mkdir -p logs db && \
    chmod +x entrypoint.sh && \
    chown -R qwenuser:qwenuser /app

# 切换到非root用户
USER qwenuser

# 设置默认环境变量
ENV PORT=8000 \
    HOST=0.0.0.0 \
    DEBUG_STATUS=false

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:${PORT}/health || exit 1

# 暴露端口
EXPOSE ${PORT}

# 启动命令
ENTRYPOINT ["/app/entrypoint.sh"]