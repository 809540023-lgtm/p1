from __future__ import annotations

import secrets
from dataclasses import dataclass
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from school_platform.schemas import AuthSessionResponse, AuthUserResponse, UserAccount
from school_platform.store import store

security = HTTPBearer(auto_error=False)


@dataclass
class SessionRecord:
    token: str
    user_id: UUID


class AuthService:
    def __init__(self) -> None:
        self.sessions: dict[str, SessionRecord] = {}

    def authenticate(self, email: str, password: str) -> AuthSessionResponse:
        user = store.get_user_by_email(email)
        if user is None or user.password_hash != store.hash_password(password):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
        if user.status != "active":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User is inactive")

        token = secrets.token_urlsafe(32)
        self.sessions[token] = SessionRecord(token=token, user_id=user.id)
        return AuthSessionResponse(access_token=token, user=self._to_user_response(user))

    def logout(self, token: str) -> None:
        self.sessions.pop(token, None)

    def current_user(self, token: str | None) -> UserAccount:
        if not token or token not in self.sessions:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
        session = self.sessions[token]
        user = store.get_user_by_id(session.user_id)
        if user is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session user not found")
        return user

    def _to_user_response(self, user: UserAccount) -> AuthUserResponse:
        return AuthUserResponse(
            id=user.id,
            email=user.email,
            name=user.name,
            role=user.role,
            permissions=user.permissions,
            staff_id=user.staff_id,
            parent_user_id=user.parent_user_id,
            account_type=user.account_type,
            scope_label=user.scope_label,
        )


auth_service = AuthService()


def get_current_user(credentials: HTTPAuthorizationCredentials | None = Depends(security)) -> UserAccount:
    token = credentials.credentials if credentials else None
    return auth_service.current_user(token)


def require_roles(*roles: str):
    def dependency(user: UserAccount = Depends(get_current_user)) -> UserAccount:
        if "*" in user.permissions:
            return user
        if roles and user.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")
        return user

    return dependency


def current_token(credentials: HTTPAuthorizationCredentials | None = Depends(security)) -> str:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    return credentials.credentials
