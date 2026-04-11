from __future__ import annotations

from dataclasses import dataclass

from fastapi import Header, HTTPException, status


@dataclass(slots=True)
class BearerTokenAuth:
    token: str

    def is_authorized(self, authorization: str | None) -> bool:
        if not authorization:
            return False
        prefix = "Bearer "
        if not authorization.startswith(prefix):
            return False
        supplied = authorization[len(prefix):].strip()
        return supplied == self.token

    def assert_authorized(self, authorization: str | None) -> None:
        if not self.is_authorized(authorization):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or missing bearer token",
                headers={"WWW-Authenticate": "Bearer"},
            )


def bearer_token_dependency(token: str):
    auth = BearerTokenAuth(token=token)

    async def dependency(authorization: str | None = Header(default=None)) -> None:
        auth.assert_authorized(authorization)

    return dependency

