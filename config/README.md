# 配置模块

项目配置管理。

## 文件说明

| 文件 | 说明 |
|------|------|
| `default_config.py` | 默认配置，包括项目路径、数据缓存路径、结果输出路径、LLM 提供者配置等 |

## 环境变量

详见项目根目录的 `.env.example`，核心配置项：
- `DEEPSEEK_API_KEY` — DeepSeek API 密钥（默认 LLM）
- 支持 OpenAI / Qwen / Anthropic / Google Gemini / Ollama 等多种 LLM 后端
