"""
fal.ai 应用定义（fal.App 结构）
============================================================
作用：
    把 MCP Server 包装成 fal 上可部署的 App，并在 HTTP 响应层补齐
    x-fal-billable-units 头 —— MCP 协议本身跑在 JSON-RPC 上，没有业务响应头，
    所以计费单元在 HTTP 传输层统一补。

说明（重要）：
    fal 的 Python SDK 接口版本迭代较快。本文件按 fal.App 的通用结构编写：
        app = fal.App(name=..., machine_type=...)
        @app.endpoint()
        def handler(req): ...
    提交前请对照 fal 官方文档当前版本核对装饰器与 machine_type 取值，
    如有差异只需改本文件，不影响 core/ 与 mcp_server.py。
"""

from __future__ import annotations

import os
from typing import Any, Dict

# ------------------------------------------------------------
# 计费单元：与 mcp_server.LAST_BILLABLE_UNITS 保持同一份数据源
# ------------------------------------------------------------
BILLABLE_UNITS = {"refactor_code": 1, "extract_semantic": 1}

APP_NAME = os.getenv("FAL_APP_NAME", "code-refactor")
MACHINE_TYPE = os.getenv("FAL_MACHINE_TYPE", "CPU")

try:
    import fal
    from fal.toolkit import Image  # noqa: F401  # 仅为确认 fal 包可用，不实际使用
except ImportError:  # pragma: no cover
    fal = None  # 本地没有 fal 包时仍允许 import 本模块做静态检查


def build_app():
    """
    构造 fal.App 实例。

    返回：
        fal.App 实例（未安装 fal 包时返回 None，并打印提示）
    """
    if fal is None:
        print("[warn] 未安装 fal 包，跳过 App 构造。部署前请 pip install fal")
        return None

    app = fal.App(
        name=APP_NAME,
        # CPU 即可：推理在 Ollama / 外部服务，本 App 只做协议转发
        machine_type=MACHINE_TYPE,
        requirements=[
            "fastapi",
            "uvicorn[standard]",
            "httpx",
            "mcp",
        ],
    )

    @app.endpoint()
    def mcp_endpoint(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """
        MCP JSON-RPC 入口的简化封装。

        真实部署时建议改为直接挂载 mcp_server 的 streamable-http ASGI app；
        这里保留请求/响应结构，便于 fal 侧路由识别并按单元计费。
        """
        method = request.get("method", "")
        tool = (request.get("params") or {}).get("name", "")
        units = BILLABLE_UNITS.get(tool, 1)

        # 关键：上报计费单元。单价由 fal 计费系统配置，这里只报数量。
        # fal 运行时会读取该字段写入账单明细。
        self.response_headers = {"x-fal-billable-units": str(units)}

        return {
            "jsonrpc": "2.0",
            "id": request.get("id"),
            "result": {"ok": True, "method": method, "billable_units": units},
        }

    return app


app = build_app()
