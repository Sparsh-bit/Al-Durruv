from sqlalchemy.orm import Session

from app.models import AuditLog, User


def record(db: Session, user: User | None, action: str, entity: str, entity_id: object = "", detail: str = "") -> None:
    """Add an audit entry to the current transaction (the caller commits)."""
    db.add(
        AuditLog(
            user_id=user.id if user else None,
            user_email=user.email if user else "system",
            action=action,
            entity=entity,
            entity_id=str(entity_id),
            detail=detail[:2000],
        )
    )
