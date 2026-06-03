#!/usr/bin/env python3
"""
Import Indonesian administrative toponyms from GADM v4.1 open data into MongoDB.
GADM uses the same GID code format (IDN.7_1, IDN.7.5_1, IDN.7.5.3_1) as the
Aetos geocode system, so downstream GeometryRef resolution works unchanged.

Safe to re-run (upserts). Downloads ~8 MB of GeoJSON from gadm.org.

Usage:
    MONGODB_URL=mongodb://localhost:27017 \
    MONGODB_DB=geocode_service \
    python scripts/import_toponyms.py
"""
import asyncio
import io
import json
import logging
import os
import sys
import zipfile

import httpx
from motor.motor_asyncio import AsyncIOMotorClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger(__name__)

MONGODB_URL = os.environ.get("MONGODB_URL", "mongodb://localhost:27017")
MONGODB_DB = os.environ.get("MONGODB_DB", "geocode_service")

GADM_BASE = "https://geodata.ucdavis.edu/gadm/gadm4.1/json"
GADM_FILES = {
    1: f"{GADM_BASE}/gadm41_IDN_1.json.zip",
    2: f"{GADM_BASE}/gadm41_IDN_2.json.zip",
    3: f"{GADM_BASE}/gadm41_IDN_3.json.zip",
}

LEVEL_MAP = {1: "province", 2: "district", 3: "subdistrict"}


async def download_geojson(client: httpx.AsyncClient, url: str) -> dict:
    log.info(f"Downloading {url} …")
    resp = await client.get(url, timeout=120, follow_redirects=True)
    resp.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
        name = next(n for n in z.namelist() if n.endswith(".json"))
        return json.loads(z.read(name))


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
    for field in ("gid_1", "gid_2", "gid_3"):
        await col.create_index(field, sparse=True, background=True)

    total = 0
    # Build province name lookup for constructing search_text at lower levels
    prov_names: dict[str, str] = {}
    dist_names: dict[str, str] = {}

    async with httpx.AsyncClient(verify=False) as client:
        for adm_level in (1, 2, 3):
            geojson = await download_geojson(client, GADM_FILES[adm_level])
            features = geojson.get("features", [])
            log.info(f"ADM{adm_level}: {len(features)} features")

            count = 0
            for feat in features:
                p = feat.get("properties", {})
                level = LEVEL_MAP[adm_level]

                if adm_level == 1:
                    gid_1 = p.get("GID_1", "")
                    name = p.get("NAME_1", "")
                    prov_names[gid_1] = name
                    doc = {
                        "name": name,
                        "full_path": f"{name}, Indonesia",
                        "search_text": f"{name.lower()} indonesia",
                        "level": level,
                        "gid_0": "IDN",
                        "gid_1": gid_1,
                        "gid_2": None,
                        "gid_3": None,
                        "parent_names": ["Indonesia"],
                    }
                    await col.update_one(
                        {"gid_1": gid_1, "level": "province"},
                        {"$set": doc},
                        upsert=True,
                    )

                elif adm_level == 2:
                    gid_1 = p.get("GID_1", "")
                    gid_2 = p.get("GID_2", "")
                    name = p.get("NAME_2", "")
                    pname = prov_names.get(gid_1, "")
                    dist_names[gid_2] = name
                    doc = {
                        "name": name,
                        "full_path": f"{name}, {pname}, Indonesia",
                        "search_text": f"{name.lower()} {pname.lower()} indonesia",
                        "level": level,
                        "gid_0": "IDN",
                        "gid_1": gid_1,
                        "gid_2": gid_2,
                        "gid_3": None,
                        "parent_names": [pname, "Indonesia"],
                    }
                    await col.update_one(
                        {"gid_2": gid_2, "level": "district"},
                        {"$set": doc},
                        upsert=True,
                    )

                elif adm_level == 3:
                    gid_1 = p.get("GID_1", "")
                    gid_2 = p.get("GID_2", "")
                    gid_3 = p.get("GID_3", "")
                    name = p.get("NAME_3", "")
                    pname = prov_names.get(gid_1, "")
                    dname = dist_names.get(gid_2, "")
                    doc = {
                        "name": name,
                        "full_path": f"{name}, {dname}, {pname}, Indonesia",
                        "search_text": f"{name.lower()} {dname.lower()} {pname.lower()} indonesia",
                        "level": level,
                        "gid_0": "IDN",
                        "gid_1": gid_1,
                        "gid_2": gid_2,
                        "gid_3": gid_3,
                        "parent_names": [dname, pname, "Indonesia"],
                    }
                    await col.update_one(
                        {"gid_3": gid_3},
                        {"$set": doc},
                        upsert=True,
                    )

                count += 1

            total += count
            log.info(f"ADM{adm_level}: upserted {count} documents")

    mongo.close()
    log.info(f"Import complete — {total} total documents in '{MONGODB_DB}.toponyms'")


if __name__ == "__main__":
    asyncio.run(import_all())
