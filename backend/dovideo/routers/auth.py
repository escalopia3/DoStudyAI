from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session
from dovideo.business import auth
from dovideo.dependencies import bearer_token, current_user, get_session
from dovideo.schemas import LoginInput, RegisterInput
from dovideo.errors import ApiError

router = APIRouter(prefix="/api/v2/auth", tags=["auth"])

@router.post("/register", status_code=201)
def register(data: RegisterInput, session: Session = Depends(get_session)):
    return auth.register(session, data)

@router.post("/login")
def login(data: LoginInput, request: Request, session: Session = Depends(get_session)):
    try:
        return auth.login(session, data, request.app.state.settings.session_hours)
    except ApiError as exc:
        if exc.code == 'INVALID_CREDENTIALS':
            session.commit()  # Persist failed attempts at the request transaction boundary.
        raise

@router.get("/me")
def me(user=Depends(current_user)):
    return auth.user_view(user)

@router.post("/logout", status_code=204)
def logout(session: Session = Depends(get_session), token: str = Depends(bearer_token)):
    auth.logout(session, token)
