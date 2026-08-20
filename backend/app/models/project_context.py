from sqlalchemy import String, Text, DateTime, Integer, ForeignKey, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from datetime import datetime, timezone

from app.core.database import Base


class ProjectContext(Base):
    """A concise, durable fact/decision/preference scoped to exactly one project.

    This is project-scoped DATA, never instructions. It is distinct from Notes
    (free-form note-taking) and is only ever surfaced to the AI as untrusted
    reference material with an explicit data boundary. A context item may be
    soft-archived by flipping ``active`` to False.
    """

    __tablename__ = "project_context"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source: Mapped[str | None] = mapped_column(String(50), nullable=True, default="user")
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    project: Mapped["Project"] = relationship("Project", back_populates="project_context")  # noqa: F821

    def __repr__(self) -> str:
        return f"<ProjectContext id={self.id} project_id={self.project_id} content={self.content!r}>"