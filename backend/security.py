# -*- coding: utf-8 -*-
"""认证与鉴权：口令哈希、登录令牌、角色校验。不依赖第三方加密库。"""
import hashlib
import hmac
import os
import secrets

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from . import models
from .database import get_db

_PBKDF2_ROUNDS = 200_000


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ROUNDS)
    return f"pbkdf2_sha256${_PBKDF2_ROUNDS}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, rounds, salt_hex, hash_hex = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt_hex), int(rounds)
        )
        return hmac.compare_digest(dk.hex(), hash_hex)
    except Exception:
        return False


def new_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def get_current_user(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> models.User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "缺少登录令牌")
    token = authorization.split(" ", 1)[1].strip()
    api_token = (
        db.query(models.ApiToken)
        .filter(models.ApiToken.token_hash == hash_token(token))
        .one_or_none()
    )
    if api_token is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "令牌无效或已失效")
    user = api_token.user
    if not user or not user.active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "账号不可用")
    return user


def require_roles(*roles: str):
    allowed = set(roles)

    def checker(user: models.User = Depends(get_current_user)) -> models.User:
        if user.role not in allowed:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"当前岗位 {user.role} 无权执行该操作",
            )
        return user

    return checker
