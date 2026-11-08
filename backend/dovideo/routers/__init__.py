from .auth import router as auth_router
from .courses import router as courses_router
from .resources import router as resources_router
from .knowledge import router as knowledge_router
from .agents import router as agents_router

ALL_ROUTERS = (auth_router, courses_router, resources_router, knowledge_router, agents_router)
