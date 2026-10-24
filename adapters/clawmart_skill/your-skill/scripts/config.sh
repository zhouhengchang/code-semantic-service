#!/usr/bin/env bash
# ============================================================
# 配置文件 —— 按你的端点信息填写
# 注意：本文件如填写了调用凭证，不要提交到公开仓库
# ============================================================

# 重构服务端点
#   - 用默认托管端点：保持下面的官方地址
#   - 自建：改成 http://127.0.0.1:8000
# 已用环境变量指定时以环境变量为准（不会覆盖 EXPORT 的值），
# 这样临时切换端点可以直接 export，不用改文件。
export REFACTOR_API_BASE="${REFACTOR_API_BASE-https://ai-interview-coach-80785.app.workbuddy.host}"

# 接口前缀：本服务挂在门户的 /api/code 下。
# 如果是自建独立部署（直接跑 core/main.py），把它设为空字符串。
export REFACTOR_API_PREFIX="${REFACTOR_API_PREFIX-/api/code}"

# 托管端点的调用凭证；自建或 x402 付费端点可留空
export REFACTOR_API_KEY="${REFACTOR_API_KEY-}"
