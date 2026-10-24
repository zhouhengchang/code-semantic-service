# Code Semantic Service · 代码重构与语义提取

一个可自托管、也可直接调用的代码智能服务：**代码重构** + **代码语义提取**，同时提供 REST API、MCP Server、x402 付费接口三种接入方式。

核心逻辑不依赖任何前端框架，后端只有 FastAPI，推理走本地 Ollama，**没有大模型时自动降级为规则引擎**，保证服务永不 500。

## 在线试用

| 入口 | 地址 | 说明 |
|---|---|---|
| 交互页面 | https://ai-interview-coach-80785.app.workbuddy.host/code | 粘贴代码直接看重构结果 |
| MCP Server | https://ai-interview-coach-80785.app.workbuddy.host/mcp | Agent 可直接连接 |
| OpenAPI | https://ai-interview-coach-80785.app.workbuddy.host/openapi.public.json | 平台导入插件用 |
| 能力清单 | https://ai-interview-coach-80785.app.workbuddy.host/llms.txt | 给 Agent 读的纯文本说明 |

## 它解决什么问题

重构代码这件事，人做起来慢，用大模型直接做又不稳定：模型可能改掉业务逻辑、可能只给一段解释而不给完整代码、可能把缩进搞乱。

这个服务做了三件事来保证结果可用：

1. **只输出代码**，不夹带解释文字。提示词和输出清洗双管齐下，`refactor_code()` 返回的一定是可直接替换的代码。
2. **强制校验可运行性**。Python 代码会过一遍 `ast.parse`，语法不合法就退回原代码并说明原因，绝不返回一段跑不起来的"重构结果"。
3. **没有模型也能干活**。`fallback_refactor.py` 是纯规则引擎：`== None` → `is None`、清理未使用 import、统一缩进、补类型注解占位。机械改造语义等价，不会引入新 bug。

## 快速开始

### 方式一：MCP（推荐给 Agent）

任何支持 MCP 的客户端填这个地址即可，无需鉴权：

```json
{
  "mcpServers": {
    "code-semantic": {
      "type": "http",
      "url": "https://ai-interview-coach-80785.app.workbuddy.host/mcp"
    }
  }
}
```

提供的工具：

| 工具 | 作用 |
|---|---|
| `refactor_code(code, task?, language?)` | 按任务重构代码，返回完整代码 |
| `extract_semantic(code, language?)` | 提取函数/类/导入/调用的结构化摘要 |
| `start_interview(jd, level?, history?)` | 按岗位 JD 生成面试题 |
| `nwdaf_analytics(event_id, target_nf_type?)` | 5G NWDAF 网络分析查询 |

### 方式二：REST API

```bash
# 代码重构
curl -X POST https://ai-interview-coach-80785.app.workbuddy.host/api/code/refactor \
  -H "Content-Type: application/json" \
  -d '{"code":"def f(a):\n  if a == None:\n    return 0\n  return a\n","language":"python"}'
```

```json
{
  "result": "def f(a):\n    if a is None:\n        return 0\n    return a\n",
  "model": "deepseek-coder",
  "language": "python",
  "billable_units": 1,
  "degraded": false,
  "elapsed_ms": 842
}
```

`degraded=true` 表示当前环境没有大模型、结果由规则引擎产出——**服务不会假装模型可用**。

### 方式三：x402 付费调用（Agent 原生付费）

不需要注册、不需要 API Key、不需要预充值。请求先拿到报价，再用钱包签名支付：

```bash
# 1) 首次请求会收到 402 + PAYMENT-REQUIRED 报价头
curl -i -X POST https://ai-interview-coach-80785.app.workbuddy.host/paid/refactor \
  -H "Content-Type: application/json" -d '{"code":"x=1"}'

# 2) 带上 X-PAYMENT 头重试即可拿到结果
curl -X POST https://ai-interview-coach-80785.app.workbuddy.host/paid/refactor \
  -H "Content-Type: application/json" \
  -H "X-PAYMENT: <base64 支付载荷>" \
  -d '{"code":"x=1"}'
```

发现文件：`/.well-known/x402`

## 本地运行

```bash
python -m venv .venv && .venv/Scripts/activate     # Windows
pip install -r requirements.txt

# 可选：接本地大模型（不接则走规则引擎）
ollama pull deepseek-coder
export OLLAMA_MODEL=deepseek-coder

python run.py          # 默认 8000 端口，读 PORT 环境变量
```

打开 http://127.0.0.1:8000/docs 看接口文档，或 http://127.0.0.1:8000/ 用交互页面。

### 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `PORT` | 8000 | 监听端口 |
| `OLLAMA_HOST` | http://127.0.0.1:11434 | Ollama 地址 |
| `OLLAMA_MODEL` | deepseek-coder | 模型名 |
| `OLLAMA_TIMEOUT` | 120 | 推理超时（秒） |
| `ALLOW_DEGRADED` | 1 | 模型不可用时是否降级到规则引擎 |
| `X402_PAY_TO` | 空 | 收款地址，留空则付费接口不接单 |

## 项目结构

```
core/
  main.py             FastAPI 入口（/refactor /semantic /health）
  refactor.py         重构核心：提示词、Ollama 调用、输出清洗、AST 校验
  code_semantic.py    语义提取：AST 优先，正则降级（支持多语言）
  fallback_refactor.py 规则引擎：无模型时的等价改造
  models.py           Pydantic 请求/响应模型
adapters/             各平台上架适配层（fal.ai / x402 / ClawMart / 扣子 / TapLaunch）
tests/                接口级测试，19 项
```

## 已知取巧与限制

- **不用 tree-sitter**。非 Python 语言走正则降级，精度不如 AST，但零编译依赖，部署省心。要更高精度可自行接 tree-sitter。
- **降级模式不做语义理解**。规则引擎只做机械等价的改造，重构质量远低于模型模式，所以响应里会明确标 `degraded=true`。
- **x402 端点不做本地验签**。签名验证交给链上/ facilitator，因为本地验签无法判断 nonce 是否已用，会漏掉重放攻击。

## License

MIT
