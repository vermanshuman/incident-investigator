from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.db import Base, engine
from app.routers import health, incidents, runs


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Phase 0 convenience: create tables directly. Replace with Alembic in Phase 1.
    Base.metadata.create_all(engine)
    yield


app = FastAPI(title="Incident Investigator API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(incidents.router)
app.include_router(runs.router)
