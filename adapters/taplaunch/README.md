# 代码重构工具（可离线运行版）

下载解压即可用的代码重构与语义提取服务。自带 FastAPI 接口 + 网页界面 + MCP Server，不依赖任何外部数据库或云服务。

## 30 秒跑起来

```bash
# 1. 装依赖（只有 3 个，都是纯 Python）
pip install fastapi uvicorn httpx

# 2. 启动
python run.py

# 3. 打开浏览器
# http://127.0.0.1:8000/
```

**不装 Ollama 也能用**——会自动切到规则引擎模式，做 `== None → is None`、清理无用 import、统一缩进这类机械改造，并在响应里标 `degraded=true`。

想要真正的 AI 重构，再装模型：

```bash
ollama pull deepseek-coder
export OLLAMA_MODEL=deepseek-coder
python run.py
```

## 你会得到什么

| 入口 | 地址 | 用途 |
|---|---|---|
| 网页界面 | `/` | 粘贴代码，点按钮看结果 |
| 接口文档 | `/docs` | 自动生成的 Swagger，可直接试 |
| 重构接口 | `POST /refactor` | 传代码 + 任务，返回完整代码 |
| 语义接口 | `POST /semantic` | 返回结构摘要，几乎零耗时 |
| MCP Server | `POST /mcp` | 给 Claude/Cursor 等 Agent 直接连 |
| 健康检查 | `GET /health` | 看模型是否可用 |

## 为什么它比"直接叫大模型改代码"可靠

让模型改代码最常见的三种翻车：

1. 只给解释不给完整代码 → 本工具提示词强制只输出代码，返回前还会剥掉 Markdown 围栏
2. 顺手改了业务逻辑 → 返回前过 `ast.parse` 语法校验，不合法就退回原代码并说明
3. 你说"没有模型"它给你 500 → 本工具降级到规则引擎，永远有结果，并诚实标注 degraded

## 目录说明

```
core/           服务本体（FastAPI）
  main.py         路由：/refactor /semantic /health /mcp
  refactor.py     重构核心：提示词 + Ollama 调用 + 输出清洗 + 语法校验
  code_semantic.py 语义提取：Python 用 ast，其他语言正则降级
  fallback_refactor.py 规则引擎：无模型时的等价改造
web/index.html  网页界面（单文件，无前端构建）
run.py          启动入口（读 PORT 环境变量）
```

## 常见问题

**Q：接口返回 degraded=true 是什么意思？**
A：当前环境没连上大模型，结果由规则引擎产出，只做了机械等价改造，没有做结构性重构。要真正的 AI 重构请装 Ollama。

**Q：能处理多长的代码？**
A：建议单次不超过 500 行。更长的请按函数拆开分别处理，否则模型容易漏掉后半部分。

**Q：支持 Java / Go 吗？**
A：重构支持（语言由提示词引导），但语义提取对非 Python 语言走正则降级，精度不如 Python 的 AST。

**Q：会改我的原文件吗？**
A：不会。接口只是返回字符串，落盘与否由你决定。

## 授权

买断后可自用与商用，不含转售权。源码开放可自行修改。

## 版本

v1.0.0 —— 重构 / 语义 / 降级 / MCP 四项能力，接口级测试 19 项通过。
