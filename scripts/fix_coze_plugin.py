"""
把扣子插件用的 OpenAPI 一次性修好，并产出两个版本：

1. plugin_openapi.json          标准版：paths 干净，servers 指向公网域名
2. plugin_openapi.sharecode.json 直连版：每个 path 后面带上 ?sharecode=，
   因为本平台分享链接强制要求 sharecode，否则平台网关直接 403

同时修掉一个会让扣子必然失败的真缺陷：
start_interview 的 level 只接受 校招/社招/大厂，
但原文件写的是「实习 / 校招 / 社招 / 高级 / 专家」，Agent 照抄就 422。
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "adapters" / "coze_bot" / "plugin_openapi.json"
PUBLIC_BASE = "https://ai-interview-coach-80785.app.workbuddy.host"
SHARECODE = "YITGYXG4CY"

LEVELS = ["校招", "社招", "大厂"]


def fix_schemas(doc: dict) -> dict:
    """修正参数定义，让平台导入后自动生成的工具描述与真实接口一致"""
    paths = doc["paths"]

    iv = paths["/api/interview/start_interview"]["post"]
    props = iv["requestBody"]["content"]["application/json"]["schema"]["properties"]
    props["jd"] = {"type": "string", "description": "岗位 JD 原文，越具体出的题越贴岗"}
    props["level"] = {
        "type": "string",
        "enum": LEVELS,
        "default": "社招",
        "description": "面试难度档位，只能取 校招 / 社招 / 大厂 三者之一",
    }
    props["history"] = {
        "type": "array",
        "description": "多轮对话历史，形如 [{role, content}]，首轮传空数组",
        "items": {"type": "object"},
    }

    rf = paths["/api/code/refactor"]["post"]
    rprops = rf["requestBody"]["content"]["application/json"]["schema"]["properties"]
    rprops["code"] = {"type": "string", "description": "待重构的源代码全文"}
    rprops["task"] = {
        "type": "string",
        "default": "现代化重构，保持原有接口与行为不变",
        "description": "重构要求，留空则按默认策略",
    }
    rprops["language"] = {"type": "string", "description": "语言提示，如 python / javascript / java"}

    se = paths["/api/code/semantic"]["post"]
    sprops = se["requestBody"]["content"]["application/json"]["schema"]["properties"]
    sprops["code"] = {"type": "string", "description": "待分析源代码全文"}
    sprops["language"] = {"type": "string", "default": "python", "description": "代码语言"}

    return doc


def main() -> int:
    doc = json.loads(SRC.read_text(encoding="utf-8"))
    doc["servers"] = [{"url": PUBLIC_BASE}]
    doc["info"]["title"] = "代码重构与语义提取 API（扣子插件）"
    doc["info"]["description"] = (
        "代码重构、语义摘要、面试出题、NWDAF 分析四类能力。"
        "接入前请把服务器地址设置为 " + PUBLIC_BASE
    )
    doc = fix_schemas(doc)
    SRC.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[ok] 标准版已写回：{SRC}")

    # 直连版：path 上挂 sharecode
    direct = json.loads(json.dumps(doc, ensure_ascii=False))
    direct["info"]["title"] = "代码重构与语义提取 API（扣子插件·直连版）"
    direct["info"]["description"] = (
        "路径中已内置平台分享码，导入后可直接调用，无需再配鉴权。"
    )
    new_paths = {}
    for path, ops in direct["paths"].items():
        sep = "&" if "?" in path else "?"
        new_paths[f"{path}{sep}sharecode={SHARECODE}"] = ops
    direct["paths"] = new_paths

    out = SRC.parent / "plugin_openapi.sharecode.json"
    out.write_text(json.dumps(direct, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[ok] 直连版已生成：{out}")
    print("     路径示例：")
    for p in direct["paths"]:
        print("       " + p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
