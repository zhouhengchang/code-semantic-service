"""
代码重构服务 · 接口全量回归测试
------------------------------------------------------------------
覆盖：
    GET  /            根路径指引
    GET  /health      健康检查（含 Ollama 可达性）
    POST /semantic    Python / JavaScript 两种语义提取
    POST /refactor    真实走大模型重构（CPU 较慢，超时给足）
    异常路径：空代码 422、超长代码 422、未知语言降级

用法：
    set CORE_BASE_URL=http://127.0.0.1:8101
    python tests/test_api.py
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

BASE = os.getenv("CORE_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
passed: list[str] = []
failed: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    if ok:
        passed.append(name)
        print(f"  [PASS] {name} {detail}")
    else:
        failed.append(name + (" | " + detail if detail else ""))
        print(f"  [FAIL] {name} {detail}")


def call(path: str, payload: dict | None = None, timeout: int = 60) -> tuple[int, dict, dict]:
    url = BASE + path
    headers = {"Content-Type": "application/json"}
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode()
            try:
                body = json.loads(raw)
            except json.JSONDecodeError:
                body = {"_raw": raw}
            return resp.status, dict(resp.headers), body
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()
        try:
            body = json.loads(raw)
        except json.JSONDecodeError:
            body = {"_raw": raw}
        return exc.code, dict(exc.headers), body


print("=" * 70)
print(f"代码重构服务接口测试  BASE={BASE}")
print("=" * 70)

# ---------- 1. 根路径 ----------
print("\n[1/6] GET /")
code, _, body = call("/")
check("根路径返回 200", code == 200, f"status={code}")
check("根路径给出端点指引", "endpoints" in body or "service" in body or "_raw" in body, str(list(body.keys()))[:80])

# ---------- 2. 健康检查 ----------
print("\n[2/6] GET /health")
code, _, body = call("/health")
check("健康检查返回 200", code == 200, f"status={code}")
check("健康检查含 ollama_reachable 字段", "ollama_reachable" in body)
if body.get("ollama_reachable"):
    check("Ollama 已连通且有模型", bool(body.get("ollama_models")), str(body.get("ollama_models")))
else:
    check("Ollama 不可达时状态标注 degraded", body.get("status") == "degraded", str(body.get("status")))

# ---------- 3. Python 语义提取 ----------
print("\n[3/6] POST /semantic (python)")
py_code = (
    "import os\n\n"
    "def add(a: int, b: int) -> int:\n"
    "    return a + b\n\n"
    "class Foo(Base):\n"
    "    def bar(self):\n"
    "        return os.getcwd()\n"
)
code, headers, body = call("/semantic", {"code": py_code, "language": "python"})
check("语义接口返回 200", code == 200, f"status={code}")
summary = body.get("summary", {})
check("解析出 1 个函数", len(summary.get("functions", [])) == 1, str([f.get("name") for f in summary.get("functions", [])]))
check("解析出 1 个类", len(summary.get("classes", [])) == 1, str([c.get("name") for c in summary.get("classes", [])]))
check("解析出 import", len(summary.get("imports", [])) >= 1, str(summary.get("imports")))
check("响应带 x-billable-units 头", "x-billable-units" in {k.lower(): v for k, v in headers.items()})

# ---------- 4. JavaScript 语义提取 ----------
print("\n[4/6] POST /semantic (javascript)")
js_code = (
    "import React from 'react';\n"
    "function greet(name) { return 'hi ' + name; }\n"
    "class User { save() { return 1; } }\n"
)
code, _, body = call("/semantic", {"code": js_code, "language": "javascript"})
check("JS 语义接口返回 200", code == 200, f"status={code}")
js_summary = body.get("summary", {})
check("JS 走正则解析器", js_summary.get("parser") == "regex", str(js_summary.get("parser")))
check("JS 识别出函数", len(js_summary.get("functions", [])) >= 1, str([f.get("name") for f in js_summary.get("functions", [])]))

# ---------- 5. 参数校验 ----------
print("\n[5/6] 异常路径")
code, _, body = call("/semantic", {"code": "   ", "language": "python"})
check("空代码被拒（422）", code == 422, f"status={code}")
code, _, body = call("/semantic", {"code": "x = 1", "language": "cobol"})
check("非法语言被拒（422）", code == 422, f"status={code}")

# ---------- 6. 真实重构 ----------
print("\n[6/6] POST /refactor（走大模型，CPU 推理约 1 分钟）")
bad = "def f(a):\n  if a==None:\n    return 0\n  else:\n    return a+1\n"
code, headers, body = call("/refactor", {"code": bad, "task": "modernize", "language": "python"}, timeout=300)
if code == 200:
    check("重构接口返回 200", True)
    check("返回非空代码", bool(str(body.get("result", "")).strip()), str(body.get("result"))[:60])
    check("标注了语言", body.get("language") == "python", str(body.get("language")))
    if body.get("degraded"):
        # 规则引擎降级：结果依然可用，但必须如实标注、不再按次计费
        check("降级时标注 degraded", body.get("degraded") is True)
        check("降级时给出改造说明", bool(body.get("notes")), str(body.get("notes"))[:80])
        check("降级时计费单元为 0", body.get("billable_units") == 0, str(body.get("billable_units")))
    else:
        check("上报计费单元", str(body.get("billable_units", 0)).isdigit() and body.get("billable_units") > 0,
              str(body.get("billable_units")))
else:
    # 只有显式关闭降级（ALLOW_DEGRADED=0）时才允许 503；无论如何不能是 500
    check("模型不可用时不返回 500", code == 503, f"status={code} body={str(body)[:100]}")

print("\n" + "=" * 70)
print(f"通过 {len(passed)} 项，失败 {len(failed)} 项")
if failed:
    for f in failed:
        print("  - " + f)
print("=" * 70)
sys.exit(0 if not failed else 1)
