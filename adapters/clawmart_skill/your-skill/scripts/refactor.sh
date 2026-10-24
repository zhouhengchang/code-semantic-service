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

API_BASE="${REFACTOR_API_BASE:-https://ai-interview-coach-80785.app.workbuddy.host}"
API_KEY="${REFACTOR_API_KEY:-}"
# 接口前缀：本服务挂在门户的 /api/code 下；自建独立部署时设为空字符串
API_PREFIX="${REFACTOR_API_PREFIX-/api/code}"

# 找得到哪个 Python 就用哪个：Windows 上通常只有 python，没有 python3。
# 组 JSON 用 Python 而不是 sed/手拼，是为了避免引号、换行、中文转义出错。
PY_BIN=""
for cand in python3 python; do
    if command -v "$cand" >/dev/null 2>&1; then
        PY_BIN="$cand"
        break
    fi
done
if [ -z "$PY_BIN" ]; then
    echo "❌ 未找到 Python，无法安全构造 JSON。请安装 Python 3 后重试。" >&2
    exit 2
fi

MODE="refactor"
CODE=""
FILE=""
OUT=""
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
        --out)       OUT="$2"; shift 2 ;;
        -h|--help)
            sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'
            exit 0 ;;
        *) echo "未知参数: $1" >&2; exit 2 ;;
    esac
done

# ---------- 健康检查 ----------
if [ "$MODE" = "health" ]; then
    echo "== 检查 $API_BASE$API_PREFIX/health =="
    if curl -fsS --max-time 10 "$API_BASE$API_PREFIX/health"; then
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
PAYLOAD="$(CODE="$CODE" TASK="$TASK" LANG="$LANG" MODE="$MODE" "$PY_BIN" - <<'PY'
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

ENDPOINT="$API_PREFIX/$MODE"
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
    rm -f "$RESP_FILE"
    exit 0
fi

# 重构结果只取 result 字段（纯代码），便于直接写文件或重定向
if command -v jq >/dev/null 2>&1; then
    RESULT="$(jq -r '.result' "$RESP_FILE")"
    DEGRADED="$(jq -r '.degraded // false' "$RESP_FILE")"
else
    RESULT="$("$PY_BIN" - "$RESP_FILE" <<'PY'
import json, sys
with open(sys.argv[1], encoding="utf-8") as f:
    print(json.load(f).get("result", ""))
PY
)"
    DEGRADED="$("$PY_BIN" - "$RESP_FILE" <<'PY'
import json, sys
with open(sys.argv[1], encoding="utf-8") as f:
    print(str(json.load(f).get("degraded", False)).lower())
PY
)"
fi

# 默认落盘位置：给了 --file 就写 <原名>.refactored.<ext>，否则不落盘只打印
if [ -z "$OUT" ] && [ -n "$FILE" ]; then
    OUT="${FILE%.*}.refactored.${FILE##*.}"
    # 文件本身没有扩展名时，上面的展开会得到形如 a.refactored.a 的怪名字
    [ "$OUT" = "$FILE" ] && OUT="${FILE}.refactored"
fi

if [ -n "$OUT" ]; then
    printf '%s\n' "$RESULT" > "$OUT"
    echo "✅ 已写入 $OUT（原文件 $FILE 未改动）" >&2
    if [ "$DEGRADED" = "true" ]; then
        echo "⚠️ 本次结果为降级模式产出（服务端未接大模型），只做了机械等价改造，请人工复核" >&2
    fi
else
    printf '%s\n' "$RESULT"
fi

# 降级时在 stdout 场景下也提醒，避免用户把机械改造当成 AI 重构
if [ -z "$OUT" ] && [ "$DEGRADED" = "true" ]; then
    echo "⚠️ 本次结果为降级模式产出（服务端未接大模型），只做了机械等价改造" >&2
fi

rm -f "$RESP_FILE"
