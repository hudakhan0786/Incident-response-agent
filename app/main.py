import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.database import Base, SessionLocal, engine
from app.routers import dashboard, incidents, postmortems, runbooks, search
from app.seed_data import seed
from app import hindsight_memory

Base.metadata.create_all(bind=engine)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if hindsight_memory.enabled():
        hindsight_memory.initialize_bank()
    db = SessionLocal()
    try:
        seed(db)
    finally:
        db.close()
    yield


app = FastAPI(
    title="Incident Response Agent",
    description="Remembers past incidents, root causes and runbooks - and learns which fixes actually worked.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(incidents.router)
app.include_router(runbooks.router)
app.include_router(search.router)
app.include_router(dashboard.router)
app.include_router(postmortems.router)


STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
app.mount("/assets", StaticFiles(directory=STATIC_DIR), name="assets")


@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.get("/api/health")
def health():
    return {"status": "ok", "hindsight": hindsight_memory.status()}
