from __future__ import annotations

from typing import Optional, Literal

from pydantic import BaseModel, Field


class TimePreference(BaseModel):
    morning: bool = False
    afternoon: bool = False
    evening: bool = False
    weekend: bool = False


class HardConstraint(BaseModel):
    field: str = Field(
        description="约束类型：excluded_keywords / excluded_tags / campus / date_scope"
    )
    operator: str = Field(
        default="contains",
        description="eq / ne / contains"
    )
    value: str = Field(description="约束值")


class SoftConstraint(BaseModel):
    field: str = Field(
        description="偏好字段：interest_tags / style_tags"
    )
    weight: float = Field(
        default=1.0, ge=0.0, le=2.0,
        description="偏好权重，0.0=排除，0.5=不太喜欢，1.0=喜欢，1.5=特别喜欢，2.0=强烈偏好"
    )
    value: str = Field(description="偏好值")


class IntentParseOutput(BaseModel):
    request_text: str = ""

    date_scope: Literal["today", "tomorrow", "this_week"] = "this_week"

    explicit_campuses: list[str] = Field(
        default_factory=list,
        description="用户本次 query 中明确提到的校区（邯郸/江湾/枫林/张江）"
    )

    max_items: int = Field(
        default=4, ge=1, le=10,
        description="用户本次想要的活动数量，默认 4"
    )

    time_preference: TimePreference = Field(
        default_factory=TimePreference,
        description="从 query 解析到的时段偏好，解析不到则全为 false"
    )

    interest_tags: list[str] = Field(
        default_factory=list,
        description="从 query 解析到的兴趣关键词，解析不到则为空数组"
    )

    style_tags: list[str] = Field(
        default_factory=list,
        description="从 query 解析到的风格标签（轻松/互动/正式等），解析不到则为空数组"
    )

    hard_constraints: list[HardConstraint] = Field(
        default_factory=list,
        description="硬约束（如不要XX、别XX）。"
                    "规则模式下由正则提取；LLM 模式下由模型从 query 中解析（含隐式意图）。"
    )

    soft_constraints: list[SoftConstraint] = Field(
        default_factory=list,
        description="软偏好（如特别喜欢XX、最好XX）。"
                    "规则模式下由正则提取；LLM 模式下由模型从 query 中解析（含隐式意图）。"
    )

    parsed_successfully: bool = True
    parse_warnings: list[str] = Field(default_factory=list)
