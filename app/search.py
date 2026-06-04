import re
from difflib import SequenceMatcher

from motor.motor_asyncio import AsyncIOMotorDatabase

from .models import ToponymResult

_LEVEL_DEPTH = {"subdistrict": 3, "district": 2, "province": 1}


def _doc_key(doc: dict) -> str:
    return doc.get("gid_3") or doc.get("gid_2") or doc.get("gid_1") or doc.get("name", "")


def _name_sim(tokens: list[str], name: str) -> float:
    name_lower = name.lower()
    return max(SequenceMatcher(None, t, name_lower).ratio() for t in tokens)


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
        tokens = [t.lower() for t in query.split() if t]
        if not tokens:
            return []

        # ── Phase 1: $text search (fast, exact-word match) ────────────────────
        text_docs: list[dict] = await (
            self.col.find(
                {"$text": {"$search": query}},
                {"score": {"$meta": "textScore"}, "_id": 0},
            )
            .sort([("score", {"$meta": "textScore"})])
            .limit(limit * 4)
            .to_list(limit * 4)
        )

        # ── Phase 2: regex fallback on name ───────────────────────────────────
        # For each query token, also try without the first character. This catches
        # common lead-char typos (e.g. "ajasari" → regex "jasari" → matches "Arjasari").
        seen_keys: set[str] = {_doc_key(d) for d in text_docs}
        regex_docs: list[dict] = []

        for token in tokens[:2]:
            patterns = [token]
            if len(token) >= 5:
                patterns.append(token[1:])  # drop first char

            for pat in patterns:
                rdocs: list[dict] = await (
                    self.col.find(
                        {"name": {"$regex": re.escape(pat), "$options": "i"}},
                        {"_id": 0},
                    )
                    .limit(limit * 2)
                    .to_list(limit * 2)
                )
                for doc in rdocs:
                    k = _doc_key(doc)
                    if k not in seen_keys:
                        seen_keys.add(k)
                        regex_docs.append(doc)

        # ── Score and rank ─────────────────────────────────────────────────────
        # depth bonus ensures a matching subdistrict beats a matching district.
        # name_sim rewards the result whose name is closest to any query token.
        # text_score provides a tie-breaker from MongoDB's relevance signal.
        def _score(doc: dict) -> float:
            depth = _LEVEL_DEPTH.get(doc.get("level", "province"), 1)
            sim = _name_sim(tokens, doc.get("name", ""))
            text_s = float(doc.get("score", 0.0))
            return depth * 1.5 + sim * 3.0 + text_s * 0.5

        all_docs = text_docs + regex_docs
        ranked = sorted(all_docs, key=_score, reverse=True)[:limit]

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
            for doc in ranked
        ]
