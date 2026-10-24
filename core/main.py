"""
FastAPI 入口 —— 所有平台共享的唯一核心服务

启动：
    uvicorn core.main:app --host 0.0.0.0 --port 8000

端点：
    GET  /health    免费健康检查
    POST /refactor  代码重构（收费端点）
    POST /semantic  代码语义提取（收费端点，轻量）

设计约定：
- 本层不做任何鉴权/计费 —— 那是 adapters/ 的职责。
- 但本层会通过 x-billable-units 响应头上报消耗单元，方便上层包装转发给平台。
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse

from core.code_semantic import compute_semantic_units, extract_semantic
from core.models import (
    ErrorResponse,
    HealthResponse,
    RefactorRequest,
    RefactorResponse,
    SemanticRequest,
    SemanticResponse,
)
from core.refactor import OLLAMA_MODEL, RefactorError, list_ollama_models, refactor_code_with_meta

VERSION = "1.0.0"
SERVICE_NAME = os.getenv("SERVICE_NAME", "monetizable-code-service")

# 网页界面目录（部署包里 core/ 和 web/ 同级）
_WEB_DIR = Path(__file__).resolve().parent.parent / "web"

app = FastAPI(
    title="Code Refactor & Semantic API",
    version=VERSION,
    description=(
        "代码重构 + 代码语义提取服务。\n\n"
        "- `POST /refactor`：传入代码与重构任务，返回重构后的纯代码。\n"
        "- `POST /semantic`：提取结构化语义摘要（免费对比用，按次计费时单价更低）。\n"
        "- `GET /health`：健康检查。"
    ),
)

# Agent 侧多为跨域调用，直接放开（付费墙在适配层，不靠 CORS 兜底）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["x-billable-units", "x-service", "x-version"],
)


@app.exception_handler(RefactorError)
async def refactor_error_handler(request: Request, exc: RefactorError) -> JSONResponse:
    """把推理侧故障转成 503，便于调用方区分『我的代码有问题』和『服务侧有问题』"""
    return JSONResponse(
        status_code=503,
        content=ErrorResponse(error="upstream_unavailable", detail=str(exc)).model_dump(),
    )


@app.get("/health", response_model=HealthResponse, tags=["免费"])
def health() -> HealthResponse:
    """健康检查：同时探测 Ollama 是否可达、目标模型是否已拉取"""
    models = list_ollama_models()
    return HealthResponse(
        status="ok" if models else "degraded",
        version=VERSION,
        model=OLLAMA_MODEL,
        ollama_reachable=bool(models),
        ollama_models=models,
    )


@app.post("/refactor", response_model=RefactorResponse, tags=["收费"])
def refactor(req: RefactorRequest) -> JSONResponse:
    """
    代码重构主端点。

    返回：{result, model, language, billable_units, elapsed_ms}
    响应头：x-billable-units（供 fal.ai 等按次计费平台转发上报）
    """
    meta = refactor_code_with_meta(req.code, task=req.task, language=req.language)
    body = RefactorResponse(**meta)
    return JSONResponse(
        content=body.model_dump(),
        headers={
            "x-billable-units": str(body.billable_units),
            "x-service": SERVICE_NAME,
            "x-version": VERSION,
        },
    )


@app.post("/semantic", response_model=SemanticResponse, tags=["收费"])
def semantic(req: SemanticRequest) -> JSONResponse:
    """
    代码语义提取端点。

    纯静态分析，不调用模型 —— 因此响应极快、成本极低，适合作为低价引流端点。
    """
    units = compute_semantic_units(req.code)
    summary = extract_semantic(req.code, language=req.language)
    body = SemanticResponse(
        summary=summary,
        language=summary.get("language", req.language),
        billable_units=units,
        elapsed_ms=summary.get("elapsed_ms", 0),
    )
    return JSONResponse(
        content=body.model_dump(),
        headers={
            "x-billable-units": str(units),
            "x-service": SERVICE_NAME,
            "x-version": VERSION,
        },
    )


@app.get("/", include_in_schema=False)
def root():
    """
    首页：直接返回可交互的网页界面（web/index.html）。

    不用 StaticFiles 挂载，是为了部署时只跑一个进程、少一层路径冲突；
    文件缺失时退回 JSON 指引，保证首页永远不 500。
    """
    page = _WEB_DIR / "index.html"
    if page.is_file():
        return HTMLResponse(page.read_text(encoding="utf-8"))
    return JSONResponse(
        {
            "service": SERVICE_NAME,
            "version": VERSION,
            "docs": "/docs",
            "endpoints": ["POST /refactor", "POST /semantic", "GET /health"],
        }
    )
