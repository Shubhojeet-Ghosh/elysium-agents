from pydantic import BaseModel, Field


class CreateDepartmentRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=256)
    description: str = Field(..., min_length=1, max_length=2000)
    team_id: str = Field(..., min_length=1, max_length=128)


class ListTeamDepartmentsRequest(BaseModel):
    team_id: str = Field(..., min_length=1, max_length=128)
