from __future__ import annotations
from fastapi import APIRouter, HTTPException, status, Depends
from app.models import LoginRequest, TokenResponse, UserRole, UserCreate, UserOut
from app.cache import store
from app.auth import verify_password, create_access_token, hash_password, require_role

router = APIRouter(prefix="/api/auth", tags=["认证"])


@router.post("/login", response_model=TokenResponse)
def login(req: LoginRequest):
    user = None
    for u in store.users.values():
        if u["username"] == req.username:
            user = u
            break
    if not user or not verify_password(req.password, user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
        )
    token = create_access_token(user["id"], user["role"])
    return TokenResponse(access_token=token)


@router.post("/users", response_model=UserOut)
def create_user(req: UserCreate, current_user: dict = Depends(require_role(UserRole.admin))):
    for u in store.users.values():
        if u["username"] == req.username:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="用户名已存在",
            )
    user_id = store.next_id("user")
    user = {
        "id": user_id,
        "username": req.username,
        "password_hash": hash_password(req.password),
        "role": req.role,
    }
    store.users[user_id] = user
    return UserOut(id=user["id"], username=user["username"], role=user["role"])
