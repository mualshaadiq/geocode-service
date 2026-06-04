from pydantic import BaseModel
from typing import Any, Optional


class ToponymResult(BaseModel):
    name: str
    full_path: str
    level: str  # province | district | subdistrict
    gid_0: str
    gid_1: Optional[str] = None
    gid_2: Optional[str] = None
    gid_3: Optional[str] = None


class SearchResponse(BaseModel):
    results: list[ToponymResult]
    count: int
    query: str


class GeometryResult(BaseModel):
    code: str
    name: str
    level: str
    geometry: Optional[Any] = None  # GeoJSON geometry object
