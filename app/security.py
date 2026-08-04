from datetime import datetime, timedelta, timezone

from collections.abc import Callable

from fastapi import HTTPException, Request, status
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import User


pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)


def create_session_token(user: User, settings: Settings) -> str:
    payload = {
        "sub": str(user.id),
        "role": user.role,
        "exp": datetime.now(timezone.utc) + timedelta(hours=12),
    }
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def get_current_user(request: Request, session: Session, settings: Settings) -> User:
    token = request.cookies.get(settings.session_cookie_name)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required"
        )
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
        user_id = int(payload["sub"])
    except (JWTError, KeyError, TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required"
        ) from None
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required"
        )
    return user


def make_role_dependency(
    session_factory: Callable[[], Session],
    settings: Settings,
    required_role: str | None = None,
) -> Callable[[Request], User]:
    def dependency(request: Request) -> User:
        session = session_factory()
        try:
            user = get_current_user(request, session, settings)
            if required_role and user.role != required_role:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Admin access required",
                )
            return user
        finally:
            session.close()

    return dependency
