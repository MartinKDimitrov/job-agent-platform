"""Encrypted per-user BYOK key storage.

API keys are encrypted at rest with Fernet, using a key derived from the app SECRET_KEY —
compromising the DB alone does not expose user keys. The plaintext key exists only in memory
at generation time; it is never logged and never rendered back to the browser.
"""
from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.orm import Session

from ..core.config import settings
from .models import UserLLMConfig


def _fernet() -> Fernet:
    digest = hashlib.sha256(settings.secret_key.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_key(plaintext: str) -> str:
    if not plaintext:
        return ""
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_key(token: str) -> str:
    if not token:
        return ""
    try:
        return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken:
        return ""   # SECRET_KEY changed or data corrupted -> treat as "no key configured"


def save_config(db: Session, user_id: int, provider: str, api_key: str, model: str = "") -> None:
    cfg = db.get(UserLLMConfig, user_id)
    if cfg is None:
        cfg = UserLLMConfig(user_id=user_id, provider=provider)
        db.add(cfg)
    cfg.provider = provider
    cfg.encrypted_key = encrypt_key(api_key)
    cfg.model = model or ""
    db.commit()


def get_config(db: Session, user_id: int) -> dict | None:
    """Return {provider, api_key (plaintext), model} or None. Callers must not log api_key."""
    cfg = db.get(UserLLMConfig, user_id)
    if cfg is None:
        return None
    return {"provider": cfg.provider, "api_key": decrypt_key(cfg.encrypted_key),
            "model": cfg.model}


def delete_config(db: Session, user_id: int) -> None:
    cfg = db.get(UserLLMConfig, user_id)
    if cfg is not None:
        db.delete(cfg)
        db.commit()
