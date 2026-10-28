"""MS-2 买家账号与登录（docs/17 T2.01）。

铁律（Global Constraints）：密码只存 hashlib.scrypt 摘要（salt 16B / n=2^14 / dklen=32）；
明文密码不落日志不入响应；登录失败统一文案不泄露账号存在性。
限频：每邮箱每分钟 5 次、每 IP 每分钟 10 次（进程内存态，超限 429）——MS-2 单实例口径。
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from collections import defaultdict, deque
from datetime import timedelta

from fastapi import APIRouter, HTTPException, Request, Response

from .models import AuthSession, User

SESSION_DAYS = 30
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _now(request: Request):
    return request.app.state.clock.now()


def hash_password(password: str, *, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32
    )
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _algo, salt_hex, _digest_hex = stored.split("$")
        bytes.fromhex(salt_hex)
    except ValueError:
        return False
    candidate = hash_password(password, salt=bytes.fromhex(salt_hex))
    return hmac.compare_digest(candidate, stored)


class RateLimiter:
    """滑动窗口计数（分钟级）；单进程内存态，MS-2 规模够用。"""

    def __init__(self):
        self._hits: dict[str, deque] = defaultdict(deque)

    def hit(self, key: str, limit: int, now) -> bool:
        """记一次并判定是否超限（True=放行）。"""
        bucket = self._hits[key]
        cutoff = now - timedelta(minutes=1)
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        bucket.append(now)
        return len(bucket) <= limit


def issue_session(session_factory, user_id: int, now) -> str:
    """签发会话（API login 与 Web 表单登录共用）：token 服务端持有，30 天。"""
    token = secrets.token_urlsafe(32)
    with session_factory() as s:
        s.add(AuthSession(token=token, user_id=user_id, created_at=now,
                          expires_at=now + timedelta(days=SESSION_DAYS)))
        s.commit()
    return token


def _validate(email: str, password: str) -> None:
    if not email or not _EMAIL_RE.match(email) or len(email) > 255:
        raise HTTPException(status_code=422, detail="邮箱格式不正确")
    if not 8 <= len(password) <= 128:
        raise HTTPException(status_code=422, detail="密码长度需在 8-128 位之间")


def register_auth_routes(app) -> None:
    router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
    app.state.auth_limiter = RateLimiter()

    def _client_ip(request: Request) -> str:
        """买家真实 IP：优先 X-Forwarded-For 首值（后端仅回环/内网可达，nginx 注入可信；
        无头（本地开发/测试）退回直连地址——否则全部买家共享 nginx 单 IP 桶）。"""
        xff = request.headers.get("x-forwarded-for", "")
        if xff:
            return xff.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    @router.post("/register", status_code=201)
    def register(body: dict, request: Request):
        email = str(body.get("email") or "").strip().lower()
        password = str(body.get("password") or "")
        _validate(email, password)
        limiter: RateLimiter = request.app.state.auth_limiter
        now = _now(request)
        if not limiter.hit(f"ip:{_client_ip(request)}", 10, now):
            raise HTTPException(status_code=429, detail="请求过于频繁，请稍后再试")
        with request.app.state.session_factory() as s:
            if s.query(User).filter_by(email=email).first() is not None:
                raise HTTPException(status_code=409, detail="邮箱已注册")
            user = User(email=email, password_hash=hash_password(password), created_at=now)
            s.add(user)
            s.commit()
            return {"user_id": user.id}

    @router.post("/login")
    def login(body: dict, request: Request, response: Response):
        email = str(body.get("email") or "").strip().lower()
        password = str(body.get("password") or "")
        limiter: RateLimiter = request.app.state.auth_limiter
        now = _now(request)
        if not limiter.hit(f"ip:{_client_ip(request)}", 10, now) or not limiter.hit(
            f"email:{email}", 5, now
        ):
            raise HTTPException(status_code=429, detail="请求过于频繁，请稍后再试")
        with request.app.state.session_factory() as s:
            user = s.query(User).filter_by(email=email).first()
            if user is None or not verify_password(password, user.password_hash):
                raise HTTPException(status_code=401, detail="邮箱或密码错误")
            token = issue_session(request.app.state.session_factory, user.id, now)
            response.set_cookie(
                "forge_sid", token, httponly=True, samesite="lax",
                max_age=SESSION_DAYS * 86400,
            )
            return {"token": token, "user_id": user.id}

    @router.post("/logout")
    def logout(request: Request):
        token = _bearer_token(request)
        if token:
            with request.app.state.session_factory() as s:
                session = s.query(AuthSession).filter_by(token=token).first()
                if session is not None:
                    s.delete(session)
                    s.commit()
        return Response(status_code=204)

    app.include_router(router)


def _bearer_token(request: Request) -> str | None:
    header = request.headers.get("authorization") or ""
    if header.lower().startswith("bearer "):
        return header[7:].strip() or None
    return None


def _session_token(request: Request) -> str | None:
    return _bearer_token(request) or request.cookies.get("forge_sid")


def current_user(request: Request) -> User:
    """会话解析依赖：Bearer 或 Cookie 任一通道；供 T2.02/03/04 路由复用。"""
    token = _session_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="请先登录")
    now = _now(request)
    with request.app.state.session_factory() as s:
        session = s.query(AuthSession).filter_by(token=token).first()
        if session is None or session.expires_at <= now:
            raise HTTPException(status_code=401, detail="登录已失效，请重新登录")
        user = s.get(User, session.user_id)
        if user is None:
            raise HTTPException(status_code=401, detail="登录已失效，请重新登录")
        return user


def register_me_routes(app) -> None:
    router = APIRouter(prefix="/api/v1", tags=["auth"])

    @router.get("/me")
    def me(request: Request):
        user = current_user(request)
        return {"user_id": user.id, "email": user.email}

    app.include_router(router)
