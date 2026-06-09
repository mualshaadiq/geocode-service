"""
Cascading hierarchy listing — read-only traversal of the administrative tree.

Implements the listing capability described in Design Doc GEO-1 v1.0: three
parent-scoped queries (provinces → districts → subdistricts) over the existing
`toponyms` collection. Returns identity only (GID code + name + full_path);
geometry resolution stays with the existing GET /geometry/{level}/{code} endpoint.

Per the RFC constraint that models.py remain untouched, the new Pydantic models
live here rather than in app/models.py.
"""
from typing import Optional

from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel

# ASSUMPTION: Indonesian locale ("id"), strength 2 (case-insensitive,
# diacritic-sensitive) for the alphabetical name sort. The Design Doc left the
# exact collation locale as an Open Question to settle in Implement. Engineer to
# confirm before merge.
_NAME_COLLATION = {"locale": "id", "strength": 2}

# Maps each listable level to (the GID field that is its own code,
# the parent GID field to filter on, the parent's level). province has no parent.
_LEVELS = {
    "province": {"code_field": "gid_1", "parent_field": None, "parent_level": None},
    "district": {"code_field": "gid_2", "parent_field": "gid_1", "parent_level": "province"},
    "subdistrict": {"code_field": "gid_3", "parent_field": "gid_2", "parent_level": "district"},
}


class ParentNotFoundError(Exception):
    """Raised when a requested parent area does not exist in the dataset.

    The route layer translates this into an HTTP 404. Kept framework-agnostic so
    HierarchyService has no dependency on FastAPI.
    """

    def __init__(self, level: str, code: str):
        self.level = level
        self.code = code
        super().__init__(f"No {level} found with code {code!r}")


class HierarchyItem(BaseModel):
    """One administrative area in a list response.

    Attributes:
        code: The GID for this area (gid_1/gid_2/gid_3 depending on level). This
            is the value the caller passes into GET /geometry/{level}/{code}.
        name: The area's display name.
        full_path: Comma-separated path up to Indonesia, for disambiguation.
        level: One of "province", "district", "subdistrict".
    """

    code: str
    name: str
    full_path: str
    level: str


class HierarchyListResponse(BaseModel):
    """A parent-scoped list of administrative areas at one level.

    Attributes:
        level: The level of the items in this response.
        parent: The parent GID the list was scoped to, or None for provinces.
        count: Number of items returned.
        items: The areas, sorted alphabetically by name.
    """

    level: str
    parent: Optional[str]
    count: int
    items: list[HierarchyItem]


class HierarchyService:
    """Parent-scoped, read-only traversal of the administrative hierarchy.

    Queries the existing toponyms collection using the gid_1/gid_2/gid_3 indexes
    created by the import script. Performs no writes and serves no geometry.
    """

    def __init__(self, db: AsyncIOMotorDatabase, collection: str = "toponyms"):
        """
        Args:
            db: The shared Motor database handle.
            collection: Name of the toponyms collection.
        """
        self.col = db[collection]

    async def list_provinces(self) -> HierarchyListResponse:
        """List every province, sorted alphabetically by name.

        Returns:
            HierarchyListResponse with level="province" and parent=None.
        """
        items = await self._children("province", parent=None)
        return HierarchyListResponse(
            level="province", parent=None, count=len(items), items=items
        )

    async def list_districts(self, province_gid: str) -> HierarchyListResponse:
        """List the districts within one province.

        Args:
            province_gid: The parent province's gid_1 (e.g. "IDN.7_1").

        Returns:
            HierarchyListResponse with level="district", scoped to province_gid.
            Empty items (still a normal response) if the province has no
            districts in the data.

        Raises:
            ParentNotFoundError: If no province with that gid_1 exists.
        """
        await self._require_parent("province", province_gid)
        items = await self._children("district", parent=province_gid)
        return HierarchyListResponse(
            level="district", parent=province_gid, count=len(items), items=items
        )

    async def list_subdistricts(self, district_gid: str) -> HierarchyListResponse:
        """List the subdistricts within one district.

        Args:
            district_gid: The parent district's gid_2 (e.g. "IDN.7.5_1").

        Returns:
            HierarchyListResponse with level="subdistrict", scoped to district_gid.
            Empty items if the district has no subdistricts in the data.

        Raises:
            ParentNotFoundError: If no district with that gid_2 exists.
        """
        await self._require_parent("district", district_gid)
        items = await self._children("subdistrict", parent=district_gid)
        return HierarchyListResponse(
            level="subdistrict", parent=district_gid, count=len(items), items=items
        )

    async def _require_parent(self, parent_level: str, code: str) -> None:
        """Raise ParentNotFoundError unless an area of parent_level with this GID exists.

        Distinguishing a non-existent parent (404) from a childless parent
        (empty 200 list) is a deliberate contract choice — see Design Doc
        "Tradeoffs". The check is a single indexed find_one.
        """
        cfg = _LEVELS[parent_level]
        doc = await self.col.find_one(
            {cfg["code_field"]: code, "level": parent_level}, {"_id": 1}
        )
        if doc is None:
            raise ParentNotFoundError(parent_level, code)

    async def _children(self, level: str, parent: Optional[str]) -> list[HierarchyItem]:
        """Query the areas at `level`, optionally scoped to a parent GID.

        Args:
            level: Child level to list ("province", "district", "subdistrict").
            parent: Parent GID to filter on, or None for top-level provinces.

        Returns:
            HierarchyItem list sorted alphabetically by name (collation).
        """
        cfg = _LEVELS[level]
        code_field = cfg["code_field"]

        query: dict = {"level": level}
        if cfg["parent_field"] is not None:
            query[cfg["parent_field"]] = parent

        # No pagination: worst-case result sets are small (see Design Doc
        # "Tradeoffs"), so we materialise the full sorted list.
        docs = await (
            self.col.find(query, {"_id": 0, code_field: 1, "name": 1, "full_path": 1})
            .collation(_NAME_COLLATION)
            .sort("name", 1)
            .to_list(length=None)
        )
        return [
            HierarchyItem(
                code=d[code_field],
                name=d["name"],
                full_path=d.get("full_path", d["name"]),
                level=level,
            )
            for d in docs
        ]
