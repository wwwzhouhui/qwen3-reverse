# Qwen FastAPI 逆向项目

基于 **FastAPI** 框架逆向千问官方站点 https://chat.qwen.ai 为本地API，支持所有模型。

## 核心特性

- ✅ **完全兼容 OpenAI API** - 支持流式/非流式响应
- 🚀 **高性能异步框架** - FastAPI + 自动API文档 (`/docs`)
- 🧠 **思维链支持** - 深度思考模式（thinking）
- 💬 **原生多轮对话** - 智能会话匹配，针对 Cherry Studio MCP 优化
- 🖼️ **完善的多模态支持** - 图片/视频/文档上传，文件信息准确传递
- 🔐 **可选API鉴权** - Bearer Token认证
- 📊 **会话持久化** - SQLite本地数据库

## 技术亮点

- **智能会话匹配** - 通过匹配最后一条AI回复，自动续接历史对话
- **OSS文件上传** - 支持阿里云OSS v4签名、分块上传、STS临时授权
- **精准文件信息** - 上传后传递完整文件元数据（大小、ID、类型等），确保AI正确处理
- **Cookie健康管理** - 自动检测Cookie状态，定期健康检查
- **双阶段思考模式** - think阶段推理 + answer阶段回答

## 最近更新

### v0.1.2 (2025-10-05)
- ✅ **修复文件上传功能** - 文件信息（大小、ID、类型）现在准确传递给AI
  - 上传接口现在构造完整文件元数据
  - 多模态聊天优先使用完整文件信息
  - 保持向后兼容（支持URL解析降级）
- 🔧 **优化调试日志** - 明确区分"使用完整文件信息"和"从URL解析"两种模式

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置环境变量

创建 `.env` 文件：

```bash

# 必需：Qwen Cookie（包含token）
QWEN_COOKIES="your_cookies_here"

QWEN_AUTH_TOKEN="your_TOKEN_here"

# 必需：API鉴权Token列表
VALID_TOKENS=["sk-token1", "sk-token2"]
```

**获取 QWEN_COOKIES**：

1. 访问 [chat.qwen.ai](https://chat.qwen.ai) 并登录
2. 打开 F12 → Network 标签页
3. 发送一条消息
4. 找到 `chat/completions` 请求
5. 复制 Request Headers 中的完整 Cookie 值

![获取Cookie示例](https://mypicture-1258720957.cos.ap-nanjing.myqcloud.com/Obsidian/QQ_1759334105644.png)

**获取 QWEN_AUTH_TOKEN**

如果您仍希望单独设置token：

> ① 进入[chat.qwen.ai](https://chat.qwen.ai) ，并登录您的账号
>
> ② 打开 F12 开发者工具
>
> ③ 在顶端找到标签页"Applications/应用"
>
> ④ 在左侧找到"Local Storage/本地存储"，打开下拉菜单
>
> ⑤ 找到 chat.qwen.ai 并进入
>
> ⑥ 在右侧找到"token"的值，整段复制，该值即为 `QWEN_AUTH_TOKEN`

![img](https://mypicture-1258720957.cos.ap-nanjing.myqcloud.com/Obsidian/QQ_1759334220962.png)

### 3. 启动服务

```bash
# 直接运行
python qwen_reverse_fastapi.py

# 或使用 Uvicorn
uvicorn qwen_reverse_fastapi:app --host 0.0.0.0 --port 8000
```

### 4. 验证服务

访问 API 文档：http://localhost:8000/docs

## Docker 部署

### 使用 Docker Compose（推荐）

```bash
# 准备配置
cp .env.example .env
nano .env  # 填入真实配置

# 启动服务
docker-compose up -d

# 查看日志
docker-compose logs -f
```

### 使用 Docker Hub 镜像

```bash
docker pull wwwzhouhui569/qwen_reverse_fastapi:latest

docker run -d \
     --name qwen_reverse_fastapi_proxy \
     -p 8000:8000 \
     -v $(pwd)/logs:/app/logs \
     -v $(pwd)/db:/app/db \
     -e QWEN_COOKIES="your_cookies_here" \
     -e QWEN_AUTH_TOKEN="your_auth_token_here" \
     -e VALID_TOKENS="your_valid_token_here" \
     --restart unless-stopped \
     wwwzhouhui569/qwen_reverse_fastapi:latest
```

## API 端点

| 端点 | 方法 | 说明 | 鉴权 |
|------|------|------|------|
| `/` | GET | 服务器信息 | ❌ |
| `/health` | GET | 健康检查 | ❌ |
| `/docs` | GET | Swagger UI 文档 | ❌ |
| `/v1/models` | GET | 列出可用模型 | ❌ |
| `/v1/chat/completions` | POST | 聊天补全（兼容OpenAI） | ✅ |
| `/v1/chat/multimodal` | POST | 多模态对话（图片） | ✅ |
| `/v1/files/upload` | POST | 文件上传 | ✅ |
| `/v1/image/upload_and_chat` | POST | 图片上传+对话（一体化） | ✅ |
| `/v1/video/upload_and_chat` | POST | 视频上传+对话（一体化） | ✅ |
| `/v2/files/getstsToken` | POST | 获取OSS授权Token | ❌ |

## 使用示例

### 基础聊天

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer sk-your-token" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen3",
    "messages": [{"role": "user", "content": "你好"}]
  }'
```

### 流式响应

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer sk-your-token" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen3",
    "messages": [{"role": "user", "content": "写一首诗"}],
    "stream": true
  }'
```

### 思考模式

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer sk-your-token" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen3",
    "messages": [{"role": "user", "content": "解释量子力学"}],
    "enable_thinking": true,
    "thinking_budget": 20
  }'
```

### 多模态对话（图片）

```bash
curl -X POST http://localhost:8000/v1/chat/multimodal \
  -H "Authorization: Bearer sk-your-token" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen3-vl-plus",
    "messages": [{
      "role": "user",
      "content": [
        {"type": "text", "text": "分析这张图片"},
        {"type": "image_url", "image_url": {"url": "https://example.com/image.jpg"}}
      ]
    }]
  }'
```

### 图片上传和对话（一体化）

**接口说明**：一次性完成图片上传和多模态对话，无需手动管理图片 URL

**✨ 技术优势**：
- **精准文件信息传递** - 上传后自动构造完整文件元数据（真实文件大小、文件ID、Content-Type等）
- **智能上传策略** - 根据文件大小自动选择最优上传方式
- **完整AI支持** - 确保AI能够准确识别和处理图片内容

**基础示例**（非流式）：

```bash
curl -X POST http://localhost:8000/v1/image/upload_and_chat \
  -H "Authorization: Bearer sk-your-token" \
  -F "image=@/path/to/image.jpg" \
  -F "model=qwen3-vl-plus" \
  -F "prompt=请详细分析这张图片的内容" \
  -F "stream=false"
```

**Windows 路径示例**：

```bash
curl --location --request POST 'http://localhost:8000/v1/image/upload_and_chat' \
--header 'Authorization: Bearer sk-your-token' \
--form 'image=@"C:\\Users\\YourName\\Pictures\\photo.jpg"' \
--form 'model="qwen3-vl-plus"' \
--form 'prompt="请分析这张图片"' \
--form 'stream="false"'
```

**流式响应示例**：

```bash
curl -X POST http://localhost:8000/v1/image/upload_and_chat \
  -H "Authorization: Bearer sk-your-token" \
  -F "image=@/path/to/image.jpg" \
  -F "model=qwen3-vl-plus" \
  -F "prompt=请识别图片中的物体和场景" \
  -F "stream=true"
```

**启用思考模式示例**：

```bash
curl -X POST http://localhost:8000/v1/image/upload_and_chat \
  -H "Authorization: Bearer sk-your-token" \
  -F "image=@/path/to/image.jpg" \
  -F "model=qwen3-vl-plus" \
  -F "prompt=请深入分析这张图片的构图和艺术价值" \
  -F "stream=false" \
  -F "enable_thinking=true" \
  -F "thinking_budget=500"
```

**参数说明**：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| image | File | ✅ | - | 图片文件（支持 JPEG, PNG, GIF, WebP, BMP, TIFF, SVG） |
| prompt | String | ✅ | - | 对话提示词 |
| model | String | ❌ | qwen3-vl-plus | 使用的模型 |
| stream | Boolean | ❌ | false | 是否使用流式响应 |
| enable_thinking | Boolean | ❌ | false | 是否启用思考模式 |
| thinking_budget | Integer | ❌ | - | 思考预算（仅在 enable_thinking=true 时有效） |

**上传策略**：
- 图片 <5MB: 使用 POST 表单上传（快速）
- 图片 ≥5MB: 使用分块上传（可靠）
- 最大支持 10MB

**支持格式**：JPEG, PNG, GIF, WebP, BMP, TIFF, SVG（最大 10MB）

### 视频上传和对话（一体化）

**接口说明**：一次性完成视频上传和多模态对话，自动使用分块上传

**✨ 技术优势**：
- **完整文件元数据** - 准确传递视频文件大小、格式、ID等信息给AI
- **分块上传优化** - 自动使用阿里云OSS分块上传，支持大文件
- **智能回退机制** - 分块上传失败时自动尝试POST表单上传

**基础示例**（流式）：

```bash
curl -X POST http://localhost:8000/v1/video/upload_and_chat \
  -H "Authorization: Bearer sk-your-token" \
  -F "video=@/path/to/video.mp4" \
  -F "model=qwen3-vl-plus" \
  -F "prompt=请分析视频中的节日氛围和庆祝活动" \
  -F "stream=true" \
  -F "enable_thinking=true" \
  -F "thinking_budget=1000"
```

**Windows 路径示例**：

```bash
curl --location --request POST 'http://localhost:8000/v1/video/upload_and_chat' \
--header 'Authorization: Bearer sk-your-token' \
--form 'video=@"C:\\Users\\YourName\\Videos\\video.mp4"' \
--form 'model="qwen3-vl-plus"' \
--form 'prompt="请分析视频中的内容"' \
--form 'stream="true"' \
--form 'enable_thinking="false"'
```

**非流式响应示例**：

```bash
curl -X POST http://localhost:8000/v1/video/upload_and_chat \
  -H "Authorization: Bearer sk-your-token" \
  -F "video=@/path/to/video.mp4" \
  -F "model=qwen3-vl-plus" \
  -F "prompt=总结这个视频的主要内容" \
  -F "stream=false"
```

**参数说明**：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| video | File | ✅ | - | 视频文件（支持 MP4, AVI, MOV, WEBM, MKV, WMV, FLV, M4V, 3GP, M2TS） |
| prompt | String | ✅ | - | 对话提示词 |
| model | String | ❌ | qwen3-vl-plus | 使用的模型 |
| stream | Boolean | ❌ | true | 是否使用流式响应 |
| enable_thinking | Boolean | ❌ | false | 是否启用思考模式 |
| thinking_budget | Integer | ❌ | - | 思考预算（仅在 enable_thinking=true 时有效） |

**上传策略**：
- 视频文件：统一使用分块上传（支持大文件）
- 失败时自动回退到 POST 表单上传

**支持格式**：MP4, AVI, MOV, WEBM, MKV, WMV, FLV, M4V, 3GP, M2TS

## 文件上传技术说明

### 文件信息传递机制

本项目在文件上传后会构造完整的文件元数据结构，确保AI能够准确处理文件：

**完整文件信息包含**：
- ✅ **真实文件大小** - 准确的字节数（非0值）
- ✅ **文件ID** - 唯一标识符，用于追踪和管理
- ✅ **Content-Type** - 精确的MIME类型（如 `image/jpeg`, `video/mp4`）
- ✅ **文件类型分类** - `image`/`video`/`file` 三种类型
- ✅ **显示类型** - `vision`/`video`/`document` 用于AI识别
- ✅ **上传状态** - `uploaded` 状态和时间戳

**传递流程**：
1. **上传阶段** - 文件上传到OSS后获取访问URL和STS元数据
2. **元数据构造** - 基于上传结果构造完整文件信息对象
3. **智能传递** - 多模态聊天优先使用完整文件信息，降级支持URL解析
4. **AI处理** - Qwen API接收准确的文件信息进行分析

**向后兼容**：
- 支持直接传递URL（会自动从URL解析文件信息）
- 优先使用完整文件信息（`file_info` 字段）
- 降级机制确保旧版本客户端仍可正常工作

## 主要模型

| 简称 | 实际模型ID | 说明 |
|------|-----------|------|
| qwen3, qwen | qwen3-max | 最新旗舰模型 |
| qwen3-coder | qwen3-coder-plus | 代码专用 |
| qwen3-vl | qwen3-vl-plus | 视觉语言模型 |
| qwq | qwq-32b | 数学推理 |
| gpt-3.5-turbo | qwen-turbo-2025-02-11 | OpenAI兼容 |
| gpt-4 | qwen-plus-2025-09-11 | OpenAI兼容 |

完整模型列表：访问 `/v1/models` 端点

## 故障排除

### Cookie过期

**现象**：API返回401错误
**解决**：重新获取Cookie（参考"快速开始"中的步骤）

### 鉴权失败

**现象**：403错误
**解决**：
- 检查 `VALID_TOKENS` 配置
- 确认请求头格式：`Authorization: Bearer sk-token`
- 查看日志确认Token加载状态

### Docker容器无法启动

```bash
# 查看日志
docker-compose logs -f

# 检查环境变量
docker exec qwen-fastapi-proxy env | grep QWEN

# 重新构建
docker-compose build --no-cache
```

### 权限错误（Permission denied）

**现象**：容器启动报错 `PermissionError: [Errno 13] Permission denied: '/app/logs/...'`

**原因**：挂载的宿主机目录权限与容器内用户不匹配

**解决方案**：

```bash
# 方案1：在启动容器前设置目录权限
mkdir -p logs db
chmod 777 logs db

# 方案2：设置为容器内用户的 UID（999）
sudo chown -R 999:999 logs db

# 方案3：使用 Docker Compose 时，临时以 root 用户运行
# 在 docker-compose.yml 中添加：
# user: "0:0"  # 仅用于调试，不推荐生产环境
```

## 项目结构

```
qwen-reverse/
├── qwen_reverse_fastapi.py  # 主程序
├── requirements.txt         # Python依赖
├── .env.example            # 环境变量模板
├── Dockerfile              # Docker镜像
├── docker-compose.yml      # Docker Compose配置
├── logs/                   # 日志目录
└── db/                     # SQLite数据库
    └── chat_history.db
```

## 许可证

MIT License