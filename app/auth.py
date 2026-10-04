"""Authentication and role-based access control.

Sessions are signed cookies (via SessionMiddleware). We store only the user id in
the session; the User row is loaded per request. Access helpers enforce the role
model and the per-business / per-store scoping.
"""
from typing import List, Optional

from fastapi import Depends, HTTPException, Request, status
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    Business,
    Role,
    Store,
    User,
    UserBusinessAccess,
    UserStoreAccess,
)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)


def authenticate(db: Session, username: str, password: str) -> Optional[User]:
    user = db.query(User).filter(User.username == username).first()
    if user and verify_password(password, user.password_hash):
        return user
    return None


# --- request-scoped current user -------------------------------------------------

def get_current_user(request: Request, db: Session = Depends(get_db)) -> Optional[User]:
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    return db.query(User).filter(User.id == user_id).first()


def require_login(request: Request, db: Session = Depends(get_db)) -> User:
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"Location": "/login"},
        )
    return user


def require_roles(*roles: Role):
    """Dependency factory enforcing that the current user has one of `roles`."""

    def _checker(user: User = Depends(require_login)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
        return user

    return _checker


# --- scoping helpers --------------------------------------------------------------

def accessible_business_ids(db: Session, user: User) -> List[int]:
    """Business ids the user may act on. Superuser => all."""
    if user.role == Role.SUPERUSER:
        return [b.id for b in db.query(Business.id).all()]
    rows = (
        db.query(UserBusinessAccess.business_id)
        .filter(UserBusinessAccess.user_id == user.id)
        .all()
    )
    return [r[0] for r in rows]


def can_access_business(db: Session, user: User, business_id: int) -> bool:
    if user.role == Role.SUPERUSER:
        return True
    return (
        db.query(UserBusinessAccess)
        .filter(
            UserBusinessAccess.user_id == user.id,
            UserBusinessAccess.business_id == business_id,
        )
        .first()
        is not None
    )


def accessible_store_ids(db: Session, user: User, business_id: Optional[int] = None) -> List[int]:
    """Store ids the user may act on.

    Superuser and business admins get all stores in their accessible businesses.
    Sales users are restricted to explicitly granted stores.
    """
    if user.role in (Role.SUPERUSER, Role.BUSINESS_ADMIN):
        biz_ids = accessible_business_ids(db, user)
        q = db.query(Store.id).filter(Store.business_id.in_(biz_ids or [-1]))
        if business_id is not None:
            q = q.filter(Store.business_id == business_id)
        return [r[0] for r in q.all()]

    # SALES: explicitly granted stores
    rows = (
        db.query(UserStoreAccess.store_id)
        .filter(UserStoreAccess.user_id == user.id)
        .all()
    )
    store_ids = [r[0] for r in rows]
    if business_id is not None and store_ids:
        store_ids = [
            s.id
            for s in db.query(Store.id)
            .filter(Store.id.in_(store_ids), Store.business_id == business_id)
            .all()
        ]
    return store_ids


def can_access_store(db: Session, user: User, store_id: int) -> bool:
    return store_id in accessible_store_ids(db, user)
