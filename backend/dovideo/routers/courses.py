import uuid
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from dovideo.business import courses
from dovideo.dependencies import current_user, get_session
from dovideo.schemas import ChapterInput, CourseInput

router = APIRouter(prefix="/api/v2/courses", tags=["courses"])

@router.get("")
def list_courses(page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=100),
                 session: Session = Depends(get_session), user=Depends(current_user)):
    return courses.list_courses(session, user, page, size)

@router.post("", status_code=201)
def create_course(data: CourseInput, session: Session = Depends(get_session), user=Depends(current_user)):
    return courses.create(session, user, data)

@router.get("/{course_id}")
def course_detail(course_id: uuid.UUID, session: Session = Depends(get_session), user=Depends(current_user)):
    return courses.detail(session, user, course_id)

@router.put('/{course_id}')
def update_course(course_id: uuid.UUID, data: CourseInput, session=Depends(get_session), user=Depends(current_user)):
    course = courses.require_owned_course(session, course_id, user.id)
    if not data.name.strip():
        from dovideo.errors import ApiError
        raise ApiError(400, 'INVALID_NAME', '课程名称不能为空')
    course.name, course.semester, course.description = data.name.strip(), data.semester.strip(), data.description.strip()
    return courses.course_view(course, 'OWNER')

@router.post("/{course_id}/chapters", status_code=201)
def add_chapter(course_id: uuid.UUID, data: ChapterInput, session: Session = Depends(get_session), user=Depends(current_user)):
    return courses.add_chapter(session, user, course_id, data)
