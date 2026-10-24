"""
代码语义提取

职责：
- 把源码压成紧凑的结构化摘要（顶层函数/类、参数、导入、关键调用）。
- 用途 1：x402 轻量端点（便宜、快、不消耗算力）做前期探查。
- 用途 2：语义传输场景下只传结构不传全文，降低 Token 成本。

实现选择：
- Python 走标准库 ast，零外部依赖、最准。
- 其它语言走正则降级（tree-sitter 在 Windows 上需要编译工具链，
  为了"开箱即跑"这里不引入；后续要提升精度可替换本文件的 _extract_by_regex）。
"""

from __future__ import annotations

import ast
import re
import time
from typing import Any, Dict, List

# 单文件最多收录的条目数，防止超大文件把响应撑爆
MAX_ITEMS = 200

# 正则路径下忽略的关键字，避免把 if/for 误判成函数调用
_CALL_KEYWORDS = {
    "if", "for", "while", "switch", "catch", "return", "function",
    "class", "new", "else", "elif", "def", "func", "fn", "sizeof",
    "typeof", "instanceof", "await", "yield", "import", "from",
}


# ============================================================
# Python：AST 精提
# ============================================================
def _annotation_to_str(node: Any) -> str:
    """把类型注解节点转成可读字符串，失败则返回空串"""
    try:
        return ast.unparse(node)
    except Exception:
        return ""


def _extract_python(code: str) -> Dict[str, Any]:
    """用 AST 提取 Python 代码结构"""
    tree = ast.parse(code)

    imports: List[str] = []
    classes: List[Dict[str, Any]] = []
    functions: List[Dict[str, Any]] = []
    calls: List[str] = []

    for node in tree.body:
        # ---- 顶层导入 ----
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            for alias in node.names:
                imports.append(f"{mod}.{alias.name}" if mod else alias.name)

        # ---- 顶层类 ----
        elif isinstance(node, ast.ClassDef):
            methods = []
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    methods.append(
                        {
                            "name": sub.name,
                            "params": _params_of(sub),
                            "returns": _annotation_to_str(sub.returns) if sub.returns else "",
                        }
                    )
            classes.append(
                {
                    "name": node.name,
                    "bases": [_annotation_to_str(b) for b in node.bases],
                    "doc": (ast.get_docstring(node) or "").split("\n")[0][:120],
                    "methods": methods[:MAX_ITEMS],
                }
            )

        # ---- 顶层函数 ----
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append(
                {
                    "name": node.name,
                    "params": _params_of(node),
                    "returns": _annotation_to_str(node.returns) if node.returns else "",
                    "is_async": isinstance(node, ast.AsyncFunctionDef),
                    "doc": (ast.get_docstring(node) or "").split("\n")[0][:120],
                }
            )

    # ---- 关键调用（全树扫描，去重保序）----
    seen = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = ""
            if isinstance(node.func, ast.Name):
                name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                name = node.func.attr
            if name and name not in _CALL_KEYWORDS and name not in seen:
                seen.add(name)
                calls.append(name)

    return {
        "language": "python",
        "parser": "ast",
        "imports": imports[:MAX_ITEMS],
        "classes": classes[:MAX_ITEMS],
        "functions": functions[:MAX_ITEMS],
        "calls": calls[:MAX_ITEMS],
    }


def _params_of(node: Any) -> List[Dict[str, str]]:
    """提取函数参数（名字 + 注解），忽略 self/cls"""
    out: List[Dict[str, str]] = []
    args = node.args
    for a in list(getattr(args, "posonlyargs", [])) + list(args.args) + list(args.kwonlyargs):
        if a.arg in ("self", "cls"):
            continue
        out.append({"name": a.arg, "type": _annotation_to_str(a.annotation) if a.annotation else ""})
    if args.vararg:
        out.append({"name": "*" + args.vararg.arg, "type": ""})
    if args.kwarg:
        out.append({"name": "**" + args.kwarg.arg, "type": ""})
    return out


# ============================================================
# 其它语言：正则降级
# ============================================================
_IMPORT_PATTERNS = [
    r'^\s*import\s+([\w\.\*\{\},\s]+?)\s*;?\s*$',
    r'^\s*from\s+([\w\.]+)\s+import\s+',
    r'^\s*require\([\'"]([^\'"]+)[\'"]\)',
    r'^\s*use\s+([\w:]+)',
    r'^\s*#include\s*[<"]([^>"]+)[>"]',
]

_FUNC_PATTERNS = [
    r'^\s*(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*\(([^)]*)\)',
    r'^\s*(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?\(([^)]*)\)\s*=>',
    r'^\s*(?:public|private|protected|static|final|\s)*[\w<>\[\]]+\s+(\w+)\s*\(([^)]*)\)\s*\{',
    r'^\s*func\s+(?:\([^)]*\)\s*)?(\w+)\s*\(([^)]*)\)',
    r'^\s*(?:pub\s+)?fn\s+(\w+)\s*\(([^)]*)\)',
]

_CLASS_PATTERNS = [
    r'^\s*(?:export\s+)?(?:abstract\s+)?class\s+(\w+)',
    r'^\s*(?:export\s+)?interface\s+(\w+)',
    r'^\s*struct\s+(\w+)',
    r'^\s*(?:pub\s+)?struct\s+(\w+)',
]


def _extract_by_regex(code: str, language: str) -> Dict[str, Any]:
    """通用正则提取，覆盖 JS/TS/Java/Go/Rust 等常见结构"""
    lines = code.splitlines()

    imports: List[str] = []
    functions: List[Dict[str, Any]] = []
    classes: List[str] = []
    calls: List[str] = []
    seen_calls = set()

    for line in lines:
        for pat in _IMPORT_PATTERNS:
            m = re.match(pat, line)
            if m and m.group(1).strip():
                imports.append(m.group(1).strip())
                break

        for pat in _CLASS_PATTERNS:
            m = re.match(pat, line)
            if m:
                classes.append(m.group(1))
                break
        else:
            for pat in _FUNC_PATTERNS:
                m = re.match(pat, line)
                if m:
                    raw_params = m.group(2) or ""
                    params = [
                        {"name": p.strip().split(":")[0].split("=")[0].strip(), "type": ""}
                        for p in raw_params.split(",")
                        if p.strip()
                    ]
                    functions.append({"name": m.group(1), "params": params, "returns": ""})
                    break

        # 调用收集：形如 xx(...) 但排除定义行
        for m in re.finditer(r"\b([A-Za-z_]\w*)\s*\(", line):
            name = m.group(1)
            if name not in _CALL_KEYWORDS and name not in seen_calls:
                seen_calls.add(name)
                calls.append(name)

    # 去重保序
    def _dedup(seq: List[str]) -> List[str]:
        out, s = [], set()
        for x in seq:
            if x and x not in s:
                s.add(x)
                out.append(x)
        return out

    return {
        "language": language,
        "parser": "regex",
        "imports": _dedup(imports)[:MAX_ITEMS],
        "classes": _dedup(classes)[:MAX_ITEMS],
        "functions": functions[:MAX_ITEMS],
        "calls": _dedup(calls)[:MAX_ITEMS],
    }


# ============================================================
# 主函数
# ============================================================
def extract_semantic(code: str, language: str = "python") -> Dict[str, Any]:
    """
    提取代码结构化摘要。

    返回紧凑 JSON 友好的 dict：
        {
          "language", "parser",
          "imports": [...], "classes": [...], "functions": [...], "calls": [...],
          "stats": {"loc": n, "function_count": n, "class_count": n}
        }

    Python 走 AST；语法错误时自动降级到正则，保证永远有输出。
    """
    lang = (language or "python").strip().lower()
    started = time.perf_counter()

    summary: Dict[str, Any]
    if lang in ("python", "py"):
        try:
            summary = _extract_python(code)
        except SyntaxError as exc:
            # 语法不合法时不能直接报错 —— 语义提取的价值恰恰在于容错
            summary = _extract_by_regex(code, "python")
            summary["parser"] = "regex(fallback)"
            summary["parse_error"] = f"SyntaxError: {exc.msg} (line {exc.lineno})"
    else:
        summary = _extract_by_regex(code, lang)

    summary["stats"] = {
        "loc": code.count("\n") + 1,
        "chars": len(code),
        "import_count": len(summary.get("imports", [])),
        "function_count": len(summary.get("functions", [])),
        "class_count": len(summary.get("classes", [])),
        "call_count": len(summary.get("calls", [])),
    }
    summary["elapsed_ms"] = int((time.perf_counter() - started) * 1000)
    return summary


def compute_semantic_units(code: str) -> int:
    """
    语义端点比重构便宜：按 200 行为 1 单元分档，上限 5。
    """
    lines = code.count("\n") + 1
    if lines <= 200:
        return 1
    return min(1 + (lines - 200) // 400, 5)
