from sqlalchemy import String, Text, DateTime, Integer, ForeignKey, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from datetime import datetime, timezone

from app.core.database import Base


class Meeting(Base):
    __tablename__ = "meetings"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    held_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    attendees: Mapped[str | None] = mapped_column(String(1000), nullable=True)  # comma-separated names
    agenda: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)       # AI-generated
    raw_transcript: Mapped[str | None] = mapped_column(Text, nullable=True) # from speech-to-text

    project_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    project: Mapped["Project | None"] = relationship("Project", back_populates="meetings")  # noqa: F821
    action_items: Mapped[list["MeetingActionItem"]] = relationship(
        "MeetingActionItem", back_populates="meeting", cascade="all, delete-orphan"
    )

    @property
    def attendee_list(self) -> list[str]:
        if not self.attendees:
            return []
        return [a.strip() for a in self.attendees.split(",") if a.strip()]

    def __repr__(self) -> str:
        return f"<Meeting id={self.id} title={self.title!r}>"


class MeetingActionItem(Base):
    __tablename__ = "meeting_action_items"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    assignee: Mapped[str | None] = mapped_column(String(200), nullable=True)
    due_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_done: Mapped[bool] = mapped_column(Boolean, default=False)

    meeting_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False, index=True
    )

    meeting: Mapped["Meeting"] = relationship("Meeting", back_populates="action_items")

    def __repr__(self) -> str:
        return f"<ActionItem id={self.id} assignee={self.assignee!r} done={self.is_done}>"
