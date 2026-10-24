description: AI 代码重构器 —— 把遗留代码重构成现代化规范代码，保留业务逻辑；附带结构化语义摘要能力
---

# Code Refactor Skill

一个面向 OpenClaw Agent 的代码重构 skill。调用远端重构服务，输入源代码 +
重构意图，拿回可直接落盘的干净代码（无 Markdown 围栏、无解释性废话）。

## 核心能力

| 能力 | 说明 | 耗时 |
|---|---|---|
| **重构** | 现代化重构 / 补类型注解 / 拆长函数 / 加异常处理 / 去重复 | 3-20s（视代码长度） |
| **语义摘要** | 提取函数、类、导入、调用关系，返回结构化 JSON | < 100ms |

## 安装

本 skill 是一个**纯客户端封装**，不包含推理逻辑，需要一个可访问的 API 端点。

### 1. 获取 API 端点

两种方式任选：

**方式 A：用托管端点（推荐，开箱即用）**

在 `scripts/config.sh` 里填入你购买时拿到的端点地址和调用凭证：

```bash
export REFACTOR_API_BASE="https://your-endpoint.example.com"
export REFACTOR_API_KEY="your-key"      # 若端点是 x402 付费型，此项留空
```

**方式 B：自建（免费，需自己跑 Ollama）**

```bash
git clone https://github.com/CHANGE_ME/code-refactor
cd code-refactor
pip install -r requirements.txt
uvicorn core.main:app --port 8000
```

然后 `export REFACTOR_API_BASE="http://127.0.0.1:8000"`。

### 2. 验证连通

```bash
bash scripts/refactor.sh --health
```

返回 `{"status":"ok",...}` 即安装成功。

## 使用示例

### 重构一段 Python 代码

```bash
bash scripts/refactor.sh --file legacy.py --task "现代化重构，补类型注解"
```

### 直接传字符串

```bash
bash scripts/refactor.sh --code 'def f(a,b): return a+b' --task "补充类型注解和文档字符串"
```

### 等价 curl 调用

```bash
curl -X POST "$REFACTOR_API_BASE/refactor" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $REFACTOR_API_KEY" \
  -d '{
    "code": "def calc(a, b):\n    return a * b + 1",
    "task": "现代化重构，保留业务逻辑",
    "language": "python"
  }'
```

响应：

```json
{
  "result": "def calc(a: float, b: float) -> float:\n    \"\"\"...\"\"\"\n    return a * b + 1\n",
  "model": "deepseek-coder",
  "language": "python",
  "billable_units": 1,
  "elapsed_ms": 3200
}
```

### 只看结构，不做重构（快且便宜）

```bash
curl -X POST "$REFACTOR_API_BASE/semantic" \
  -H "Content-Type: application/json" \
  -d '{"code": "（你的代码）", "language": "python"}'
```

## 支持的场景

- **遗留项目现代化**：Python 2 → 3、var → const、callback → async/await
- **代码审查前置**：重构后再人工 review，减少噪音
- **跨语言迁移的第一步**：先拿语义摘要，再决定迁移策略
- **教学**：同一段代码的重构前后对照

## 限制（请如实告知用户）

- 重构质量取决于后端模型。1B 级小模型适合**格式化、补注解、拆函数**这类
  机械重构；涉及架构调整的大改建议用 7B+ 模型。
- **不会**自动运行测试。重构后务必自己跑一遍测试。
- 超长文件（>2000 行）建议切分后分批处理。

## 定价与授权

本 skill 为一次性买断授权，购买后可用于任意数量的个人/团队项目。
不含再分发权（不得转售或作为你自己的产品发布）。

## 支持

问题反馈：在 Claw Mart 商品页留言，或提 issue 到 GitHub 仓库。
