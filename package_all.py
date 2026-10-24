"""
一键打包所有平台的上架产物

设计原则：
1. 幂等 —— 重复跑结果一致，不会累积旧文件
2. 行尾正确 —— 打进包里的 .sh / Dockerfile 必须是 LF，否则容器里跑不起来
3. 可核对 —— 每个包都算 SHA256 并写进 manifest，方便上架后比对是不是同一个版本

产物输出到 artifacts/，不提交到 git（.gitignore 已排除）。
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ARTIFACTS = ROOT / "artifacts"
VERSION = "1.0.0"

# 这些后缀打进包时必须 LF：CRLF 会让 Linux 容器里的解释器找不到 /bin/sh
LF_SUFFIXES = {".sh", ".py", ".md", ".json", ".yaml", ".yml", ".txt", ""}
LF_NAMES = {"Dockerfile", "LICENSE", "run.py", "requirements.txt"}


def _needs_lf(name: str) -> bool:
    p = Path(name)
    return p.name in LF_NAMES or p.suffix.lower() in LF_SUFFIXES or p.suffix == ""


def _add_file(zf: zipfile.ZipFile, path: Path, arcname: str) -> None:
    """
    写入单个文件，按需要把 CRLF 归一到 LF。

    直接读字节而不是 read_text，是为了不破坏二进制文件（PNG 之类）。
    """
    data = path.read_bytes()
    if _needs_lf(path.name) and b"\r\n" in data:
        data = data.replace(b"\r\n", b"\n")
    info = zipfile.ZipInfo(arcname, date_time=(2026, 1, 1, 0, 0, 0))
    # 保留可执行位：脚本上传后要能 chmod +x
    mode = 0o755 if path.suffix == ".sh" else 0o644
    info.external_attr = (0o100000 | mode) << 16
    info.compress_type = zipfile.ZIP_DEFLATED
    zf.writestr(info, data)


def _walk(base: Path, prefix: str, skip: tuple[str, ...] = ("__pycache__", ".pytest_cache")) -> list[tuple[Path, str]]:
    """收集目录下要打包的文件，跳过缓存和隐藏文件"""
    out: list[tuple[Path, str]] = []
    for p in sorted(base.rglob("*")):
        if not p.is_file():
            continue
        if any(part in skip for part in p.parts):
            continue
        if p.name.startswith(".") and p.suffix not in (".example",):
            continue
        out.append((p, f"{prefix}/{p.relative_to(base).as_posix()}"))
    return out


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _zip(target: Path, entries: list[tuple[Path, str]]) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.unlink()
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
        for src, arc in entries:
            _add_file(zf, src, arc)
    return target


# ---------------------------------------------------------------------------
# 各平台产物
# ---------------------------------------------------------------------------


def build_clawmart() -> Path:
    """Claw Mart skill 包：SKILL.md + scripts/"""
    skill = ROOT / "adapters" / "clawmart_skill" / "your-skill"
    entries = _walk(skill, "code-refactor")
    return _zip(ARTIFACTS / f"code-refactor-skill-v{VERSION}.zip", entries)


def build_taplaunch() -> Path:
    """TapLaunch 下载包：完整可运行的独立工具"""
    entries: list[tuple[Path, str]] = []
    entries += _walk(ROOT / "core", "code-refactor-tool/core")
    entries += _walk(ROOT / "web", "code-refactor-tool/web")
    for name in ("run.py", "requirements.txt"):
        p = ROOT / name
        if p.is_file():
            entries.append((p, f"code-refactor-tool/{name}"))
    # 下载包用「下载者视角」的 README，不是项目开发文档
    taplaunch_readme = ROOT / "adapters" / "taplaunch" / "README.md"
    if taplaunch_readme.is_file():
        entries.append((taplaunch_readme, "code-refactor-tool/README.md"))
    if (ROOT / "LICENSE").is_file():
        entries.append((ROOT / "LICENSE", "code-refactor-tool/LICENSE"))
    return _zip(ARTIFACTS / f"code-refactor-tool-v{VERSION}.zip", entries)


def build_fal() -> Path:
    """fal.ai 部署上下文：适配层 + core（fal build 时一起打进镜像）"""
    entries: list[tuple[Path, str]] = []
    entries += _walk(ROOT / "adapters" / "fal_mcp", "fal_mcp")
    entries += _walk(ROOT / "core", "core")
    for name in ("requirements.txt",):
        p = ROOT / name
        if p.is_file():
            entries.append((p, name))
    return _zip(ARTIFACTS / f"fal-mcp-context-v{VERSION}.zip", entries)


def build_coze() -> Path:
    """扣子插件包：OpenAPI 描述 + Bot 配置说明"""
    coze = ROOT / "adapters" / "coze_bot"
    entries = _walk(coze, "coze-plugin")
    return _zip(ARTIFACTS / f"coze-plugin-v{VERSION}.zip", entries)


def build_x402_submission() -> Path:
    """
    x402 发现/提交材料。

    这不是给平台自动读取的文件，而是提交到目录站时可以直接粘贴的内容，
    避免每次手填还填错金额和网络。
    """
    base = "https://ai-interview-coach-80785.app.workbuddy.host"
    data = {
        "name": "Code Semantic Service",
        "description": (
            "代码重构与语义提取。重构返回可直接替换的完整代码并通过语法校验；"
            "语义提取输出函数/类/导入/调用的结构化摘要。"
        ),
        "homepage": base,
        "mcp_endpoint": f"{base}/mcp",
        "openapi": f"{base}/openapi.public.json",
        "discovery": f"{base}/.well-known/x402",
        "llms_txt": f"{base}/llms.txt",
        "resources": [
            {
                "path": "/paid/refactor",
                "method": "POST",
                "price_usdc": 0.01,
                "price_atomic": "10000",
                "network": "base-sepolia",
                "description": "AI 代码重构：按任务描述返回规范化后的完整代码",
            },
            {
                "path": "/paid/semantic",
                "method": "POST",
                "price_usdc": 0.005,
                "price_atomic": "5000",
                "network": "base-sepolia",
                "description": "代码语义提取：返回紧凑结构化摘要",
            },
        ],
        "free_resources": ["/mcp", "/api/code/refactor", "/api/code/semantic", "/openapi.public.json"],
        "categories": ["developer-tools", "code-analysis", "ai"],
        "note": "收款地址需在 deploy.env 中配置 X402_PAY_TO 后，付费端点才会开始接单",
    }
    target = ARTIFACTS / "x402-submission.json"
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def build_github_bundle() -> Path:
    """
    GitHub 推送包：不含 .git，解压后一条命令就能推上去。

    之所以不直接打包 .git 目录：里面含本地路径与提交历史，跨机器拷贝容易出问题。
    给一个干净的源码目录 + 推送脚本，比给一个可能损坏的仓库更可靠。
    """
    entries: list[tuple[Path, str]] = []
    for item in ("core", "web", "adapters", "config", "tests"):
        d = ROOT / item
        if d.is_dir():
            entries += _walk(d, f"repo/{item}")
    for name in ("README.md", "LICENSE", "requirements.txt", "run.py", ".gitignore", ".gitattributes", ".env.example"):
        p = ROOT / name
        if p.is_file():
            entries.append((p, f"repo/{name}"))
    return _zip(ARTIFACTS / f"github-repo-v{VERSION}.zip", entries)


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------


def main() -> int:
    if ARTIFACTS.exists():
        shutil.rmtree(ARTIFACTS)
    ARTIFACTS.mkdir(parents=True)

    builders = [
        ("clawmart", "Claw Mart skill 包（90% 分成）", build_clawmart),
        ("taplaunch", "TapLaunch 下载包（按下载量分成）", build_taplaunch),
        ("fal", "fal.ai 部署上下文（需 Docker）", build_fal),
        ("coze", "扣子/豆包插件包（65% 分成）", build_coze),
        ("x402", "x402 提交材料", build_x402_submission),
        ("github", "GitHub 源码推送包", build_github_bundle),
    ]

    manifest = {
        "version": VERSION,
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "artifacts": [],
    }

    for key, desc, fn in builders:
        try:
            path = fn()
        except Exception as exc:  # noqa: BLE001  单个包失败不该中断其余
            print(f"  [FAIL] {key}: {type(exc).__name__}: {exc}")
            manifest["artifacts"].append({"key": key, "error": str(exc)})
            continue
        size = path.stat().st_size
        entry = {
            "key": key,
            "platform": desc,
            "file": path.name,
            "path": str(path),
            "size_bytes": size,
            "sha256": _sha256(path),
        }
        if path.suffix == ".zip":
            with zipfile.ZipFile(path) as zf:
                entry["file_count"] = len(zf.namelist())
        manifest["artifacts"].append(entry)
        print(f"  [OK]   {key:11s} {path.name:36s} {size/1024:8.1f} KB")

    (ARTIFACTS / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    ok = sum(1 for a in manifest["artifacts"] if "error" not in a)
    print(f"\n产物目录：{ARTIFACTS}")
    print(f"成功 {ok} / {len(builders)} 个包")
    return 0 if ok == len(builders) else 1


if __name__ == "__main__":
    sys.exit(main())
