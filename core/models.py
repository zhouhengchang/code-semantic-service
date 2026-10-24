"""
核心服务的数据模型（Pydantic）

说明：
- 所有入参出参统一定义在这里，供 core/main.py 与各平台适配层复用。
- 校验规则尽量宽松，避免上游 Agent 传参不规范时直接 500。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


# 真正实现了分析通路的语言白名单（含常见简写别名）
# python 走 AST 精确解析；其余走通用正则通路，结构字段基本可用
SUPPORTED_LANGUAGES: frozenset[str] = frozenset(
    {"python", "py", "javascript", "js", "typescript", "ts", "java", "go", "auto"}
)


# ============================================================
# 请求模型
# ============================================================
class RefactorRequest(BaseModel):
    """代码重构请求"""

    code: str = Field(
        ...,
        description="待重构的源代码文本",
        max_length=200_000,
    )
    task: str = Field(
        default="现代化重构，保留业务逻辑",
        description="重构任务描述，例如：现代化重构、补充类型注解、提取函数、加异常处理",
        max_length=2_000,
    )
    language: Optional[str] = Field(
        default=None,
        description="代码语言（可选）。不传则自动推断，影响 prompt 组织",
        max_length=40,
    )

    @field_validator("code")
    @classmethod
    def code_not_blank(cls, v: str) -> str:
        """空代码直接拦掉，避免白白消耗推理算力"""
        if not v or not v.strip():
            raise ValueError("code 不能为空")
        return v


class SemanticRequest(BaseModel):
    """代码语义提取请求"""

    code: str = Field(..., description="待分析源代码", max_length=200_000)
    language: str = Field(
        default="python",
        description="代码语言，默认 python；Python 走 AST 精确解析，其余走通用正则通路",
        max_length=40,
    )

    @field_validator("code")
    @classmethod
    def code_not_blank(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("code 不能为空")
        return v

    @field_validator("language")
    @classmethod
    def language_supported(cls, v: str) -> str:
        """
        只接受真正实现了分析通路的语言。

        原因：未知语言（比如 cobol）也会掉进通用正则分支，吐出结构不全的结果，
        但调用方照样被计费——这是对客户不诚实。宁可 422 明确拒绝。
        """
        lang = (v or "python").strip().lower()
        if lang not in SUPPORTED_LANGUAGES:
            raise ValueError(
                "不支持的语言：" + lang + "；可选：" + "、".join(sorted(SUPPORTED_LANGUAGES))
            )
        return lang


# ============================================================
# 响应模型
# ============================================================
class RefactorResponse(BaseModel):
    """重构结果"""

    result: str = Field(..., description="重构后的纯代码文本（不含解释性 Markdown）")
    model: str = Field(..., description="实际使用的 Ollama 模型")
    language: str = Field(..., description="识别到的代码语言")
    billable_units: int = Field(
        default=1,
        description="本次调用消耗的可计费单元数（供 fal.ai 等平台上报）",
    )
    elapsed_ms: int = Field(..., description="服务端耗时（毫秒）")
    degraded: bool = Field(
        default=False,
        description="是否走了规则引擎降级（True 表示当前环境没有可用大模型）",
    )
    notes: List[str] = Field(
        default_factory=list,
        description="本次改造说明（降级时告知具体做了哪些等价变换）",
    )


class SemanticResponse(BaseModel):
    """语义摘要结果"""

    summary: Dict[str, Any] = Field(
        ..., description="结构化语义摘要：imports / classes / functions / calls 等"
    )
    language: str = Field(..., description="识别到的代码语言")
    billable_units: int = Field(default=1, description="本次调用消耗的可计费单元数")
    elapsed_ms: int = Field(..., description="服务端耗时（毫秒）")


class HealthResponse(BaseModel):
    """健康检查结果"""

    status: str
    version: str
    model: str
    ollama_reachable: bool
    ollama_models: List[str] = Field(default_factory=list)


class ErrorResponse(BaseModel):
    """统一错误结构，方便 Agent 侧做重试判断"""

    error: str
    detail: Optional[str] = None
