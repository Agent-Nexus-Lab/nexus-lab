"""Shared dependencies — demo user resolution."""

from __future__ import annotations

import logging
import os

from sqlalchemy.orm import Session

from database.models import User

logger = logging.getLogger(__name__)


def get_demo_user(db: Session) -> User | None:
    """Return the fixed demo user, or the first user if DEMO_USER_ID is unset.

    Reads DEMO_USER_ID from the environment.  In single-user MVP mode this
    avoids relying on ``db.query(User).first()`` which is fragile when the
    user table isn't seeded or gets reordered.
    """
    demo_id = os.getenv("DEMO_USER_ID")
    if demo_id:
        user = db.query(User).filter(User.id == demo_id).first()
        if user is not None:
            return user
        logger.warning("DEMO_USER_ID=%s not found in DB, falling back to first user", demo_id)

    user = db.query(User).first()
    if user is not None:
        logger.debug("Resolved demo user via fallback: id=%s", user.id)
    return user
