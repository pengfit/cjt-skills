"""登录端点(2026-07-19)

POST /api/auth/login
  body: x-www-form-urlencoded (OAuth2 Password Flow)
    username=admin
    password=***
  resp: {"access_token": "...", "token_type": "bearer", "expires_in": 86400}

GET /api/auth/me
  header: Authorization Bearer ...
  resp: {"username": "admin", "role": "admin"}
"""
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm

from api.auth import (
    create_access_token,
    decode_token,
    get_current_user,
    verify_admin,
    JWT_EXP_SECONDS,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login")
async def login(form: OAuth2PasswordRequestForm = Depends()):
    """登录:校验用户名密码,返回 JWT"""
    if not verify_admin(form.username, form.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = create_access_token(sub=form.username, role="admin")
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": JWT_EXP_SECONDS,
        "username": form.username,
        "role": "admin",
    }


@router.get("/me")
async def me(user: dict = Depends(get_current_user)):
    """验证 token 是否有效,返回当前用户信息"""
    return {"username": user["sub"], "role": user.get("role", "admin")}


@router.post("/logout")
async def logout(_: dict = Depends(get_current_user)):
    """JWT 无状态,前端清除本地 token 即视为登出。后端保留接口便于将来加黑名单。"""
    return {"ok": True}