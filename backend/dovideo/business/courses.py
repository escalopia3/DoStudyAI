import uuid
from sqlalchemy import func, select
from dovideo.errors import ApiError
from dovideo.models import Course, CourseChapter, Resource, CourseResource

def require_owned_course(session, course_id, user_id):
    course = session.scalar(select(Course).where(Course.id == course_id, Course.created_by == user_id))
    if course is None:
        raise ApiError(404, "COURSE_NOT_FOUND", "课程不存在")
    return course

def create(session, user, data):
    if not data.name.strip():
        raise ApiError(400, 'INVALID_NAME', '课程名称不能为空')
    course = Course(id=uuid.uuid4(), name=data.name.strip(), semester=data.semester.strip(),
                    description=data.description.strip(), created_by=user.id)
    session.add(course)
    session.flush()
    return course_view(course, "OWNER", 0)

def course_view(course, role, resource_count=0):
    return {"id": str(course.id), "name": course.name, "semester": course.semester,
            "description": course.description, "resourceCount": resource_count}

def list_courses(session, user, page, size):
    if page < 1 or size < 1 or size > 100:
        raise ApiError(400, "INVALID_PAGE", "分页参数无效")
    count = func.count(CourseResource.resource_id).label("resources")
    query = (select(Course, count)
             .outerjoin(CourseResource, CourseResource.course_id == Course.id)
             .where(Course.created_by == user.id).group_by(Course.id)
             .order_by(Course.created_at.desc()).limit(size).offset((page - 1) * size))
    rows = session.execute(query).all()
    total = session.scalar(select(func.count()).select_from(Course).where(Course.created_by == user.id))
    return {"items": [course_view(c, "OWNER", n) for c, n in rows], "page": page, "size": size, "total": total}

def detail(session, user, course_id):
    require_owned_course(session, course_id, user.id)
    course = session.get(Course, course_id)
    chapters = session.scalars(select(CourseChapter).where(CourseChapter.course_id == course_id).order_by(CourseChapter.sort_order)).all()
    result = course_view(course, "OWNER")
    result["chapters"] = [{"id": str(c.id), "name": c.name, "sortOrder": c.sort_order} for c in chapters]
    return result

def add_chapter(session, user, course_id, data):
    if not data.name.strip():
        raise ApiError(400, 'INVALID_NAME', '章节名称不能为空')
    require_owned_course(session, course_id, user.id)
    session.get(Course, course_id, with_for_update=True)
    order = session.scalar(select(func.coalesce(func.max(CourseChapter.sort_order), 0) + 1).where(CourseChapter.course_id == course_id))
    chapter = CourseChapter(id=uuid.uuid4(), course_id=course_id, name=data.name.strip(), sort_order=order)
    session.add(chapter)
    return {"id": str(chapter.id), "name": chapter.name, "sortOrder": order}
