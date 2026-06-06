from typing import Literal

from pydantic import BaseModel, EmailStr, Field

EmailUserRole = Literal["admin", "member"]


class CreateEmailUserRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=256)
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    team_id: str = Field(..., min_length=1, max_length=128)
    department_id: str = Field(..., min_length=1, max_length=128)
    role: EmailUserRole


class LoginEmailUserRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1, max_length=128)


class ListTeamUsersRequest(BaseModel):
    team_id: str = Field(..., min_length=1, max_length=128)
