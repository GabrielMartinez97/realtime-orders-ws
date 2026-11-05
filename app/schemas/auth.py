"""Esquemas Pydantic v2 para Autenticación y Tokens JWT."""

from pydantic import BaseModel, EmailStr, Field
from app.schemas.user import UserRead


class LoginRequest(BaseModel):
    """Credenciales de inicio de sesión."""

    email: EmailStr
    password: str = Field(..., min_length=6, max_length=128)


class TokenResponse(BaseModel):
    """Respuesta emitida al autenticar un usuario exitosamente."""

    access_token: str
    token_type: str = "bearer"
    user: UserRead
