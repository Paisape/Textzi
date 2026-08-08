from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from database import Base, SessionLocal, engine
from routers.api import router
from services.company import ensure_seed

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Compucon", description="AI Agent IT Company OS — Chairman Baloda · Voice: Piki")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router, prefix="/api")

STATIC_DIR = Path(__file__).resolve().parent.parent / "web" / "dist"


@app.on_event("startup")
def startup():
    db = SessionLocal()
    try:
        ensure_seed(db)
    finally:
        db.close()


@app.get("/api/health")
def health():
    return {"ok": True, "company": "Compucon", "chairman": "Baloda", "voice": "Piki"}


if STATIC_DIR.exists():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

    @app.get("/{full_path:path}")
    def spa(full_path: str):
        index = STATIC_DIR / "index.html"
        candidate = STATIC_DIR / full_path
        if full_path and candidate.exists() and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(index)
