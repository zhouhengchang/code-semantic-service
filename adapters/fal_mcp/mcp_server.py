"""
fal.ai MCP Server 适配层
============================================================
作用：
    把 core/ 的重构与语义能力包装成 MCP 工具，供 fal.ai Marketplace
    上的 Agent 调用。本层不实现业务逻辑，只做「协议翻译 + 计费单元上报」。

计费要点（fal.ai shared mode）：
    - 平台按 x-fal-billable-units 响应头上报的单元数计费。
    - 单价由 fal 团队在计费系统中配置，本代码只负责"报多少单元"。
    - 单元数由 core 服务按代码行数分档计算后随响应返回。

运行：
    # 本地调试（stdio，供 Claude Desktop / 本地 Agent 连接）
    python adapters/fal_mcp/mcp_server.py

    # HTTP 模式（fal 远程部署 / 远程 Agent 连接）
    MCP_TRANSPORT=streamable-http MCP_PORT=8080 python adapters/fal_mcp/mcp_server.py
"""

from __future__ import annotations

import os
import sys
from typing import Any, Dict

import httpx

# 允许从项目根目录导入 core（fal 部署时 core 会一起打进镜像）
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

try:
    from mcp.server.fastmcp import Context, FastMCP
except ImportError:  # pragma: no cover
    raise SystemExit(
        "缺少依赖 mcp。请执行：pip install mcp\n"
        "（fal 部署镜像中已包含，本地调试才需要手动装）"
    )

CORE_BASE_URL = os.getenv("CORE_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
CORE_TIMEOUT = float(os.getenv("CORE_TIMEOUT", "300"))
MCP_PORT = int(os.getenv("MCP_PORT", "8080"))
MCP_TRANSPORT = os.getenv("MCP_TRANSPORT", "stdio")

mcp = FastMCP(
    name="code-refactor",
    instructions=(
        "代码重构与语义分析工具集。\n"
        "- refactor_code：把遗留代码重构为现代化规范代码，保留原有业务逻辑。\n"
        "- extract_semantic：提取代码结构摘要（函数/类/导入/调用），不消耗推理算力。\n"
        "建议先用 extract_semantic 了解代码规模，再决定是否 refactor_code。"
    ),
)

# 计费单元缓存：MCP 是 JSON-RPC 无 HTTP 头，这里把最近一次调用的单元数
# 记在服务端，供 HTTP 传输层中间件在响应头上补齐（见 fal_app.py）。
LAST_BILLABLE_UNITS: Dict[str, int] = {"refactor_code": 1, "extract_semantic": 1}


async def _post(path: str, payload: dict) -> Dict[str, Any]:
    """统一调用核心服务，把网络异常翻译成 Agent 能读懂的中文提示"""
    try:
        async with httpx.AsyncClient(timeout=CORE_TIMEOUT) as client:
            resp = await client.post(f"{CORE_BASE_URL}{path}", json=payload)
    except httpx.ConnectError:
        raise RuntimeError(f"核心服务不可达（{CORE_BASE_URL}），请确认 core/main.py 已启动")
    except httpx.TimeoutException:
        raise RuntimeError("核心服务推理超时，请缩短代码长度或换更快的模型")

    if resp.status_code >= 400:
        # 透传核心服务的错误结构，方便上层 Agent 判断是否重试
        raise RuntimeError(f"核心服务返回 {resp.status_code}: {resp.text[:300]}")
    return resp.json()


@mcp.tool()
async def refactor_code(
    code: str,
    task: str = "现代化重构，保留业务逻辑",
    language: str = "",
    ctx: Context = None,
) -> str:
    """
    重构给定代码，返回重构后的纯代码文本。

    参数：
        code:     待重构的源代码（必填）
        task:     重构意图，例如「现代化重构」「补充类型注解」「拆分长函数」
        language: 语言提示（可空，留空由服务端自动推断）

    计费：按代码行数分档上报可计费单元（1-5 单元/次）。
    """
    if ctx:
        await ctx.info("正在重构代码…")

    data = await _post(
        "/refactor",
        {"code": code, "task": task, "language": language or None},
    )
    # 记录单元数，供 HTTP 传输层上报给 fal 计费系统
    LAST_BILLABLE_UNITS["refactor_code"] = int(data.get("billable_units", 1))
    if ctx:
        await ctx.info(f"完成，消耗 {LAST_BILLABLE_UNITS['refactor_code']} 计费单元")
    return data["result"]


@mcp.tool()
async def extract_semantic(code: str, language: str = "python", ctx: Context = None) -> str:
    """
    提取代码的结构化语义摘要（JSON 字符串）。

    纯静态分析，不调用模型，响应快、成本低。适合作为重构前的探查步骤。

    参数：
        code:     待分析代码
        language: 代码语言，默认 python；其它语言走正则降级（精度略低）

    返回：
        JSON 字符串，含 imports / classes / functions / calls / stats
    """
    import json

    data = await _post("/semantic", {"code": code, "language": language})
    LAST_BILLABLE_UNITS["extract_semantic"] = int(data.get("billable_units", 1))
    return json.dumps(data["summary"], ensure_ascii=False, indent=2)


@mcp.tool()
async def health() -> str:
    """检查核心服务与推理后端是否可用（免费，不产生计费）"""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{CORE_BASE_URL}/health")
            resp.raise_for_status()
            return resp.text
    except Exception as exc:
        return f"核心服务异常: {exc}"


if __name__ == "__main__":
    # stdio 供本地 Agent；streamable-http 供 fal 远程部署
    mcp.run(transport=MCP_TRANSPORT)
