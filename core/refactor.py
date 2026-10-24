"""
代码重构核心逻辑

职责：
- 接收源代码 + 重构任务描述，调用本地 Ollama 生成重构后的代码。
- 只返回纯代码，不夹带解释性文字（下游 Agent 直接可用）。
- 不做平台相关的任何事情（计费、鉴权都在适配层）。

环境变量：
- OLLAMA_HOST   默认 http://127.0.0.1:11434
- OLLAMA_MODEL  默认 deepseek-coder
- OLLAMA_TIMEOUT 默认 300 秒（CPU 推理较慢，留足时间）
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

import httpx

# ------------------------------------------------------------
# 配置
# ------------------------------------------------------------
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "deepseek-coder")
OLLAMA_TIMEOUT = float(os.getenv("OLLAMA_TIMEOUT", "300"))

# 语言推断用的后缀映射
_EXT_HINTS = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".java": "java",
    ".go": "go",
    ".rs": "rust",
    ".cpp": "cpp",
    ".c": "c",
    ".cs": "csharp",
    ".php": "php",
    ".rb": "ruby",
}


class RefactorError(RuntimeError):
    """重构过程的可预期错误（上游据此返回 5xx 并给出可读原因）"""


# ------------------------------------------------------------
# 工具函数
# ------------------------------------------------------------
def detect_language(code: str, hint: Optional[str] = None) -> str:
    """
    推断代码语言。

    优先级：显式 hint > 后缀命中 > 关键字特征 > 默认 python。
    这是一个启发式判断，只为组织 prompt，不影响正确性。
    """
    if hint:
        h = hint.strip().lower().lstrip(".")
        if h in _EXT_HINTS:
            return _EXT_HINTS["." + h]
        return h

    clues: List[Tuple[str, str]] = [
        ("python", r"(?m)^\s*(def |class |import |from \w+ import |if __name__)"),
        ("go", r"(?m)^\s*(package \w+|func \w+\()"),
        ("rust", r"(?m)^\s*(fn \w+|use \w+::|impl \w+)"),
        ("java", r"(?m)^\s*(public class |private class |package \w+;)"),
        ("javascript", r"(?m)^\s*(function |const \w+ = |let \w+ = |export )"),
        ("typescript", r"(?m)^\s*(interface \w+ \{|export interface )"),
        ("php", r"(?m)^\s*<\?php"),
        ("ruby", r"(?m)^\s*(require '|def \w+$|class \w+ <)"),
    ]
    # 先排除强特征，再按顺序命中
    for lang, pattern in clues:
        if re.search(pattern, code):
            # TypeScript 会先命中 javascript 规则，这里回补一下
            if lang == "javascript" and re.search(r"(?m)(interface \w+ \{|: string\b|: number\b)", code):
                return "typescript"
            return lang
    return "python"


def strip_code_fence(text: str) -> str:
    """
    去掉模型输出里的 Markdown 代码围栏和解释性前后缀。

    小模型经常输出 "```python\\n...\\n```" 或 "以下是重构后的代码："，
    这里做一次清洗，保证返回的是可直接落盘的纯代码。
    """
    if not text:
        return ""

    s = text.strip()

    # 1) 优先抓第一个 ```lang ... ``` 代码块（允许未闭合）
    fence = re.search(r"```[a-zA-Z0-9_+-]*\s*\n(.*?)(?:```|\Z)", s, re.DOTALL)
    if fence:
        s = fence.group(1).strip()
    else:
        # 2) 没有围栏时，剥掉常见的引导语
        s = re.sub(
            r"^\s*(?:以下是|这是|下面是)?[^\n]{0,40}?"
            r"(?:重构后|重构结果|modified|refactored|updated)[^\n]{0,30}?[:：]\s*\n",
            "",
            s,
            flags=re.IGNORECASE,
        )

    # 3) 去掉可能残留的孤立围栏行
    s = re.sub(r"(?m)^\s*```[a-zA-Z0-9_+-]*\s*$", "", s)
    return s.strip()


def build_messages(code: str, task: str, language: str) -> List[dict]:
    """
    构造 /api/chat 的 messages。

    system 里把约束写死：只输出代码、保留行为、不引入不存在的依赖。
    小模型对"只说代码"的遵循度有限，所以后面还要靠 strip_code_fence 兜底。
    """
    system = (
        f"你是一名资深 {language} 工程师，专门做代码重构。\n"
        "硬性要求：\n"
        "1. 只输出重构后的完整代码，不要任何解释、注释说明、前后缀寒暄。\n"
        "2. 严格保留原有业务逻辑与对外行为（函数名/返回值/异常语义不变，除非任务明确要求改变）。\n"
        "3. 不引入新的第三方依赖，除非原代码已经使用。\n"
        "4. 不要用 Markdown 代码围栏包裹结果。\n"
        "5. 保持原语言，不要翻译成其它语言。"
    )
    user = f"重构任务：{task}\n\n待重构代码：\n{code}"
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def compute_billable_units(code: str, base: int = 1) -> int:
    """
    按代码行数计算可计费单元（供适配层上报给平台）。

    分档：<=50 行记 1 单元，之后每 100 行 +1，上限 10 单元，
    避免单个超大请求把单价算术放大到不可控。
    """
    lines = code.count("\n") + 1
    if lines <= 50:
        return base
    units = base + (lines - 50) // 100
    return min(units, 10)


# ------------------------------------------------------------
# 主函数
# ------------------------------------------------------------
def _new_client(timeout: float) -> httpx.Client:
    """
    构造直连客户端。

    trust_env=False 是必须的：如果运行环境里存在 HTTP_PROXY / HTTPS_PROXY，
    httpx 会默认把发往 127.0.0.1 的请求也塞给代理，结果是代理连不上本地
    推理服务，报 ReadError / WinError 10054，接口直接 500。
    本服务的推理后端只在本地/内网，绝不能走系统代理。
    """
    return httpx.Client(timeout=timeout, trust_env=False)


def refactor_code(code: str, task: str = "现代化重构，保留业务逻辑", language: Optional[str] = None) -> str:
    """
    调用 Ollama 完成代码重构，返回纯代码文本。

    参数：
        code: 原始代码
        task: 重构任务描述
        language: 可选语言提示

    异常：
        RefactorError: Ollama 不可达、超时、模型未拉取等
    """
    if not code or not code.strip():
        raise RefactorError("code 为空，拒绝处理")

    lang = detect_language(code, language)
    payload = {
        "model": OLLAMA_MODEL,
        "messages": build_messages(code, task, lang),
        "stream": False,
        # temperature 压低，重构任务需要稳定输出而不是发散创作
        "options": {"temperature": 0.1, "top_p": 0.9, "num_predict": 2048},
    }

    try:
        with _new_client(OLLAMA_TIMEOUT) as client:
            resp = client.post(f"{OLLAMA_HOST}/api/chat", json=payload)
    except httpx.ConnectError as exc:
        raise RefactorError(f"无法连接 Ollama（{OLLAMA_HOST}），请确认服务已启动") from exc
    except httpx.TimeoutException as exc:
        raise RefactorError(f"Ollama 推理超时（>{OLLAMA_TIMEOUT:.0f}s），可换更小模型或增大 OLLAMA_TIMEOUT") from exc
    except httpx.HTTPError as exc:
        # 代理劫持、连接被重置、协议异常等统统归到上游不可用，
        # 否则会漏成 500，让调用方以为是自己的请求有问题
        raise RefactorError(f"访问 Ollama 失败（{type(exc).__name__}: {exc}）") from exc

    if resp.status_code == 404:
        raise RefactorError(f"模型 {OLLAMA_MODEL} 未拉取，请先执行：ollama pull {OLLAMA_MODEL}")
    if resp.status_code >= 400:
        raise RefactorError(f"Ollama 返回 {resp.status_code}: {resp.text[:300]}")

    data = resp.json()
    content = (data.get("message") or {}).get("content", "")
    if not content.strip():
        raise RefactorError("Ollama 返回空内容")

    return strip_code_fence(content)


def refactor_code_with_meta(
    code: str, task: str = "现代化重构，保留业务逻辑", language: Optional[str] = None
) -> dict:
    """
    带元信息版本，供 FastAPI 路由直接使用（一次调用拿到 result / model / 耗时）。

    降级策略：
    云端部署环境没有 Ollama。若 OLLAMA 不可达且 ALLOW_DEGRADED=1（默认），
    改用 core.fallback_refactor 的规则引擎做等价的机械改造，并在响应里
    标注 degraded=True + notes 说明做了什么，绝不返回 503 让网页直接失败。
    """
    started = time.perf_counter()
    lang = detect_language(code, language)
    degraded = False
    notes: List[str] = []
    model = OLLAMA_MODEL

    try:
        result = refactor_code(code, task=task, language=lang)
    except RefactorError as exc:
        if os.getenv("ALLOW_DEGRADED", "1") != "1":
            raise
        # 延迟导入，避免正常路径多加载 AST 相关代码
        from core.fallback_refactor import refactor_by_rules

        result, notes = refactor_by_rules(code, language=lang)
        degraded = True
        model = "rule-engine"
        notes = [f"当前环境未接入大模型（{exc}），已使用规则引擎完成等价改造"] + notes

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    return {
        "result": result,
        "model": model,
        "language": lang,
        "billable_units": 0 if degraded else compute_billable_units(code),
        "elapsed_ms": elapsed_ms,
        "degraded": degraded,
        "notes": notes,
    }


def list_ollama_models() -> List[str]:
    """健康检查用：列出 Ollama 已拉取的模型名"""
    try:
        with _new_client(5) as client:
            resp = client.get(f"{OLLAMA_HOST}/api/tags")
            resp.raise_for_status()
            return [m.get("name", "") for m in resp.json().get("models", [])]
    except Exception:
        return []
