import base64
import hashlib
import hmac
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from sqlalchemy import delete, select, text
from sqlalchemy.exc import IntegrityError
from dovideo.errors import ApiError
from dovideo.models import AuthSession, LoginAttempt, User

USERNAME = re.compile(r"^[A-Za-z0-9_]{3,32}$")
ITERATIONS = 210_000

def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode().rstrip("=")

def _unb64(value: str) -> bytes:
    return base64.b64decode(value + "=" * (-len(value) % 4))

def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, ITERATIONS, 32)
    return f"pbkdf2${ITERATIONS}${_b64(salt)}${_b64(digest)}"

def password_matches(raw: str, stored: str) -> bool:
    if not stored.startswith("pbkdf2$"):
        return hmac.compare_digest(raw.encode(), stored.encode())
    try:
        prefix, iterations, salt, expected = stored.split("$")
        actual = hashlib.pbkdf2_hmac("sha256", raw.encode(), _unb64(salt), int(iterations), 32)
        return hmac.compare_digest(actual, _unb64(expected))
    except (ValueError, TypeError):
        return False

def user_view(user: User) -> dict:
    return {"id": str(user.id), "username": user.username, "nickname": user.nickname,
            "avatar": user.avatar, "role": user.role}

def register(session, data) -> dict:
    username = data.username.strip()
    nickname = data.nickname.strip()
    if not USERNAME.fullmatch(username) or not 8 <= len(data.password) <= 128:
        raise ApiError(400, "INVALID_REGISTRATION", "账号需为3-32位字母、数字或下划线，密码需为8-128位")
    if len(nickname) > 50:
        raise ApiError(400, "INVALID_NICKNAME", "昵称不能超过50个字符")
    user = User(id=uuid.uuid4(), username=username, password_hash=hash_password(data.password),
                nickname=nickname or f"用户{username}", role="USER")
    session.add(user)
    try:
        session.flush()
    except IntegrityError:
        raise ApiError(409, "USERNAME_EXISTS", "该账号已存在")
    return user_view(user)

def login(session, data, session_hours: int) -> dict:
    username = data.username.strip()
    # A transaction-scoped lock also serializes first attempts, before a row exists.
    session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                    {"key": "login:" + username})
    now = datetime.now(timezone.utc)
    attempt = session.get(LoginAttempt, username, with_for_update=True)
    if attempt and now - attempt.window_started_at < timedelta(minutes=10) and attempt.failures >= 8:
        raise ApiError(429, "LOGIN_RATE_LIMITED", "登录尝试过于频繁，请稍后再试")
    user = session.scalar(select(User).where(User.username == username))
    if user is None or not password_matches(data.password, user.password_hash):
        if attempt is None or now - attempt.window_started_at >= timedelta(minutes=10):
            if attempt is not None:
                session.delete(attempt)
                session.flush()
            session.add(LoginAttempt(username=username, failures=1, window_started_at=now))
        else:
            attempt.failures += 1
        raise ApiError(401, "INVALID_CREDENTIALS", "账号或密码错误")
    if attempt:
        session.delete(attempt)
    if not user.password_hash.startswith("pbkdf2$"):
        user.password_hash = hash_password(data.password)
    token = secrets.token_urlsafe(32)
    session.add(AuthSession(token_hash=hashlib.sha256(token.encode()).digest(), user_id=user.id,
                            expires_at=now + timedelta(hours=session_hours)))
    return {"token": token, "expiresIn": session_hours * 3600, "user": user_view(user)}

def resolve_user(session, token: str) -> User:
    token_hash = hashlib.sha256(token.encode()).digest()
    row = session.get(AuthSession, token_hash)
    now = datetime.now(timezone.utc)
    if row is None or row.expires_at <= now:
        if row is not None:
            session.delete(row)
        raise ApiError(401, "SESSION_EXPIRED", "登录状态已失效")
    user = session.get(User, row.user_id)
    if user is None:
        raise ApiError(401, "SESSION_EXPIRED", "登录状态已失效")
    return user

def logout(session, token: str):
    session.execute(delete(AuthSession).where(AuthSession.token_hash == hashlib.sha256(token.encode()).digest()))
