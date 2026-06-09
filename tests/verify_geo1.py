"""
GEO-1 Verification — functional tests for the cascading hierarchy dropdown API.

Tests are derived from the interface contracts in Design Doc GEO-1 v1.0, NOT from
reading app/hierarchy.py. Each test maps to a row in the Verification Record's
coverage table.

Run inside the service container (so it can reach both the HTTP API and MongoDB):

    docker compose exec -T geocode-service python - < tests/verify_geo1.py

Exits non-zero if any test fails.
"""
import asyncio
import os
import sys

import httpx
from motor.motor_asyncio import AsyncIOMotorClient

BASE = os.environ.get("VERIFY_BASE_URL", "http://localhost:8080")
MONGO_URL = os.environ.get("MONGODB_URL", "mongodb://mongodb:27017")
MONGO_DB = os.environ.get("MONGODB_DB", "geocode_service")

# Synthetic childless province used to prove the "parent exists, no children →
# 200 empty list" contract (distinct from "parent missing → 404"). Inserted and
# removed by this test; uses an obviously-fake GID that cannot collide with GADM.
SYNTH_GID = "IDN.ZZVERIFY_1"

_failures: list[str] = []
_passes = 0


def check(tc: str, cond: bool, detail: str = "") -> bool:
    global _passes
    if cond:
        _passes += 1
        print(f"PASS {tc} {detail}")
    else:
        _failures.append(f"{tc} {detail}")
        print(f"FAIL {tc} {detail}")
    return cond


def _sorted_ci(names: list[str]) -> bool:
    """True if names are in case-insensitive non-decreasing order."""
    folded = [n.casefold() for n in names]
    return folded == sorted(folded)


def _province_base(gid_1: str) -> str:
    # "IDN.7_1" -> "IDN.7"  ; children gid_2 look like "IDN.7.5_1"
    return gid_1.rsplit("_", 1)[0]


async def main() -> None:
    async with httpx.AsyncClient(base_url=BASE, timeout=30) as c:
        # ── Contract: GET /provinces → 200, every province, identity fields ────
        r = await c.get("/provinces")
        check("TC-01-status", r.status_code == 200, f"GET /provinces -> {r.status_code}")
        body = r.json()
        provinces = body.get("items", [])
        check("TC-01-shape",
              body.get("level") == "province" and body.get("parent") is None
              and body.get("count") == len(provinces) and len(provinces) > 0,
              f"level={body.get('level')} parent={body.get('parent')} count={body.get('count')}")
        check("TC-01-fields",
              all({"code", "name", "full_path", "level"} <= p.keys()
                  and p["level"] == "province" for p in provinces),
              "every item has code/name/full_path/level=province")

        # ── Contract: lists have NO geometry / centroid / bbox ────────────────
        check("TC-09-no-geometry",
              all(not ({"geometry", "centroid", "bbox"} & p.keys()) for p in provinces),
              "no geometry/centroid/bbox in list items")

        # ── Contract: provinces sorted alphabetically by name ─────────────────
        check("TC-02-sorted", _sorted_ci([p["name"] for p in provinces]),
              "provinces alphabetical by name")

        # Pick a province that actually has districts for the cascade tests.
        prov = provinces[0]
        districts = []
        for p in provinces:
            rr = await c.get(f"/provinces/{p['code']}/districts")
            if rr.status_code == 200 and rr.json().get("count", 0) > 0:
                prov, districts = p, rr.json()["items"]
                break

        # ── Contract: GET /provinces/{gid_1}/districts → scoped, sorted ───────
        check("TC-03-districts",
              len(districts) > 0
              and all(d["level"] == "district" for d in districts),
              f"province {prov['code']} -> {len(districts)} districts")
        pbase = _province_base(prov["code"])
        check("TC-03-scoped",
              all(d["code"].startswith(pbase + ".") for d in districts),
              f"all district codes scoped under {pbase}.")
        check("TC-04-sorted", _sorted_ci([d["name"] for d in districts]),
              "districts alphabetical by name")

        # ── Contract: GET /districts/{gid_2}/subdistricts → scoped, sorted ────
        dist = districts[0]
        subs = []
        for d in districts:
            rr = await c.get(f"/districts/{d['code']}/subdistricts")
            if rr.status_code == 200 and rr.json().get("count", 0) > 0:
                dist, subs = d, rr.json()["items"]
                break
        check("TC-06-subdistricts",
              len(subs) > 0 and all(s["level"] == "subdistrict" for s in subs),
              f"district {dist['code']} -> {len(subs)} subdistricts")
        dbase = dist["code"].rsplit("_", 1)[0]
        check("TC-06-scoped",
              all(s["code"].startswith(dbase + ".") for s in subs),
              f"all subdistrict codes scoped under {dbase}.")
        check("TC-07-sorted", _sorted_ci([s["name"] for s in subs]),
              "subdistricts alphabetical by name")

        # ── Contract: unknown parent → 404 (distinct from empty list) ─────────
        r404a = await c.get("/provinces/IDN.NONEXIST_9/districts")
        check("TC-05-404", r404a.status_code == 404,
              f"unknown province -> {r404a.status_code}")
        r404b = await c.get("/districts/IDN.NONEXIST.9_9/subdistricts")
        check("TC-08-404", r404b.status_code == 404,
              f"unknown district -> {r404b.status_code}")

        # ── Contract: parent exists but no children → 200 empty list ──────────
        mongo = AsyncIOMotorClient(MONGO_URL)
        col = mongo[MONGO_DB]["toponyms"]
        await col.insert_one({
            "name": "ZZ Verify Province", "full_path": "ZZ Verify Province, Indonesia",
            "search_text": "zz verify province indonesia", "level": "province",
            "gid_0": "IDN", "gid_1": SYNTH_GID, "gid_2": None, "gid_3": None,
        })
        try:
            re = await c.get(f"/provinces/{SYNTH_GID}/districts")
            check("TC-10-empty",
                  re.status_code == 200 and re.json().get("count") == 0,
                  f"childless province -> {re.status_code} count={re.json().get('count')}")
        finally:
            await col.delete_one({"gid_1": SYNTH_GID, "level": "province"})
            mongo.close()

        # ── Contract: returned GID resolves via existing /geometry endpoint ───
        rg = await c.get(f"/geometry/subdistrict/{subs[0]['code']}")
        check("TC-11-geometry",
              rg.status_code == 200 and rg.json().get("geometry") is not None,
              f"subdistrict {subs[0]['code']} resolves geometry -> {rg.status_code}")

        # ── Regression: existing endpoints still behave ──────────────────────
        rs = await c.get("/search", params={"q": prov["name"][:5]})
        check("TC-12-search", rs.status_code == 200 and "results" in rs.json(),
              "existing /search still works")
        rgp = await c.get(f"/geometry/province/{prov['code']}")
        check("TC-12-geo-prov", rgp.status_code == 200,
              "existing /geometry province still works")

    print(f"\n=== {_passes} passed, {len(_failures)} failed ===")
    if _failures:
        for f in _failures:
            print("  FAILED:", f)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
