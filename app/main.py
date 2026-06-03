from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Query
from motor.motor_asyncio import AsyncIOMotorClient

from .config import settings
from .models import SearchResponse
from .search import ToponymSearch

_search: Optional[ToponymSearch] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _search
    client = AsyncIOMotorClient(settings.mongodb_url)
    db = client[settings.mongodb_db]
    _search = ToponymSearch(db, settings.collection_name)
    await _search.ensure_index()
    yield
    client.close()


app = FastAPI(
    title="Indonesian Geocode Search",
    description="Full-text search over Indonesian administrative toponyms (province/district/subdistrict).",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/search", response_model=SearchResponse)
async def search(
    q: str = Query(..., min_length=2, description="Place name — can include multiple levels, e.g. 'ajasari bandung'"),
    limit: int = Query(5, ge=1, le=20),
):
    results = await _search.search(q, limit)
    return SearchResponse(results=results, count=len(results), query=q)


@app.get("/health")
async def health():
    return {"status": "ok"}
