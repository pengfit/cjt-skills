"""JWT + bcrypt 鉴权(2026-07-19)

设计:
  - 单 admin(env 注入 ADMIN_USER / ADMIN_HASH,无 db)
  - JWT HS256,默认 24h 过期
  - 全局 dependency:get_current_user 验证 Authorization Bearer
  - 公开路由仅 /api/auth/login 与 /api/health(后者给 docker healthcheck)

依赖(已加 requirements.txt):
  python-jose[cryptography]>=3.3
  bcrypt>=4.0
"""
import os
import time
from typing import Optional

import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError

# ── 配置 ─────────────────────────────────────────────────────────────────────
JWT_SECRET = os.environ.get("JWT_SECRET", "").strip()
JWT_ALG = "HS256"
JWT_EXP_SECONDS = int(os.environ.get("JWT_EXP_SECONDS", "86400"))  # 24h

ADMIN_USER = os.environ.get("ADMIN_USER", "admin").strip()
ADMIN_HASH = os.environ.get("ADMIN_HASH", "").strip()

if not JWT_SECRET:
    raise RuntimeError("JWT_SECRET 环境变量未设置,服务拒绝启动")
if not ADMIN_HASH:
    raise RuntimeError("ADMIN_HASH 环境变量未设置,服务拒绝启动")

# bcrypt hash 必须以 $2 开头
if not ADMIN_HASH.startswith(("$2a$", "$2b$", "$2y$")):
    raise RuntimeError("ADMIN_HASH 不是合法 bcrypt hash(需 $2a/$2b/$2y 开头)")

# OAuth2PasswordBearer 只为 Swagger UI / OpenAPI schema 生成正确的 tokenUrl,
# 实际验证在 get_current_user 中完成(token 通过 header 读)
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)


# ── 密码工具 ────────────────────────────────────────────────────────────────
def verify_admin(username: str, password: str) -> bool:
    """核对用户名密码(目前只支持单 admin)"""
    if username != ADMIN_USER:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), ADMIN_HASH.encode("utf-8"))
    except Exception:
        return False


# ── JWT ─────────────────────────────────────────────────────────────────────
def create_access_token(sub: str, role: str = "admin") -> str:
    payload = {
        "sub": sub,
        "role": role,
        "iat": int(time.time()),
        "exp": int(time.time()) + JWT_EXP_SECONDS,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)


def decode_token(token: str) -> dict:
    """解 JWT,过期/无效抛 HTTPException 401"""
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])
    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"invalid token: {e}",
            headers={"WWW-Authenticate": "Bearer"},
        )


# ── FastAPI Dependency ──────────────────────────────────────────────────────
async def get_current_user(token: Optional[str] = Depends(oauth2_scheme)) -> dict:
    """全局依赖:校验 Authorization Bearer,返回 {sub, role}"""
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return decode_token(token)


def require_admin(user: dict = Depends(get_current_user)) -> dict:
    """role 校验(目前只有 admin,留接口给将来扩展)"""
    if user.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="admin only",
        )
    return user