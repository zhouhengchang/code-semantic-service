"""
x402 付费闭环实测 —— 对着真实运行的门户实例跑，不 mock。

覆盖：
  1. 发现文件 /.well-known/x402 里的 payTo / asset / network 是否与配置一致
  2. 无支付头 → 402，且 PAYMENT-REQUIRED 是合法 base64 JSON，字段齐全
  3. 网络不符 / 收款方不符 / 金额不足 → 必须被拒
  4. 正确支付头 → 200，带回可解析的 X-PAYMENT-RESPONSE 结算回执
  5. 免费接口不受付费闸门影响

用法：python test_x402_live.py [base_url]
"""

from __future__ import annotations

import base64
import json
import sys
import urllib.error
import urllib.request

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8321").rstrip("/")
# 生产环境托管要求 URL 带 sharecode，否则平台层直接 403。
# 允许把 "?sharecode=xxx" 附在 base 后面，脚本自动把参数带到每个请求上。
SHARE_QUERY = ""
if "?" in BASE:
    BASE, SHARE_QUERY = BASE.split("?", 1)
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

PASS, FAIL = [], []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    print(f"  {'✓' if cond else '✗'} {name}" + (f"  [{detail}]" if detail and not cond else ""))


def call(path: str, payload: dict | None = None, headers: dict | None = None):
    """返回 (状态码, 响应体文本, 响应头)"""
    data = json.dumps(payload).encode() if payload is not None else None
    url = BASE + path
    if SHARE_QUERY:
        url += ("&" if "?" in url else "?") + SHARE_QUERY
    req = urllib.request.Request(url, data=data, method="POST" if data else "GET")
    req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with OPENER.open(req, timeout=90) as r:
            return r.status, r.read().decode("utf-8", "ignore"), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "ignore"), dict(e.headers)
    except Exception as exc:  # noqa: BLE001
        return 0, f"{type(exc).__name__}: {exc}", {}


def b64(obj: dict) -> str:
    return base64.b64encode(json.dumps(obj, separators=(",", ":")).encode()).decode()


def header(headers: dict, name: str) -> str:
    for k, v in headers.items():
        if k.lower() == name.lower():
            return v
    return ""


def main() -> int:
    print(f"\n目标：{BASE}")
    print("=" * 62)

    # ---------- 1. 发现文件 ----------
    print("\n[1] 发现文件 /.well-known/x402")
    code, body, _ = call("/.well-known/x402")
    check("HTTP 200", code == 200, f"got {code}")
    try:
        disc = json.loads(body)
    except Exception:
        disc = {}
    accepts = (disc.get("accepts") or (disc.get("resources") or [{}]))[0]
    pay_to = accepts.get("payTo", "")
    asset = accepts.get("asset", "")
    network = accepts.get("network", "")
    check("payTo 已配置且是 0x 地址", pay_to.startswith("0x") and len(pay_to) == 42, pay_to)
    check("asset（USDC 合约）存在", asset.startswith("0x") and len(asset) == 42, asset)
    check("network 已声明", bool(network), network)
    check("含标准 accepts 数组", isinstance(disc.get("accepts"), list) and len(disc["accepts"]) > 0)
    check("maxAmountRequired 是整数（非字符串）", isinstance(accepts.get("maxAmountRequired"), int),
          str(type(accepts.get("maxAmountRequired"))))
    res_url = accepts.get("resource", "")
    check("resource 不是内网/沙箱地址", all(bad not in res_url for bad in ("127.0.0.1", "localhost", "sandbox.cloudstudio")), res_url)
    print(f"    payTo={pay_to}")
    print(f"    asset={asset}  network={network}")
    print(f"    resource={res_url}")

    # ---------- 2. 免费接口不受影响 ----------
    print("\n[2] 免费接口（付费闸门不应影响）")
    code, body, _ = call("/api/code/health")
    check("GET /api/code/health → 200", code == 200, f"got {code}")
    code, body, _ = call("/api/code/refactor", {"code": "x = 1\nif x == None:\n    pass\n", "language": "python"})
    ok_free = code == 200 and '"result"' in body
    check("POST /api/code/refactor 免费可用", ok_free, f"got {code} {body[:120]}")

    # ---------- 3. 带 sharecode 之外的付费端点：无头 → 402 ----------
    print("\n[3] 付费端点无支付头 → 402 + 报价单")
    sample = {"code": "def f(a):\n    if a == None:\n        return 0\n    return a\n", "language": "python"}
    code, body, hdrs = call("/paid/refactor", sample)
    check("HTTP 402", code == 402, f"got {code}")
    raw = header(hdrs, "PAYMENT-REQUIRED")
    check("返回 PAYMENT-REQUIRED 头", bool(raw))
    quote = {}
    try:
        quote = json.loads(base64.b64decode(raw).decode())
        check("报价单可 base64 解码为 JSON", True)
    except Exception as exc:  # noqa: BLE001
        check("报价单可 base64 解码为 JSON", False, str(exc))
    q_acc = (quote.get("accepts") or [{}])[0]
    check("报价单 x402Version=1", quote.get("x402Version") == 1, str(quote.get("x402Version")))
    check("报价单 payTo 与配置一致", q_acc.get("payTo", "").lower() == pay_to.lower())
    check("报价单金额为正整数", isinstance(q_acc.get("maxAmountRequired"), int) and q_acc["maxAmountRequired"] > 0)
    check("报价单 asset 与发现文件一致", q_acc.get("asset", "").lower() == asset.lower())
    price = q_acc.get("maxAmountRequired", 0)
    print(f"    报价：{price}（USDC 最小单位）  payTo={q_acc.get('payTo')}")

    # ---------- 4. 非法支付载荷必须被拒 ----------
    print("\n[4] 非法支付载荷 → 必须拒绝")
    bad_cases = {
        "网络不符": {"x402Version": 1, "network": "polygon", "payTo": pay_to, "payload": {"value": price, "asset": asset}},
        "收款方不符": {"x402Version": 1, "network": network, "payTo": "0x" + "11" * 20, "payload": {"value": price, "asset": asset}},
        "金额不足": {"x402Version": 1, "network": network, "payTo": pay_to, "payload": {"value": max(price - 1, 0), "asset": asset}},
        "非法 base64": None,
    }
    for name, payload in bad_cases.items():
        if payload is None:
            code, body, _ = call("/paid/refactor", sample, {"X-PAYMENT": "!!!not-base64!!!"})
        else:
            code, body, _ = call("/paid/refactor", sample, {"X-PAYMENT": b64(payload)})
        check(f"{name} 被拒（非 200）", code != 200, f"got {code} {body[:100]}")

    # ---------- 5. 正确支付 → 200 + 结算回执 ----------
    print("\n[5] 正确支付 → 200 + X-PAYMENT-RESPONSE")
    good = {
        "x402Version": 1,
        "scheme": "exact",
        "network": network,
        "payTo": pay_to,
        "payload": {
            "value": price,
            "asset": asset,
            "signature": "0x" + "ab" * 65,
            "transaction": "0x" + "cd" * 32,
        },
    }
    code, body, hdrs = call("/paid/refactor", sample, {"X-PAYMENT": b64(good)})
    check("HTTP 200", code == 200, f"got {code} {body[:200]}")
    resp = header(hdrs, "X-PAYMENT-RESPONSE")
    check("返回 X-PAYMENT-RESPONSE 回执", bool(resp))
    receipt = {}
    try:
        receipt = json.loads(base64.b64decode(resp).decode())
        check("回执可解析", True)
    except Exception as exc:  # noqa: BLE001
        check("回执可解析", False, str(exc))
    check("回执 success=true", receipt.get("success") is True)
    check("回执含 transaction", bool(receipt.get("transaction")))
    check("回执 network 正确", receipt.get("network") == network, str(receipt.get("network")))
    try:
        paid_body = json.loads(body)
    except Exception:
        paid_body = {}
    check("付费响应 paid=true", paid_body.get("paid") is True, str(paid_body)[:150])
    check("付费响应含重构结果", bool(paid_body.get("summary") or paid_body.get("refactored") or paid_body.get("result")))

    # ---------- 6. 第二个付费端点 ----------
    print("\n[6] 语义提取付费端点")
    code, body, hdrs = call("/paid/semantic", {"code": sample["code"], "language": "python"})
    check("无支付头 → 402", code == 402, f"got {code}")
    raw = header(hdrs, "PAYMENT-REQUIRED")
    q2 = json.loads(base64.b64decode(raw).decode()) if raw else {}
    q2_acc = (q2.get("accepts") or [{}])[0]
    good2 = {
        "x402Version": 1, "network": network, "payTo": pay_to,
        "payload": {"value": q2_acc.get("maxAmountRequired", 0), "asset": asset, "signature": "0x" + "ef" * 65},
    }
    code, body, hdrs = call("/paid/semantic", {"code": sample["code"], "language": "python"}, {"X-PAYMENT": b64(good2)})
    check("正确支付 → 200", code == 200, f"got {code} {body[:200]}")
    check("带回执", bool(header(hdrs, "X-PAYMENT-RESPONSE")))

    # ---------- 7. MCP 仍可用 ----------
    print("\n[7] MCP Server 不受影响")
    code, body, _ = call("/mcp", {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    check("tools/list → 200", code == 200, f"got {code}")
    try:
        tools = [t["name"] for t in json.loads(body).get("result", {}).get("tools", [])]
    except Exception:
        tools = []
    check("工具列表非空", len(tools) > 0, str(tools))
    print(f"    工具：{', '.join(tools)}")

    # ---------- 汇总 ----------
    print("\n" + "=" * 62)
    total = len(PASS) + len(FAIL)
    print(f"通过 {len(PASS)} / {total}")
    if FAIL:
        print("失败项：")
        for f in FAIL:
            print(f"  - {f}")
        return 1
    print("x402 付费闭环全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
