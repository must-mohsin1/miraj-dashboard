"""Authentication routes — register, login, and a protected health-check."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth import (
    create_access_token,
    get_current_user,
    hash_password,
    verify_password,
)
from backend.database import get_session
from backend.models import User
from backend.schemas import (
    TokenResponse,
    UserRegisterRequest,
    UserLoginRequest,
    UserResponse,
)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register(body: UserRegisterRequest, session: AsyncSession = Depends(get_session)) -> User:
    """Register a new user account."""
    # Check for existing username or email
    result = await session.execute(
        select(User).where(
            (User.username == body.username) | (User.email == body.email)
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username or email already taken",
        )

    user = User(
        username=body.username,
        email=body.email,
        hashed_password=hash_password(body.password),
    )
    session.add(user)
    await session.flush()  # get the auto-generated id
    await session.refresh(user)
    return user


@router.post("/login", response_model=TokenResponse)
async def login(body: UserLoginRequest, session: AsyncSession = Depends(get_session)) -> dict:
    """Authenticate and return a JWT access token."""
    result = await session.execute(
        select(User).where(User.username == body.username)
    )
    user = result.scalar_one_or_none()
    if user is None or not verify_password(body.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    token = create_access_token(data={"sub": str(user.id)})
    return {"access_token": token, "token_type": "bearer"}


@router.get("/me", response_model=UserResponse)
async def me(current_user: User = Depends(get_current_user)) -> User:
    """Return the authenticated user's profile."""
    return current_user
