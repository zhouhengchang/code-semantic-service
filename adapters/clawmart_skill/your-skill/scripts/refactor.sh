#!/usr/bin/env bash
# ============================================================
# Code Refactor Skill 客户端脚本
# ------------------------------------------------------------
# 用法：
#   bash refactor.sh --health
#   bash refactor.sh --file legacy.py --task "现代化重构"
#   bash refactor.sh --code 'def f(a): return a' --task "补类型注解"
#   bash refactor.sh --semantic --file legacy.py
#
# 依赖：curl、jq（jq 可选，缺失时输出原始 JSON）
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 读取配置（用户购买后自行填写）
if [ -f "$SCRIPT_DIR/config.sh" ]; then
    # shellcheck source=/dev/null
    . "$SCRIPT_DIR/config.sh"
fi

API_BASE="${REFACTOR_API_BASE:-http://127.0.0.1:8000}"
API_KEY="${REFACTOR_API_KEY:-}"

MODE="refactor"
CODE=""
FILE=""
TASK="现代化重构，保留业务逻辑"
LANG=""

# ---------- 参数解析 ----------
while [ $# -gt 0 ]; do
    case "$1" in
        --health)    MODE="health"; shift ;;
        --semantic)  MODE="semantic"; shift ;;
        --file)      FILE="$2"; shift 2 ;;
        --code)      CODE="$2"; shift 2 ;;
        --task)      TASK="$2"; shift 2 ;;
        --language)  LANG="$2"; shift 2 ;;
        -h|--help)
            sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'
            exit 0 ;;
        *) echo "未知参数: $1" >&2; exit 2 ;;
    esac
done

# ---------- 健康检查 ----------
if [ "$MODE" = "health" ]; then
    echo "== 检查 $API_BASE =="
    if curl -fsS --max-time 10 "$API_BASE/health"; then
        echo ""
        echo "✅ 服务可用"
    else
        echo "❌ 无法连接，请检查 REFACTOR_API_BASE 或服务是否启动" >&2
        exit 1
    fi
    exit 0
fi

# ---------- 读取代码 ----------
if [ -n "$FILE" ]; then
    if [ ! -f "$FILE" ]; then
        echo "❌ 文件不存在: $FILE" >&2
        exit 1
    fi
    CODE="$(cat "$FILE")"
fi

if [ -z "$CODE" ]; then
    echo "❌ 必须提供 --file 或 --code" >&2
    exit 2
fi

# ---------- 组装 JSON（用 python 避免手动转义出错）----------
PAYLOAD="$(CODE="$CODE" TASK="$TASK" LANG="$LANG" MODE="$MODE" python3 - <<'PY'
import json, os
mode = os.environ["MODE"]
if mode == "semantic":
    body = {"code": os.environ["CODE"], "language": os.environ.get("LANG") or "python"}
else:
    body = {"code": os.environ["CODE"], "task": os.environ["TASK"]}
    if os.environ.get("LANG"):
        body["language"] = os.environ["LANG"]
print(json.dumps(body, ensure_ascii=False))
PY
)"

ENDPOINT="/$MODE"
AUTH_HEADER=()
if [ -n "$API_KEY" ]; then
    AUTH_HEADER=(-H "Authorization: Bearer $API_KEY")
fi

# ---------- 发起请求 ----------
RESP_FILE="$(mktemp)"
HTTP_CODE="$(curl -sS -o "$RESP_FILE" -w '%{http_code}' \
    --max-time 300 \
    -X POST "$API_BASE$ENDPOINT" \
    -H "Content-Type: application/json" \
    "${AUTH_HEADER[@]}" \
    -d "$PAYLOAD")"

if [ "$HTTP_CODE" = "402" ]; then
    echo "⚠️ 该端点需要付费（HTTP 402）。请检查订阅状态或改用托管端点。" >&2
    cat "$RESP_FILE" >&2
    rm -f "$RESP_FILE"
    exit 3
fi

if [ "$HTTP_CODE" -ge 400 ] 2>/dev/null; then
    echo "❌ 请求失败 HTTP $HTTP_CODE" >&2
    cat "$RESP_FILE" >&2
    rm -f "$RESP_FILE"
    exit 1
fi

# ---------- 输出结果 ----------
if [ "$MODE" = "semantic" ]; then
    if command -v jq >/dev/null 2>&1; then
        jq '.summary' "$RESP_FILE"
    else
        cat "$RESP_FILE"
    fi
else
    # 重构结果只打印 result 字段的内容（纯代码），便于直接重定向到文件
    if command -v jq >/dev/null 2>&1; then
        jq -r '.result' "$RESP_FILE"
    else
        python3 - "$RESP_FILE" <<'PY'
import json, sys
with open(sys.argv[1], encoding="utf-8") as f:
    print(json.load(f).get("result", ""))
PY
    fi
fi

rm -f "$RESP_FILE"
