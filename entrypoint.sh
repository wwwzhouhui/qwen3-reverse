#!/bin/bash
set -e

# 确保日志和数据库目录存在
mkdir -p /app/logs /app/db

# 尝试修复权限（如果目录已挂载且无权限，会静默失败）
chmod -R 755 /app/logs 2>/dev/null || true
chmod -R 755 /app/db 2>/dev/null || true

# 启动应用
exec python qwen_reverse_fastapi.py
