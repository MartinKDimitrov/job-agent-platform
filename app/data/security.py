from datetime import datetime, timedelta

import bcrypt
from jose import jwt, JWTError

from ..core.config import settings

ALGO = "HS256"

# bcrypt only considers the first 72 bytes of the password; bcrypt >= 4 raises on longer
# input instead of truncating, so we cap explicitly. (We use the bcrypt library directly
# rather than passlib: passlib 1.7.4's backend probe crashes against bcrypt 5.x.)
def hash_password(p: str) -> str:
    return bcrypt.hashpw(p.encode("utf-8")[:72], bcrypt.gensalt()).decode("utf-8")


def verify_password(p: str, h: str) -> bool:
    try:
        return bcrypt.checkpw(p.encode("utf-8")[:72], h.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def make_token(user_id: int) -> str:
    exp = datetime.utcnow() + timedelta(minutes=settings.access_token_minutes)
    return jwt.encode({"sub": str(user_id), "exp": exp}, settings.secret_key, algorithm=ALGO)


def read_token(token: str) -> int | None:
    try:
        data = jwt.decode(token, settings.secret_key, algorithms=[ALGO])
        return int(data["sub"])
    except (JWTError, KeyError, ValueError):
        return None
