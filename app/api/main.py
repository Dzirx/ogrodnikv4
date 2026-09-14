import secrets

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from app.api.routes import router
from app.config import settings

_security = HTTPBasic()


def verify(credentials: HTTPBasicCredentials = Depends(_security)) -> str:
    ok_user = secrets.compare_digest(credentials.username, settings.auth_username)
    ok_pass = secrets.compare_digest(credentials.password, settings.auth_password)
    if not (ok_user and ok_pass):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Błędny login lub hasło",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


app = FastAPI(title="Ogrodnik", dependencies=[Depends(verify)])
app.include_router(router)
