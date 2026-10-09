from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.db import Base, SessionLocal, engine
from app.core.tenancy import ensure_demo_org
from app.routers import auth, dashboard, health, incidents, ingest, org, runs


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Phase 0 convenience: create tables directly. Replace with Alembic later.
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        ensure_demo_org(db)
    yield


app = FastAPI(title="Incident Investigator API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,  # explicit origins: credentials forbid "*"
    allow_credentials=True,  # the session cookie identifies the reviewer
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(incidents.router)
app.include_router(runs.router)
app.include_router(dashboard.router)
app.include_router(org.router)
app.include_router(ingest.router)
