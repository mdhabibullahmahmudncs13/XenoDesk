"""Auth request/response schemas."""

import uuid

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: str = Field(min_length=8, max_length=256)


class SignupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    business_name: str = Field(min_length=1, max_length=255)
    name: str = Field(min_length=1, max_length=255)
    email: EmailStr
    password: str = Field(min_length=8, max_length=256)


class BusinessSummary(BaseModel):
    id: uuid.UUID
    name: str
    timezone: str
    currency: str


class MembershipResponse(BaseModel):
    business: BusinessSummary
    role: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user_id: uuid.UUID
    business_id: uuid.UUID
    role: str


class MeResponse(BaseModel):
    user_id: uuid.UUID
    email: str
    name: str
    role: str
    business: BusinessSummary
