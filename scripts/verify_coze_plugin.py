"""
按扣子插件的真实调用方式验证四个接口。

扣子的 URL 规则是 base + path，所以这里直接拿
plugin_openapi.sharecode.json 里的 path 原样拼上去发请求 ——
这就是插件上线后发出的那个请求，不多不少。
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOC = ROOT / "adapters" / "coze_bot" / "plugin_openapi.sharecode.json"
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

PASS, FAIL = [], []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"  {'✓' if ok else '✗'} {name}" + (f"  [{detail}]" if detail and not ok else ""))


def call(base: str, path: str, payload: dict):
    req = urllib.request.Request(
        base + path,
        data=json.dumps(payload).encode(),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with OPENER.open(req, timeout=120) as r:
            return r.status, r.read().decode("utf-8", "ignore")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "ignore")
    except Exception as exc:  # noqa: BLE001
        return 0, f"{type(exc).__name__}: {exc}"


def main() -> int:
    doc = json.loads(DOC.read_text(encoding="utf-8"))
    base = doc["servers"][0]["url"]
    paths = list(doc["paths"])
    print(f"base = {base}")
    print(f"paths = {len(paths)}")
    print("=" * 60)

    # 每个 path 的测试载荷：模拟扣子把用户输入填进参数后的样子
    payloads = {
        "/api/code/refactor": {
            "code": "def f(a):\n    if a == None:\n        return 0\n    return a\n",
            "task": "现代化重构，保持行为不变",
            "language": "python",
        },
        "/api/code/semantic": {
            "code": "class A:\n    def run(self, x):\n        return [i * i for i in range(x)]\n",
            "language": "python",
        },
        "/api/interview/start_interview": {
            "jd": "Python 后端工程师，负责高并发 API 服务，要求熟悉 FastAPI、Redis、MySQL，有微服务经验。",
            "level": "社招",
            "history": [],
        },
        "/api/nwdaf/nnwdaf-analyticsinfo/v1/analytics": {
            "eventId": "NF_LOAD",
            "targetNfType": "AMF",
        },
    }

    for path in paths:
        clean = path.split("?")[0]
        payload = payloads.get(clean)
        if payload is None:
            check(f"{clean} 有对应测试载荷", False, "缺少载荷定义")
            continue
        print(f"\n[{clean}]")
        code, body = call(base, path, payload)
        check("HTTP 200", code == 200, f"got {code} {body[:200]}")
        try:
            data = json.loads(body)
            check("返回合法 JSON", True)
        except Exception:
            data = {}
            check("返回合法 JSON", False, body[:120])
        check("非空响应体", bool(data))
        # 抽出关键字段做个提示，方便人眼确认业务上确实有内容
        keys = list(data.keys())[:6]
        print(f"    返回字段：{keys}")

    print("\n" + "=" * 60)
    total = len(PASS) + len(FAIL)
    print(f"通过 {len(PASS)} / {total}")
    if FAIL:
        for f in FAIL:
            print("  - 失败:", f)
        return 1
    print("扣子插件四个接口全部可用")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
