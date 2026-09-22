"""ORM models.

Importing this package registers every table on ``Base.metadata`` — both
Alembic's ``env.py`` and ``create_tables()`` rely on that side effect.
"""

from app.models.application import Application, ApplicationEvent
from app.models.base import ApplicationEventType, ApplicationStatus
from app.models.job import Job, JobChangeLog, JobSource, SavedJob
from app.models.resume import Resume, ResumeVersion
from app.models.user import User, UserProfile

__all__ = [
    "Application",
    "ApplicationEvent",
    "ApplicationEventType",
    "ApplicationStatus",
    "Job",
    "JobChangeLog",
    "JobSource",
    "Resume",
    "ResumeVersion",
    "SavedJob",
    "User",
    "UserProfile",
]
