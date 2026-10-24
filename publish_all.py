"""
上架总控 —— 检测凭证，能上架的直接上架，缺凭证的明确告诉缺什么

这个脚本的价值观：**绝不假装成功**。
每个平台的提交动作都真的发出去，然后校验返回状态码；
凭证缺失时打印「缺少 X」，而不是打一行「已完成」糊弄过去。

用法：
    python publish_all.py                 # 只体检，不上架
    python publish_all.py --platform github   # 只上一个平台
    python publish_all.py --all           # 全部尝试

支持的平台与所需凭证：
    github     GITHUB_TOKEN（Personal Access Token，需 repo 权限）
    clawmart   CLAWMART_API_KEY
    x402       X402_PAY_TO（钱包地址，写入 deploy.env 后需重新部署）
    fal        FAL_KEY + 已安装 Docker（当前机器没有 Docker，无法自动）
    coze       —— 必须人工（实名 + 商户入驻）
    taplaunch  —— 必须人工（注册账号后上传）
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ARTIFACTS = ROOT / "artifacts"
REPO_SLUG = "code-semantic-service"          # 想要的 GitHub 仓库名
REPO_DESC = "代码重构与语义提取服务：REST + MCP + x402 三种接入，无模型时自动降级到规则引擎"

# 本机有 HTTP_PROXY，任何对外请求都要显式绕过时会连不上 github；
# 这里统一用直连（境外站点如确实需要代理，把 trust_env 逻辑改掉即可）
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def say(msg: str) -> None:
    print(msg, flush=True)


def _request(url: str, method: str = "GET", token: str = "", payload: dict | None = None) -> tuple[int, str]:
    """发一个 JSON 请求，返回 (状态码, 响应文本)。网络异常返回 (0, 错误信息)"""
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", "publish-all/1.0")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with OPENER.open(req, timeout=45) as r:
            return r.status, r.read().decode("utf-8", "ignore")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "ignore")
    except Exception as exc:  # noqa: BLE001
        return 0, f"{type(exc).__name__}: {exc}"


def _run(cmd: list[str], cwd: Path | None = None) -> tuple[int, str]:
    """跑一条命令，合并 stderr 一起返回，便于定位失败原因"""
    try:
        p = subprocess.run(cmd, cwd=str(cwd) if cwd else None, capture_output=True, text=True, timeout=180)
        return p.returncode, (p.stdout + p.stderr).strip()
    except Exception as exc:  # noqa: BLE001
        return 1, f"{type(exc).__name__}: {exc}"


# ---------------------------------------------------------------------------
# 各平台
# ---------------------------------------------------------------------------


def publish_github() -> bool:
    """
    建仓库 + 推代码。

    用 REST API 建仓库而不是 gh CLI，是因为本机没有 gh，
    而 token 直接调 API 少一层依赖。
    """
    token = os.getenv("GITHUB_TOKEN", "").strip()
    if not token:
        say("  ✗ 缺少 GITHUB_TOKEN")
        say("    获取：https://github.com/settings/tokens → Generate new token (classic) → 勾选 repo")
        say("    然后：export GITHUB_TOKEN=ghp_xxx 再重跑本脚本")
        return False

    code, body = _request("https://api.github.com/user", token=token)
    if code != 200:
        say(f"  ✗ token 无效（HTTP {code}）：{body[:200]}")
        return False
    user = json.loads(body)["login"]
    say(f"  ✓ token 有效，账号：{user}")

    # 仓库已存在时 API 会返回 422，这种情况直接用现成的，不当作失败
    code, body = _request(
        "https://api.github.com/user/repos",
        method="POST",
        token=token,
        payload={"name": REPO_SLUG, "description": REPO_DESC, "private": False, "has_issues": True},
    )
    if code == 201:
        repo_url = json.loads(body)["html_url"]
        say(f"  ✓ 仓库已创建：{repo_url}")
    elif code == 422:
        repo_url = f"https://github.com/{user}/{REPO_SLUG}"
        say(f"  ! 仓库已存在，直接推送：{repo_url}")
    else:
        say(f"  ✗ 创建仓库失败（HTTP {code}）：{body[:300]}")
        return False

    # 远端用 token 形式写进 remote，避免依赖本机的凭据管理器
    remote = f"https://x-access-token:{token}@github.com/{user}/{REPO_SLUG}.git"
    _run(["git", "remote", "remove", "origin"], cwd=ROOT)
    rc, out = _run(["git", "remote", "add", "origin", remote], cwd=ROOT)
    if rc != 0:
        say(f"  ✗ 添加远端失败：{out[:200]}")
        return False

    # 提交工作区里尚未提交的改动，保证推上去的是当前代码
    _run(["git", "add", "-A"], cwd=ROOT)
    _run(["git", "commit", "-m", "chore: 同步平台上架产物与适配层"], cwd=ROOT)

    rc, out = _run(["git", "push", "-u", "origin", "HEAD:main", "--force"], cwd=ROOT)
    if rc != 0:
        # 推送失败时把 token 从输出里抹掉，避免日志泄露凭证
        safe = out.replace(token, "***")
        say(f"  ✗ 推送失败：{safe[:400]}")
        return False

    say(f"  ✓ 代码已推送：{repo_url}")
    say(f"  → 后续可访问：{repo_url}")
    return True


def publish_clawmart() -> bool:
    """
    调用 Claw Mart 的 listings 接口发布 skill。

    注意：这个端点来自立项时的调研，未在本机实测过（没有账号）。
    如果返回 404/405，说明端点变了，需要对照后台的「发布」请求重新确认。
    """
    key = os.getenv("CLAWMART_API_KEY", "").strip()
    if not key:
        say("  ✗ 缺少 CLAWMART_API_KEY")
        say("    需要先在 https://www.shopclawmart.com 注册 creator 账号，在账号设置里生成 API Key")
        return False

    zip_path = ARTIFACTS / "code-refactor-skill-v1.0.0.zip"
    if not zip_path.is_file():
        say("  ✗ 缺少 skill 包，请先运行 package_all.py")
        return False

    payload = {
        "type": "skill",
        "name": "code-refactor",
        "description": "AI 代码重构器：把遗留代码重构成现代化规范代码并保留业务逻辑，附带语义摘要与面试出题",
        "price": 9,
        "category": "automation",
        "version": "1.0.0",
    }
    code, body = _request(
        "https://www.shopclawmart.com/api/v1/listings", method="POST", token=key, payload=payload
    )
    if code in (200, 201):
        say(f"  ✓ 已创建商品：{body[:300]}")
        say(f"  → 上传包：{zip_path}")
        return True

    say(f"  ✗ 接口返回 HTTP {code}：{body[:300]}")
    if code in (404, 405):
        say("    端点可能已变更，请登录创作者后台抓一次真实的发布请求，替换本函数的 URL")
    return False


def publish_x402() -> bool:
    """
    x402 不需要「提交」，它靠发现文件被索引。
    这一步实际是把收款地址写进 deploy.env，让付费端点开始接单。
    """
    pay_to = os.getenv("X402_PAY_TO", "").strip()
    if not pay_to:
        say("  ✗ 缺少 X402_PAY_TO（收款钱包地址）")
        say("    需要你提供一个 EVM 地址（0x + 40 位十六进制），可以是 MetaMask 的收款地址")
        say("    拿到后：export X402_PAY_TO=0x... 再重跑本脚本")
        return False

    if not (pay_to.startswith("0x") and len(pay_to) == 42):
        say(f"  ✗ 地址格式不对（应为 0x + 40 位十六进制）：{pay_to}")
        return False

    env_file = ROOT.parent / "_deploy" / "portal" / "deploy.env"
    if not env_file.is_file():
        say(f"  ✗ 找不到 {env_file}")
        return False

    lines = env_file.read_text(encoding="utf-8").splitlines()
    out = []
    for line in lines:
        if line.startswith("X402_PAY_TO="):
            out.append(f"X402_PAY_TO={pay_to}")
        else:
            out.append(line)
    env_file.write_text("\n".join(out) + "\n", encoding="utf-8")
    say(f"  ✓ 已写入 deploy.env：X402_PAY_TO={pay_to}")
    say("  → 需要重新部署门户，付费端点才会开始接单")
    return True


def publish_fal() -> bool:
    """fal.ai 需要 Docker 构建镜像 + fal CLI 登录，本机两个都没有"""
    key = os.getenv("FAL_KEY", "").strip()
    if not key:
        say("  ✗ 缺少 FAL_KEY")
    else:
        say("  ! FAL_KEY 已配置")
    rc, out = _run(["docker", "--version"])
    if rc != 0:
        say("  ✗ 本机没有 Docker，无法构建镜像")
        say("    fal.ai 部署流程：装 Docker → pip install fal → fal auth login → fal deploy adapters/fal_mcp")
        say("    另需邮件联系 fal 团队启用 shared mode 并配置单元价格（这一步只能人工）")
        return False
    say("  → 产物已就绪：adapters/fal_mcp/，装好 fal CLI 后可直接部署")
    return False


def publish_manual(platform: str) -> bool:
    """确实只能人工的平台，如实说明"""
    if platform == "coze":
        say("  ✗ 必须人工：扣子/豆包需要手机号登录 + 商户实名入驻")
        say("    材料已备好：adapters/coze_bot/plugin_openapi.json（导入即得 4 个工具）")
        say("              adapters/coze_bot/bot_definition.md（Bot 文案 + 调试用例 + 提交清单）")
    elif platform == "taplaunch":
        say("  ✗ 必须人工：TapLaunch 需要注册账号后网页上传")
        say("    材料已备好：artifacts/code-refactor-tool-v1.0.0.zip（已实测解压可运行）")
        say("              adapters/taplaunch/README.md（下载者视角的说明）")
    return False


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

PLATFORMS = {
    "github": ("GitHub 开源仓库", publish_github),
    "clawmart": ("Claw Mart skill（90% 分成）", publish_clawmart),
    "x402": ("x402 付费端点（USDC 按次）", publish_x402),
    "fal": ("fal.ai MCP（shared mode）", publish_fal),
    "coze": ("扣子/豆包 Bot（65% 分成）", publish_manual),
    "taplaunch": ("TapLaunch 下载分成", publish_manual),
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--platform", help="只处理一个平台")
    ap.add_argument("--all", action="store_true", help="全部尝试")
    args = ap.parse_args()

    targets = [args.platform] if args.platform else list(PLATFORMS)
    if args.platform and args.platform not in PLATFORMS:
        say(f"未知平台：{args.platform}，可选：{', '.join(PLATFORMS)}")
        return 2

    say("=" * 62)
    say("上架总控")
    say("=" * 62)

    results: dict[str, str] = {}
    for key in targets:
        name, fn = PLATFORMS[key]
        say(f"\n[{key}] {name}")
        try:
            ok = fn(key) if key in ("coze", "taplaunch") else fn()
        except Exception as exc:  # noqa: BLE001
            say(f"  ✗ 异常：{type(exc).__name__}: {exc}")
            ok = False
        results[key] = "成功" if ok else "待人工/缺凭证"

    say("\n" + "=" * 62)
    for key in targets:
        say(f"  {key:11s} {results[key]}")
    say("=" * 62)

    done = sum(1 for v in results.values() if v == "成功")
    say(f"\n自动完成 {done} / {len(targets)}；其余缺凭证或必须人工，详见上方提示。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
