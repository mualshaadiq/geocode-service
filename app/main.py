from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from motor.motor_asyncio import AsyncIOMotorClient

from .config import settings
from .models import GeometryResult, SearchResponse
from .search import ToponymSearch

_search: Optional[ToponymSearch] = None
_db = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _search, _db
    client = AsyncIOMotorClient(settings.mongodb_url)
    _db = client[settings.mongodb_db]
    _search = ToponymSearch(_db, settings.collection_name)
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


_LEVEL_GID_FIELD = {
    "province": "gid_1",
    "district": "gid_2",
    "subdistrict": "gid_3",
}


@app.get("/geometry/{level}/{code}", response_model=GeometryResult)
async def get_geometry(level: str, code: str):
    """Return the stored GeoJSON geometry for an administrative area by GID code."""
    gid_field = _LEVEL_GID_FIELD.get(level)
    if not gid_field:
        raise HTTPException(status_code=400, detail=f"Unknown level '{level}'. Use: province, district, subdistrict")

    col = _db[settings.collection_name]
    doc = await col.find_one(
        {gid_field: code},
        {"_id": 0, "name": 1, "level": 1, "geometry": 1},
    )
    if not doc:
        raise HTTPException(status_code=404, detail=f"No {level} found with {gid_field}={code!r}")

    return GeometryResult(
        code=code,
        name=doc.get("name", ""),
        level=doc.get("level", level),
        geometry=doc.get("geometry"),
    )


@app.get("/health")
async def health():
    return {"status": "ok"}
