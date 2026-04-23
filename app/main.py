from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.db import Base, engine
from app.routes.capabilities import router as capability_router
from app.routes.mandates import router as mandate_router
from app.routes.projects import router as project_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title="Execution Governor UI v0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="app/static"), name="static")

templates = Jinja2Templates(directory="app/templates")
app.state.templates = templates

app.include_router(project_router)
app.include_router(capability_router)
app.include_router(mandate_router)


@app.get("/health")
def health():
    return {"status": "ok"}
