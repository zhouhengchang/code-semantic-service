---
name: code-refactor
description: AI 代码重构器 —— 把遗留代码重构成现代化规范代码并保留业务逻辑，附带结构化语义摘要、技术面试出题、5G 网络分析能力
---

# Code Refactor Skill

面向 OpenClaw Agent 的代码重构 skill。输入源代码 + 重构意图，拿回**可直接落盘的干净代码**：没有 Markdown 围栏、没有"好的，我来帮你重构"之类废话、没有解释段落。

## 为什么需要它

让大模型直接改代码，常见的三种翻车方式：

1. 只给一段 diff 或解释，不给完整文件，你还得自己拼回去
2. 顺手改了业务逻辑——把 `if a == None` 改成 `if not a`，语义全变了
3. 输出被 Markdown 围栏和寒暄话包住，没法直接写回文件

本 skill 在后端做了三件事堵这些坑：提示词约束只输出代码；返回前过语法校验（不合法就退回原代码并说明原因）；响应里明确标注本次是模型产出还是规则引擎产出。

## 能力

| 能力 | 说明 | 耗时 |
|---|---|---|
| **重构** | 现代化重构 / 补类型注解 / 拆长函数 / 加异常处理 / 去重复 | 3-20s（视代码长度与模型） |
| **语义摘要** | 提取函数、类、导入、关键调用，返回结构化 JSON | < 100ms |
| **面试出题** | 按岗位 JD 生成考察题、考察点、追问建议 | 2-10s |
| **网络分析** | 查询 Mock NWDAF 的网元负载、UE 移动性、切片 SLA | < 200ms |

## 配置

本 skill 是**纯客户端封装**，不含推理逻辑，需要连一个可访问的端点。

### 默认端点（开箱即用）

```bash
export REFACTOR_API_BASE="https://ai-interview-coach-80785.app.workbuddy.host"
```

无需 API Key，无需注册。也可以改这个变量指向你自己部署的实例。

### 自建（免费，需自己跑 Ollama）

```bash
pip install -r requirements.txt
ollama pull deepseek-coder
export OLLAMA_MODEL=deepseek-coder
python run.py                      # 默认 8000 端口
export REFACTOR_API_BASE="http://127.0.0.1:8000"
```

### 验证连通

```bash
curl -s "$REFACTOR_API_BASE/api/code/health"
```

返回 `{"status":"ok",...}` 即配置成功。

## 使用

### 重构代码

```bash
scripts/refactor.sh --file ./src/legacy.py --task "拆掉超长函数，补类型注解，保留所有业务分支"
```

结果写到 `legacy.refactored.py`，**原文件不动**。确认无误再自己覆盖。

### 直接传字符串

```bash
scripts/refactor.sh --code 'def f(a,b): return a+b' --task "补充类型注解和文档字符串"
```

### 等价 curl 调用

```bash
curl -s -X POST "$REFACTOR_API_BASE/api/code/refactor" \
  -H "Content-Type: application/json" \
  -d '{
    "code": "def calc(a, b):\n    return a * b + 1",
    "task": "现代化重构，保留业务逻辑",
    "language": "python"
  }'
```

响应：

```json
{
  "result": "def calc(a: float, b: float) -> float:\n    return a * b + 1\n",
  "model": "deepseek-coder",
  "language": "python",
  "billable_units": 1,
  "degraded": false,
  "elapsed_ms": 3200
}
```

| 字段 | 含义 |
|---|---|
| `result` | 重构后的完整代码，可直接写入文件 |
| `degraded` | `true` 表示当前环境没接大模型，结果由规则引擎产出 |
| `model` | 实际模型名，降级时为 `rule-engine` |
| `elapsed_ms` | 服务端耗时 |

**务必检查 `degraded`**。降级模式只做 `== None → is None`、清理无用 import、统一缩进这类机械改造，不会帮你重新设计结构。把它当"AI 重构"用会失望。

### 只看结构，不做重构（快且几乎零成本）

```bash
curl -s -X POST "$REFACTOR_API_BASE/api/code/semantic" \
  -H "Content-Type: application/json" \
  -d '{"code":"class OrderService:\n    def create(self, dto):\n        ...","language":"python"}'
```

返回：

```json
{
  "language": "python",
  "parser": "ast",
  "classes": [{"name": "OrderService", "methods": ["create"]}],
  "functions": [],
  "imports": [],
  "calls": []
}
```

先看摘要判断结构，再决定要不要花时间整篇重构。大文件别一上来就重写。

## 通过 MCP 接入（推荐）

如果你的 Agent 支持 MCP，不需要本 skill 的脚本，直接连：

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

工具：`refactor_code`、`extract_semantic`、`start_interview`、`nwdaf_analytics`。

## 适用场景

- **遗留项目现代化**：Python 2 风格 → 现代写法、callback → async/await、补全类型注解
- **代码审查前置**：先机器规范化，再人工 review，减少噪音
- **跨语言迁移第一步**：先拿语义摘要，再定迁移策略
- **教学对照**：同一段代码重构前后对比

## 边界与限制

- **不做跨文件重构**。一次只处理一段代码，不推断其他模块的接口。
- **不保证性能提升**。目标是可读性与规范性，不是优化。
- **不会自动运行测试**。重构后请自行跑一遍测试。
- **超长文件注意耗时**。单次建议不超过 500 行，更长请按函数拆开分别处理。

## 授权

一次性买断授权，购买后可用于任意数量的个人/团队项目。不含再分发权（不得转售或作为你自己的产品发布）。

## 支持

在 Claw Mart 商品页留言，或提 issue 到 GitHub 仓库。
