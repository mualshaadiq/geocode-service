from motor.motor_asyncio import AsyncIOMotorDatabase
from .models import ToponymResult


class ToponymSearch:
    def __init__(self, db: AsyncIOMotorDatabase, collection: str = "toponyms"):
        self.col = db[collection]

    async def ensure_index(self) -> None:
        existing = await self.col.index_information()
        if "search_text_index" not in existing:
            await self.col.create_index(
                [("search_text", "text")],
                name="search_text_index",
                default_language="none",
            )

    async def search(self, query: str, limit: int = 5) -> list[ToponymResult]:
        cursor = (
            self.col.find(
                {"$text": {"$search": query}},
                {"score": {"$meta": "textScore"}, "_id": 0},
            )
            .sort([("score", {"$meta": "textScore"})])
            .limit(limit)
        )
        docs = await cursor.to_list(limit)
        return [
            ToponymResult(
                name=doc["name"],
                full_path=doc.get("full_path", doc["name"]),
                level=doc["level"],
                gid_0=doc["gid_0"],
                gid_1=doc.get("gid_1"),
                gid_2=doc.get("gid_2"),
                gid_3=doc.get("gid_3"),
            )
            for doc in docs
        ]
