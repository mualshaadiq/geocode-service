#!/usr/bin/env python3
"""
One-time import of all Indonesian administrative toponyms from the Aetos geocode
service into a local MongoDB collection. Safe to re-run (upserts on GID codes).

Usage:
    GEOCODE_BASE_URL=https://app.dev.aetosky.com/api/services/geocode \
    GEOCODE_AUTH_TOKEN=<token> \
    MONGODB_URL=mongodb://localhost:27017 \
    python scripts/import_toponyms.py

Environment variables:
    GEOCODE_BASE_URL    Base URL for the Aetos geocode API  (required)
    GEOCODE_AUTH_TOKEN  Bearer token for the geocode API    (required)
    MONGODB_URL         MongoDB connection string           (default: mongodb://localhost:27017)
    MONGODB_DB          Database name                       (default: geocode_service)
    IMPORT_CONCURRENCY  Concurrent HTTP requests            (default: 10)
"""
import asyncio
import logging
import os
import sys

import httpx
from motor.motor_asyncio import AsyncIOMotorClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger(__name__)

GEOCODE_BASE_URL = os.environ.get(
    "GEOCODE_BASE_URL", "https://app.dev.aetosky.com/api/services/geocode"
).rstrip("/")
GEOCODE_AUTH_TOKEN = os.environ.get("GEOCODE_AUTH_TOKEN", "")
MONGODB_URL = os.environ.get("MONGODB_URL", "mongodb://localhost:27017")
MONGODB_DB = os.environ.get("MONGODB_DB", "geocode_service")
CONCURRENCY = int(os.environ.get("IMPORT_CONCURRENCY", "10"))


async def fetch(client: httpx.AsyncClient, path: str, params: dict | None = None) -> list:
    headers = {}
    if GEOCODE_AUTH_TOKEN:
        headers["Authorization"] = f"Bearer {GEOCODE_AUTH_TOKEN}"
    resp = await client.get(
        f"{GEOCODE_BASE_URL}{path}", params=params, headers=headers, timeout=30
    )
    resp.raise_for_status()
    data = resp.json()
    return data if isinstance(data, list) else []


async def import_all() -> None:
    mongo = AsyncIOMotorClient(MONGODB_URL)
    col = mongo[MONGODB_DB]["toponyms"]

    # Ensure indexes
    existing = await col.index_information()
    if "search_text_index" not in existing:
        await col.create_index(
            [("search_text", "text")],
            name="search_text_index",
            default_language="none",
        )
    await col.create_index("gid_1", sparse=True, background=True)
    await col.create_index("gid_2", sparse=True, background=True)
    await col.create_index("gid_3", sparse=True, background=True)

    sem = asyncio.Semaphore(CONCURRENCY)
    total = 0

    async with httpx.AsyncClient() as client:
        # ── Countries ──────────────────────────────────────────────
        countries = await fetch(client, "/countries")
        idn = next((c for c in countries if c.get("gid_0") == "IDN"), None)
        if not idn:
            log.error("Indonesia (IDN) not found in the geocode service. Aborting.")
            return
        log.info("Found Indonesia (IDN)")

        # ── Provinces ──────────────────────────────────────────────
        provinces = await fetch(client, "/adm_1", {"gid_0": "IDN"})
        log.info(f"Fetched {len(provinces)} provinces")

        for p in provinces:
            doc = {
                "name": p["name_1"],
                "full_path": f"{p['name_1']}, Indonesia",
                "search_text": f"{p['name_1'].lower()} indonesia",
                "level": "province",
                "gid_0": "IDN",
                "gid_1": p["gid_1"],
                "gid_2": None,
                "gid_3": None,
                "parent_names": ["Indonesia"],
            }
            await col.update_one(
                {"gid_1": doc["gid_1"], "level": "province"},
                {"$set": doc},
                upsert=True,
            )
        total += len(provinces)
        log.info(f"Upserted {len(provinces)} provinces")

        # ── Districts (concurrent per province) ───────────────────
        async def fetch_districts(prov: dict) -> tuple[dict, list]:
            async with sem:
                districts = await fetch(
                    client, "/adm_2", {"gid_0": "IDN", "gid_1": prov["gid_1"]}
                )
                return prov, districts

        prov_results = await asyncio.gather(*[fetch_districts(p) for p in provinces])

        all_districts: list[tuple[dict, dict]] = []
        district_count = 0
        for prov, districts in prov_results:
            for d in districts:
                doc = {
                    "name": d["name_2"],
                    "full_path": f"{d['name_2']}, {prov['name_1']}, Indonesia",
                    "search_text": f"{d['name_2'].lower()} {prov['name_1'].lower()} indonesia",
                    "level": "district",
                    "gid_0": "IDN",
                    "gid_1": prov["gid_1"],
                    "gid_2": d["gid_2"],
                    "gid_3": None,
                    "parent_names": [prov["name_1"], "Indonesia"],
                }
                await col.update_one(
                    {"gid_2": doc["gid_2"], "level": "district"},
                    {"$set": doc},
                    upsert=True,
                )
                all_districts.append((prov, d))
                district_count += 1

        total += district_count
        log.info(f"Upserted {district_count} districts")

        # ── Subdistricts (concurrent per district) ─────────────────
        log.info(f"Fetching subdistricts for {len(all_districts)} districts (this may take a few minutes)…")

        async def fetch_subdistricts(prov: dict, dist: dict) -> tuple[dict, dict, list]:
            async with sem:
                subs = await fetch(
                    client,
                    "/adm_3",
                    {"gid_0": "IDN", "gid_1": prov["gid_1"], "gid_2": dist["gid_2"]},
                )
                return prov, dist, subs

        sub_results = await asyncio.gather(
            *[fetch_subdistricts(prov, dist) for prov, dist in all_districts]
        )

        sub_count = 0
        for prov, dist, subs in sub_results:
            for s in subs:
                if "gid_3" not in s or "name_3" not in s:
                    continue
                doc = {
                    "name": s["name_3"],
                    "full_path": f"{s['name_3']}, {dist['name_2']}, {prov['name_1']}, Indonesia",
                    "search_text": f"{s['name_3'].lower()} {dist['name_2'].lower()} {prov['name_1'].lower()} indonesia",
                    "level": "subdistrict",
                    "gid_0": "IDN",
                    "gid_1": prov["gid_1"],
                    "gid_2": dist["gid_2"],
                    "gid_3": s["gid_3"],
                    "parent_names": [dist["name_2"], prov["name_1"], "Indonesia"],
                }
                await col.update_one(
                    {"gid_3": doc["gid_3"]},
                    {"$set": doc},
                    upsert=True,
                )
                sub_count += 1

        total += sub_count
        log.info(f"Upserted {sub_count} subdistricts")

    mongo.close()
    log.info(f"Import complete — {total} total documents in '{MONGODB_DB}.toponyms'")


if __name__ == "__main__":
    if not GEOCODE_AUTH_TOKEN:
        log.warning("GEOCODE_AUTH_TOKEN is not set — requests may be rejected by the API")
    asyncio.run(import_all())
