from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.database import init_db
from src.routers import buckets, multipart, objects


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(lifespan=lifespan)
app.include_router(buckets.router)
app.include_router(objects.router)
app.include_router(multipart.router)
