from fastapi import Security, HTTPException, status, Depends
from fastapi.security import APIKeyHeader, HTTPBearer, HTTPAuthorizationCredentials
import jwt
from datetime import datetime, timedelta
from app.core.config import settings

api_key_header = APIKeyHeader(name="X-API-KEY", auto_error=False)
security = HTTPBearer()

async def get_api_key(api_key_header: str = Security(api_key_header)):
    if api_key_header == settings.ADAPTER_API_KEY:
        return api_key_header
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Could not validate credentials",
    )

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(seconds=3600) # Hardcoded expiry for now, or use config
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.JWT_SECRET, algorithm="HS256")
    return encoded_jwt

async def verify_jwt(credentials: HTTPAuthorizationCredentials = Security(security)):
    try:
        payload = jwt.decode(credentials.credentials, settings.JWT_SECRET, algorithms=["HS256"])
        username: str = payload.get("sub")
        if username is None:
            raise HTTPException(status_code=403, detail="Invalid token")
        return username
    except jwt.PyJWTError:
        raise HTTPException(status_code=403, detail="Invalid token")
