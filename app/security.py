from datetime import datetime, timedelta

from jose import jwt, JWTError
from passlib.context import CryptContext

from .config import settings

pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
ALGO = "HS256"


def hash_password(p: str) -> str:
    return pwd.hash(p)


def verify_password(p: str, h: str) -> bool:
    try:
        return pwd.verify(p, h)
    except Exception:
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
