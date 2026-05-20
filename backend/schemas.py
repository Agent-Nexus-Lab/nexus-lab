from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime

class BaseData(BaseModel):
    pass


# ============================================================
# 用户画像 — POST/GET/PUT /api/profile
# ============================================================

class ProfileRequest(BaseModel):
    """POST/PUT /api/profile 请求体"""
    nickname: str = Field(..., max_length=32, description="用户昵称")
    campus: str = Field(..., description="主校区：江湾/邯郸/枫林/张江/其他")
    identity: Optional[str] = Field(None, description="本科/硕士/博士/教职工/其他")
    raw_preference_text: Optional[str] = None
    interest_tags: Optional[list[str]] = None
    preferred_campuses: Optional[list[str]] = None
    available_time: Optional[str] = None
    activity_style_tags: Optional[list[str]] = None
    profile_summary: Optional[str] = None


class ProfileData(BaseModel):
    """GET/POST/PUT /api/profile 响应 data"""
    user_id: str
    nickname: str
    campus: str
    identity: Optional[str] = None
    raw_preference_text: Optional[str] = None
    interest_tags: Optional[list[str]] = None
    preferred_campuses: Optional[list[str]] = None
    available_time: Optional[str] = None
    activity_style_tags: Optional[list[str]] = None
    profile_summary: Optional[str] = None
    created_at: datetime
    updated_at: datetime


# ============================================================
# 日程生成 — POST /api/agent/plan-day
# ============================================================

class PlanDayRequest(BaseModel):
    """POST /api/agent/plan-day 请求体"""
    request_text: str = Field(..., max_length=500, description="用户自然语言需求描述")
    date_scope: str = Field(..., description="today / tomorrow / this_week")


class PlanDayResponseData(BaseModel):
    """POST /api/agent/plan-day 响应 data（202 Accepted）"""
    run_id: str
    status: str  # "queued"


# ============================================================
# 运行状态 — GET /api/agent/runs/{run_id}
# ============================================================

class RunItem(BaseModel):
    """日程中的单个活动条目"""
    event_id: str
    title: str
    summary: Optional[str] = None
    start_time: datetime
    end_time: Optional[datetime] = None
    location: Optional[str] = None
    campus: Optional[str] = None
    organizer: Optional[str] = None
    tags: Optional[list[str]] = None
    source_url: Optional[str] = None
    reason_text: Optional[str] = None
    display_order: int
    quality_score: Optional[float] = None


class RunStatusData(BaseModel):
    """GET /api/agent/runs/{run_id} 响应 data"""
    run_id: str
    status: str  # queued / running / completed / failed
    plan_id: Optional[str] = None
    title: Optional[str] = None
    summary: Optional[str] = None
    date_scope: Optional[str] = None
    items: Optional[list[RunItem]] = None
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    error_message: Optional[str] = None


# ============================================================
# 历史日程 — GET /api/plans, GET /api/plans/{plan_id}
# ============================================================

class PlanListItem(BaseModel):
    """GET /api/plans 列表中每条日程"""
    plan_id: str
    title: str
    date_scope: str
    summary: Optional[str] = None
    item_count: int
    created_at: datetime


class PlanListData(BaseModel):
    """GET /api/plans 响应 data（分页）"""
    items: list[PlanListItem]
    total: int
    page: int
    page_size: int


class PlanDetailData(BaseModel):
    """GET /api/plans/{plan_id} 响应 data"""
    plan_id: str
    title: str
    date_scope: str
    summary: Optional[str] = None
    items: list[RunItem]
    created_at: datetime


# ============================================================
# 后台管理 — sources
# ============================================================

class SourceCreateRequest(BaseModel):
    """POST /api/admin/sources 请求体"""
    name: str = Field(..., description="来源名称")
    source_type: str = Field(..., description="web / rss / manual")
    base_url: Optional[str] = None
    feed_url: Optional[str] = None
    is_active: bool = True


class SourceItem(BaseModel):
    """GET /api/admin/sources 列表中每条来源"""
    source_id: str
    name: str
    source_type: str
    base_url: Optional[str] = None
    feed_url: Optional[str] = None
    is_active: bool
    last_crawled_at: Optional[datetime] = None
    event_count: int


class SourceListData(BaseModel):
    """GET /api/admin/sources 响应 data"""
    items: list[SourceItem]
    total: int
    page: int
    page_size: int


class SourceCreateData(BaseModel):
    """POST /api/admin/sources 响应 data"""
    source_id: str
    name: str
    source_type: str
    base_url: Optional[str] = None
    feed_url: Optional[str] = None
    is_active: bool
    created_at: datetime


# ============================================================
# 后台管理 — import-url
# ============================================================

class ImportUrlRequest(BaseModel):
    """POST /api/admin/import-url 请求体"""
    url: str = Field(..., description="要抓取的活动页面 URL")
    source_id: Optional[str] = None


class ImportUrlData(BaseModel):
    """POST /api/admin/import-url 响应 data"""
    document_id: str
    url: str
    status: str  # "queued"


# ============================================================
# 后台管理 — events
# ============================================================

class AdminEventItem(BaseModel):
    """GET /api/admin/events 列表中每条活动"""
    event_id: str
    title: str
    summary: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    location: Optional[str] = None
    campus: Optional[str] = None
    organizer: Optional[str] = None
    source_name: Optional[str] = None
    source_url: Optional[str] = None
    tags: Optional[list[str]] = None
    quality_score: float
    verification_status: str
    is_user_visible: bool
    created_at: datetime


class EventListData(BaseModel):
    """GET /api/admin/events 响应 data"""
    items: list[AdminEventItem]
    total: int
    page: int
    page_size: int