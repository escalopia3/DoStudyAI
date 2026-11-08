import uuid
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field, field_validator
from dovideo.dependencies import current_user, get_session
from dovideo import knowledge
from typing import Literal
router = APIRouter(prefix='/api/v2',tags=['knowledge'])

class KnowledgeInput(BaseModel):
    query: str = Field(default='',max_length=2000)
    intent: Literal['auto','detail','overview'] = 'auto'
    resource_ids: list[uuid.UUID] = Field(default_factory=list,max_length=100)
    section_ids: list[str] = Field(default_factory=list,max_length=100)
    cursor: str | None = Field(default=None,max_length=4000)

@router.post('/courses/{course_id}/knowledge/query')
def query(course_id: uuid.UUID, data: KnowledgeInput, request: Request,
          session=Depends(get_session),user=Depends(current_user)):
    from dovideo.course_knowledge import query_course_knowledge
    return query_course_knowledge(session,request.app.state.storage,user,course_id,**data.model_dump())


class SearchInput(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    limit: int = Field(default=8, ge=1, le=30)

    @field_validator('question')
    @classmethod
    def meaningful(cls, value):
        if not value.strip():
            raise ValueError('Question is empty')
        return value.strip()

@router.post('/courses/{course_id}/knowledge/search')
def search(course_id: uuid.UUID, data: SearchInput, request: Request,
           session=Depends(get_session), user=Depends(current_user)):
    return knowledge.search(session, request.app.state.storage, user, course_id, data.question, data.limit)

@router.get('/courses/{course_id}/knowledge')
def status(course_id: uuid.UUID, session=Depends(get_session), user=Depends(current_user)):
    return knowledge.status(session, user, course_id)

@router.post('/resources/{resource_id}/indexes', status_code=202)
def rebuild(resource_id: uuid.UUID, session=Depends(get_session), user=Depends(current_user)):
    return knowledge.rebuild(session, user, resource_id)
