from collections.abc import Generator
from fastapi import Depends, Header, Request
from sqlalchemy.orm import Session
from dovideo.business.auth import resolve_user
from dovideo.errors import ApiError

def get_session(request: Request) -> Generator[Session, None, None]:
    session = Session(request.app.state.storage.engine, expire_on_commit=False)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

def bearer_token(authorization: str | None = Header(default=None)) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise ApiError(401, "AUTH_REQUIRED", "请先登录")
    token = authorization[7:].strip()
    if len(token) < 32:
        raise ApiError(401, "INVALID_TOKEN", "无效的登录凭证")
    return token

def current_user(session: Session = Depends(get_session), token: str = Depends(bearer_token)):
    return resolve_user(session, token)
