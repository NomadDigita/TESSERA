from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time


class AuthError(RuntimeError):
    pass


ROLE_LEVEL = {"viewer": 10, "researcher": 20, "operator": 30, "admin": 40, "system_agent": 50}
USER_ROLES = {"viewer", "researcher", "operator", "admin"}


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def hash_password(password: str, *, salt: bytes | None = None) -> str:
    if len(password) < 12:
        raise ValueError("Password must contain at least 12 characters")
    salt = salt or secrets.token_bytes(16)
    derived = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt$16384$8$1${_b64(salt)}${_b64(derived)}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, n, r, p, salt, expected = encoded.split("$")
        if algorithm != "scrypt":
            return False
        actual = hashlib.scrypt(password.encode(), salt=_unb64(salt), n=int(n), r=int(r), p=int(p), dklen=32)
        return hmac.compare_digest(actual, _unb64(expected))
    except (ValueError, TypeError):
        return False


class AuthManager:
    def __init__(self, store, secret: str, ttl_seconds: int = 28800, clock=time.time) -> None:
        if len(secret) < 32:
            raise ValueError("JWT/session secret must contain at least 32 characters")
        self.store = store
        self.secret = secret.encode()
        self.ttl_seconds = ttl_seconds
        self.clock = clock

    def create_user(self, username: str, password: str, role: str) -> dict:
        username = username.strip().lower()
        if not username or role not in USER_ROLES:
            raise ValueError("Valid username and role are required")
        if self.store.get_user(username):
            raise ValueError("User already exists")
        user = {"username": username, "password_hash": hash_password(password), "role": role, "active": True}
        self.store.create_user(user)
        return {"username": username, "role": role, "active": True}

    def login(self, username: str, password: str) -> dict:
        user = self.store.get_user(username.strip().lower())
        if not user or not user["active"] or not verify_password(password, user["password_hash"]):
            raise AuthError("Invalid credentials")
        now = int(self.clock())
        payload = {"sub": user["username"], "role": user["role"], "iat": now, "exp": now + self.ttl_seconds, "jti": secrets.token_hex(12)}
        self.store.create_session({"jti": payload["jti"], "username": user["username"],
                                   "issued_at": now, "expires_at": payload["exp"]})
        encoded = _b64(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())
        signature = _b64(hmac.new(self.secret, encoded.encode(), hashlib.sha256).digest())
        return {"access_token": f"{encoded}.{signature}", "token_type": "bearer", "expires_in": self.ttl_seconds, "role": user["role"]}

    def verify(self, token: str) -> dict:
        try:
            encoded, signature = token.split(".", 1)
            expected = _b64(hmac.new(self.secret, encoded.encode(), hashlib.sha256).digest())
            if not hmac.compare_digest(signature, expected):
                raise AuthError("Invalid token signature")
            payload = json.loads(_unb64(encoded))
        except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise AuthError("Malformed token") from exc
        if int(payload.get("exp", 0)) <= int(self.clock()):
            raise AuthError("Token expired")
        session = self.store.get_session(str(payload.get("jti", "")))
        if not session or session.get("revoked_at") is not None:
            raise AuthError("Session is revoked")
        user = self.store.get_user(str(payload.get("sub", "")))
        if not user or not user["active"] or user["role"] != payload.get("role"):
            raise AuthError("User is inactive or permissions changed")
        return {"username": user["username"], "role": user["role"], "jti": payload["jti"],
                "expires_at": int(payload["exp"])}

    def logout(self, token: str) -> None:
        principal = self.verify(token)
        self.store.revoke_session(principal["jti"], int(self.clock()))

    def sessions(self, username: str) -> list[dict]:
        return self.store.list_active_sessions(username, int(self.clock()))

    def update_user(self, username: str, *, role: str | None = None,
                    active: bool | None = None) -> dict:
        username = username.strip().lower()
        user = self.store.get_user(username)
        if not user:
            raise ValueError("User not found")
        if role is not None and role not in USER_ROLES:
            raise ValueError("Invalid role")
        removes_admin = user["role"] == "admin" and (role not in {None, "admin"} or active is False)
        if removes_admin and self.store.active_admin_count() <= 1:
            raise ValueError("Cannot remove the last active administrator")
        updated = self.store.update_user(username, role=role, active=active)
        self.store.revoke_user_sessions(username, int(self.clock()))
        return {"username": updated["username"], "role": updated["role"], "active": updated["active"]}

    @staticmethod
    def require(principal: dict, minimum_role: str) -> None:
        if ROLE_LEVEL.get(principal.get("role"), -1) < ROLE_LEVEL[minimum_role]:
            raise AuthError("Insufficient permissions")
