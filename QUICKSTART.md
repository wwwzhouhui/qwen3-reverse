# Qwen FastAPI 快速启动指南

## 🚀 5分钟快速开始

### 方式一：本地运行（推荐新手）

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置环境变量
cp .env.example .env
nano .env  # 填入你的QWEN_COOKIES

# 3. 启动服务
python qwen_reverse_fastapi.py

# 4. 测试
curl http://localhost:8000/health
```

### 方式二：Docker运行（推荐生产）

```bash
# 1. 配置环境变量
cp .env.example .env
nano .env  # 填入你的QWEN_COOKIES

# 2. 创建目录并设置权限（重要！）
mkdir -p logs db
chmod 777 logs db

# 3. 启动服务（一键启动）
docker-compose up -d

# 4. 查看日志
docker-compose logs -f

# 5. 测试
curl http://localhost:8000/health
```

## 📝 获取QWEN_COOKIES

1. 访问 https://chat.qwen.ai 并登录
2. 按 F12 打开开发者工具
3. 切换到 Network（网络）标签
4. 在网站上发送一条消息
5. 找到 `chat/completions` 请求
6. 复制 Request Headers 中的 Cookie 值
7. 粘贴到 .env 文件的 QWEN_COOKIES

## 🧪 测试API

### 列出模型
```bash
curl http://localhost:8000/v1/models
```

### 发送消息（非流式）
```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen3",
    "messages": [{"role": "user", "content": "你好"}],
    "stream": false
  }'
```

### 发送消息（流式）
```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen3",
    "messages": [{"role": "user", "content": "写一首诗"}],
    "stream": true
  }'
```

### 上传图片并分析（一体化方法，推荐）
```bash
# 一步完成图片上传和分析
curl -X POST http://localhost:8000/v1/image/upload_and_chat \
  -F "image=@/path/to/image.jpg" \
  -F "model=qwen3-vl-plus" \
  -F "prompt=这张图片里有什么？" \
  -F "stream=false"
```

### 上传视频并分析（一体化方法）
```bash
# 一步完成视频上传和分析
curl -X POST http://localhost:8000/v1/video/upload_and_chat \
  -F "video=@/path/to/video.mp4" \
  -F "model=qwen3-vl-plus" \
  -F "prompt=分析这个视频的内容" \
  -F "stream=true"
```

### 传统的两步法（仍然支持）
```bash
# 1. 上传图片
IMAGE_URL=$(curl -X POST http://localhost:8000/v1/files/upload \
  -F "file=@/path/to/image.jpg" | jq -r '.url')

# 2. 发送多模态消息
curl -X POST http://localhost:8000/v1/chat/multimodal \
  -H "Content-Type: application/json" \
  -d "{
    \"model\": \"qwen3-vl-plus\",
    \"messages\": [{
      \"role\": \"user\",
      \"content\": [
        {\"type\": \"text\", \"text\": \"这张图片里有什么？\"},
        {\"type\": \"image_url\", \"image_url\": {\"url\": \"$IMAGE_URL\"}}
      ]
    }]
  }"
```

## 📚 查看API文档

- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## 🛠️ 常用命令

### 本地运行
```bash
# 开发模式（自动重载）
uvicorn qwen_reverse_fastapi:app --reload

# 生产模式（多进程）
gunicorn qwen_reverse_fastapi:app -w 4 -k uvicorn.workers.UvicornWorker
```

### Docker管理
```bash
# 查看日志
docker-compose logs -f

# 重启服务
docker-compose restart

# 停止服务
docker-compose down

# 完全清理
docker-compose down -v
```

### 数据备份
```bash
# 备份数据库
docker exec qwen-fastapi-proxy sqlite3 /app/db/chat_history.db .dump > backup.sql

# 备份所有数据
tar -czf backup-$(date +%Y%m%d).tar.gz db/ logs/
```

## ❓ 遇到问题？

### 权限错误
```bash
# 如果遇到 "Permission denied: '/app/logs/...'"
mkdir -p logs db
chmod 777 logs db
docker-compose restart
```

### 其他问题
1. 查看日志：`docker-compose logs -f`
2. 检查健康状态：`curl http://localhost:8000/health`
3. 验证配置：`docker exec qwen-fastapi-proxy env | grep QWEN`
4. 查看完整文档：`README.md`

## 🎯 下一步

- 集成到你的AI客户端（推荐 Cherry Studio）
- 配置Nginx反向代理实现HTTPS
- 设置监控和日志分析
- 配置多副本负载均衡

---

更多详细信息请参考 [README.md](README.md)
