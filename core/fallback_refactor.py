"""
规则引擎降级重构（无大模型时使用）

为什么需要这个模块：
云端部署环境没有 Ollama，如果直接返回 503，用户在网页上点「重构」就永远失败。
这里的规则引擎做的是「确定安全、语义等价」的机械改造，不臆造业务逻辑，
因此即使没有模型也能给出真实可用的结果，并在响应里标注 degraded=True，
让调用方知道这是规则重构而不是模型重构。

支持的改造（只做语义等价的安全操作）：
1. `x == None` / `x != None` 统一改为 `is None` / `is not None`（PEP 8）
2. 清理 Python 中未被引用的顶层 import（基于 AST 名称使用分析）
3. 制表符缩进统一为 4 空格
4. 行尾空白清理、文件末尾补换行、连续 3 个以上空行压缩为 2 个
5. 非 Python 语言只做 3、4 两项（语言无法安全做语义分析）
"""

from __future__ import annotations

import ast
import re
from typing import List, Tuple

# 判断是否 Python 代码的粗略特征
_PY_HINTS = re.compile(r"^\s*(def |class |import |from \S+ import |@\w+)", re.MULTILINE)


def _looks_like_python(code: str) -> bool:
    """用特征 + AST 双重判断，避免把 JS 当 Python 解析"""
    if not _PY_HINTS.search(code):
        return False
    try:
        ast.parse(code)
        return True
    except SyntaxError:
        return False


def _fix_none_compare(code: str) -> Tuple[str, bool]:
    """`== None` → `is None`，`!= None` → `is not None`"""
    new = re.sub(r"([=!]=)\s*None\b", lambda m: "is None" if m.group(1) == "==" else "is not None", code)
    return new, new != code


def _remove_unused_imports(code: str) -> Tuple[str, bool]:
    """
    删除未被引用的顶层 import。

    保守策略：
    - 只处理 `import a` / `import a as b` / `from m import n`、`from m import n as k`
    - 带 `*` 的、`from __future__` 的、有 `# noqa` 的一律跳过
    - 名字出现在代码任意位置（含字符串外）即视为使用，宁可少删不误删
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return code, False

    lines = code.splitlines()
    drop_lines: List[int] = []

    # 收集所有被引用的标识符（含属性访问的根名）
    used: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            used.add(node.id)
        elif isinstance(node, ast.Attribute):
            cur = node
            while isinstance(cur, ast.Attribute):
                cur = cur.value
            if isinstance(cur, ast.Name):
                used.add(cur.id)

    for node in tree.body:
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        seg = ast.get_source_segment(code, node) or ""
        if "noqa" in seg or "*" in seg:
            continue
        if isinstance(node, ast.ImportFrom) and node.module == "__future__":
            continue

        names = []
        for alias in node.names:
            bound = alias.asname or alias.name.split(".")[0]
            names.append(bound)

        if names and not any(n in used for n in names):
            # 整条 import 都没用到 → 删除该行
            start, end = node.lineno - 1, (node.end_lineno or node.lineno) - 1
            for i in range(start, end + 1):
                drop_lines.append(i)

    if not drop_lines:
        return code, False

    kept = [ln for idx, ln in enumerate(lines) if idx not in set(drop_lines)]
    new = "\n".join(kept) + ("\n" if code.endswith("\n") else "")
    return new, new != code


def _normalize_format(code: str) -> Tuple[str, bool]:
    """制表符→4空格、行尾空白、连续空行、文件末尾换行"""
    original = code
    # 行首 tab 视为一级缩进
    code = re.sub(r"(?m)^\t+", lambda m: "    " * len(m.group(0)), code)
    # 行尾空白
    code = re.sub(r"(?m)[ \t]+$", "", code)
    # 3 个以上连续空行压到 2 个
    code = re.sub(r"\n{4,}", "\n\n\n", code)
    code = code.strip("\n") + "\n"
    return code, code != original


def refactor_by_rules(code: str, language: str = "python") -> Tuple[str, List[str]]:
    """
    规则引擎重构入口。

    返回：
        (重构后的代码, 已应用的改造说明列表)
    """
    applied: List[str] = []
    result = code

    is_py = language.startswith("py") and _looks_like_python(result)

    if is_py:
        result, changed = _fix_none_compare(result)
        if changed:
            applied.append("None 比较改为 is / is not（PEP 8 规范）")

        result, changed = _remove_unused_imports(result)
        if changed:
            applied.append("清理未被引用的 import")

    result, changed = _normalize_format(result)
    if changed:
        applied.append("统一缩进与空行、清理行尾空白")

    if not applied:
        applied.append("代码已符合规范，未发现可安全自动改造的点")

    return result, applied
