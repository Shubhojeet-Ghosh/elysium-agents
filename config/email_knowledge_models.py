from pydantic import BaseModel, Field


class CreateEmailKnowledgeRequest(BaseModel):
    team_id: str = Field(..., min_length=1, max_length=128)
    title: str = Field(..., min_length=1, max_length=256)
    knowledge_text: str = Field(..., min_length=1, max_length=500_000)


class ListTeamEmailKnowledgeRequest(BaseModel):
    team_id: str = Field(..., min_length=1, max_length=128)


class DeleteEmailKnowledgeRequest(BaseModel):
    knowledge_id: str = Field(..., min_length=1, max_length=128)


class QueryEmailKnowledgeRequest(BaseModel):
    knowledge_id: str = Field(..., min_length=1, max_length=128)
    query: str = Field(..., min_length=1, max_length=10_000)
