from enum import Enum

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import get_settings

security = HTTPBearer(auto_error=False)


class Principal(str, Enum):
    client = "client"
    researcher = "researcher"


async def require_client(
    creds: HTTPAuthorizationCredentials | None = Depends(security),
) -> Principal:
    if creds is None or creds.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    if creds.credentials != get_settings().client_secret:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid credentials",
        )
    return Principal.client


async def require_researcher(
    creds: HTTPAuthorizationCredentials | None = Depends(security),
) -> Principal:
    if creds is None or creds.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    if creds.credentials != get_settings().researcher_secret:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid credentials",
        )
    return Principal.researcher


async def require_any_study_user(
    creds: HTTPAuthorizationCredentials | None = Depends(security),
) -> Principal:
    if creds is None or creds.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    s = get_settings()
    if creds.credentials == s.client_secret:
        return Principal.client
    if creds.credentials == s.researcher_secret:
        return Principal.researcher
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Invalid credentials",
    )
