from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from schemas import ProfileRequest, ProfileData
from models import User, UserProfile, MemoryItem
import uuid

router = APIRouter(prefix="/api", tags=["profile"])


@router.post("/profile")
def create_profile(req: ProfileRequest, db: Session = Depends(get_db)):
    existing_user = db.query(User).filter(User.openid == "placeholder").first()
    if existing_user:
        user = existing_user
        user.nickname = req.nickname
        user.campus = req.campus

        profile = db.query(UserProfile).filter_by(user_id=user.id).first()
        if not profile:
            profile = UserProfile(
                user_id=user.id,
                identity=req.identity,
                raw_preference_text=req.raw_preference_text,
                interest_tags=req.interest_tags,
                preferred_campuses=req.preferred_campuses,
                available_time=req.available_time,
                activity_style_tags=req.activity_style_tags,
                profile_summary=req.profile_summary,
            )
            db.add(profile)
        else:
            profile.identity = req.identity
            profile.raw_preference_text = req.raw_preference_text
            profile.interest_tags = req.interest_tags
            profile.preferred_campuses = req.preferred_campuses
            profile.available_time = req.available_time
            profile.activity_style_tags = req.activity_style_tags
            profile.profile_summary = req.profile_summary
        db.commit()
        db.refresh(user)
        db.refresh(profile)
        return {"code": 0, "data": _to_profile_data(user, profile, db).model_dump(mode="json"), "message": "ok"}
    user = User(
        id=str(uuid.uuid4()),
        openid="placeholder",       # 后续从 Header 解析
        nickname=req.nickname,
        campus=req.campus,
    )
    db.add(user)
    profile = UserProfile(
        user_id=user.id,
        identity=req.identity,
        raw_preference_text=req.raw_preference_text,
        interest_tags=req.interest_tags,
        preferred_campuses=req.preferred_campuses,
        available_time=req.available_time,
        activity_style_tags=req.activity_style_tags,
        profile_summary=req.profile_summary,
    )
    db.add(profile)
    db.commit()
    db.refresh(user)
    return {"code": 0, "data": _to_profile_data(user, profile, db).model_dump(mode="json"), "message": "ok"}


@router.get("/profile")
def get_profile(db: Session = Depends(get_db)):
    user = db.query(User).first()    # MVP 先用第一条，后续加鉴权
    if not user:
        return {"code": 0, "data": None, "message": "ok"}
    profile = db.query(UserProfile).filter_by(user_id=user.id).first()
    return {"code": 0, "data": _to_profile_data(user, profile, db).model_dump(mode="json"), "message": "ok"}


@router.put("/profile")
def update_profile(req: ProfileRequest, db: Session = Depends(get_db)):
    user = db.query(User).first()
    if not user:
        raise HTTPException(400, "画像未创建")
    profile = db.query(UserProfile).filter_by(user_id=user.id).first()
    for key, val in req.model_dump(exclude_unset=True).items():
        if key == "nickname":
            setattr(user, key, val)
        elif hasattr(profile, key):
            setattr(profile, key, val)
    db.commit()
    db.refresh(user)
    return {"code": 0, "data": _to_profile_data(user, profile, db).model_dump(mode="json"), "message": "ok"}


def _to_profile_data(user, profile, db=None):
    # Resolve memory_summary from latest active memory_summary MemoryItem
    memory_summary: str | None = None
    if db is not None:
        mem = (
            db.query(MemoryItem)
            .filter_by(user_id=user.id, memory_type="memory_summary", status="active")
            .order_by(MemoryItem.updated_at.desc())
            .first()
        )
        if mem and mem.content:
            memory_summary = mem.content

    return ProfileData(
        user_id=user.id,
        nickname=user.nickname,
        campus=user.campus,
        identity=profile.identity if profile else None,
        raw_preference_text=profile.raw_preference_text if profile else None,
        interest_tags=profile.interest_tags if profile else None,
        preferred_campuses=profile.preferred_campuses if profile else None,
        available_time=profile.available_time if profile else None,
        activity_style_tags=profile.activity_style_tags if profile else None,
        profile_summary=profile.profile_summary if profile else None,
        memory_summary=memory_summary,
        created_at=user.created_at,
        updated_at=profile.updated_at if profile else user.updated_at,
    )