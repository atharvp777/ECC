from sqlalchemy import String, Text, DateTime, Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from datetime import datetime, timezone
import enum

from app.core.database import Base


class ProjectCategory(str, enum.Enum):
    BAJA = "baja"
    AGROVAULT = "agrovault"
    COLLEGE = "college"
    PERSONAL = "personal"
    INTERNSHIP = "internship"


class ProjectStatus(str, enum.Enum):
    ACTIVE = "active"
    ON_HOLD = "on_hold"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[ProjectCategory] = mapped_column(
        SAEnum(ProjectCategory), default=ProjectCategory.PERSONAL
    )
    status: Mapped[ProjectStatus] = mapped_column(
        SAEnum(ProjectStatus), default=ProjectStatus.ACTIVE
    )
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    color: Mapped[str] = mapped_column(String(7), default="#6366f1")  # Hex color for UI

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    tasks: Mapped[list["Task"]] = relationship(  # noqa: F821
        "Task", back_populates="project", cascade="all, delete-orphan"
    )
    notes: Mapped[list["Note"]] = relationship(  # noqa: F821
        "Note", back_populates="project", cascade="all, delete-orphan"
    )
    documents: Mapped[list["Document"]] = relationship(  # noqa: F821
        "Document", back_populates="project", cascade="all, delete-orphan"
    )
    meetings: Mapped[list["Meeting"]] = relationship(  # noqa: F821
        "Meeting", back_populates="project", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Project id={self.id} name={self.name!r}>"
