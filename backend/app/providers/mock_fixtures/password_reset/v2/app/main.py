"""Customer Portal API entry point."""
from contextlib import asynccontextmanager

from fastapi import FastAPI

from . import auth, config, password_reset
from .db import init_db


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="Customer Portal API", version=config.APP_VERSION, lifespan=lifespan)
app.include_router(auth.router)
app.include_router(password_reset.router)


@app.get("/health")
def health():
    return {"status": "ok", "version": config.APP_VERSION}
