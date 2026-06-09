# Design Doc: Cascading Hierarchy Dropdown API

Version: v1.0
Status: Approved
Author: AI-drafted, azonarate
Approver: satya
Date: 2026-06-10
Related ticket: GEO-1
RFC reference: RFC GEO-1 "Cascading Hierarchy Dropdown API" v1.0 (Approved, approver: satya)

---

## System Architecture

This design adds a **read-only, purely additive hierarchy listing capability** to
the existing FastAPI geocode service. It introduces three nested REST endpoints
that expose the Indonesian administrative hierarchy (province → district →
subdistrict) by querying the existing `toponyms` MongoDB collection through the
already-configured Motor client.

The new capability sits alongside the two existing APIs and does not modify them:

```
                         ┌─────────────────────────────────────┐
   client (dropdown UI)  │           FastAPI app                │
        │                │                                      │
        │  GET /provinces ──────► hierarchy routes (NEW) ──┐    │
        │  …/{gid_1}/districts                             │    │
        │  …/{gid_2}/subdistricts                          ▼    │
        │                │                       app/hierarchy.py (NEW)
        │                │                       HierarchyService          │
        │                │                                 │    │
        │                │                                 ▼    │
        │                │                       toponyms collection ◄─── (existing, shared)
        │                │                       indexes: gid_1, gid_2, gid_3
        │  GET /geometry/{level}/{code} ─► get_geometry (EXISTING, untouched)
        │  GET /search ─────────────────► search (EXISTING, untouched)
        └────────────────┘
```

The cascade flow (from the RFC) is realised as:

```
1. GET /provinces                        → pick a province (gid_1)
2. GET /provinces/{gid_1}/districts      → pick a district (gid_2)
3. GET /districts/{gid_2}/subdistricts   → pick a subdistrict (gid_3)
4. GET /geometry/{level}/{code}          → resolve the chosen area's geometry
```

Steps 1–3 are the new endpoints (identity only). Step 4 is the existing,
unchanged geometry endpoint. The listing endpoints never serve geometry; they
hand back the GID `code` that the caller passes into step 4.

## Components and Responsibilities

**`app/hierarchy.py` (new module)**
- `HierarchyService` — owns hierarchy traversal. Exposes three methods:
  `list_provinces()`, `list_districts(province_gid)`,
  `list_subdistricts(district_gid)`. Each performs (a) a parent-existence check
  where applicable and (b) a parent-scoped child query, sorted alphabetically by
  name. Returns lists of `HierarchyItem`.
- New Pydantic models `HierarchyItem` and `HierarchyListResponse`. They live here,
  **not** in `models.py`, to honour the RFC constraint that `models.py` remain
  untouched.
- Does **not**: serve geometry, perform free-text/fuzzy search, rank results,
  write data, or handle auth/caching/rate-limiting.

**`app/main.py` (existing, additive change only)**
- Registers three new route handlers that delegate to `HierarchyService` and shape
  the HTTP response (including the 404 for an unknown parent).
- The existing `/search`, `/geometry/{level}/{code}`, and `/health` handlers, and
  the `lifespan` setup, remain byte-for-byte unchanged. The service is instantiated
  in `lifespan` reusing the existing `_db` handle.

**Existing, untouched:** `models.py`, `search.py`, `scripts/import_toponyms.py`,
the MongoDB schema, and all existing indexes.

## Interfaces

All responses are JSON. `code` is the GID the caller forwards to the existing
`GET /geometry/{level}/{code}` endpoint.

**`GET /provinces`**
- Input: none.
- Output `200`: `HierarchyListResponse`
  - `level`: `"province"`, `parent`: `null`, `count`: int,
    `items`: `[ { code: <gid_1>, name, full_path, level: "province" }, … ]`
- Guarantee: every province in the dataset, sorted alphabetically by `name`.

**`GET /provinces/{gid_1}/districts`**
- Input: `gid_1` path param (e.g. `IDN.7_1`).
- Output `200`: `HierarchyListResponse` with `level: "district"`,
  `parent: <gid_1>`, items `{ code: <gid_2>, name, full_path, level: "district" }`.
- Output `404`: if no province with that `gid_1` exists.
- Guarantee: only districts whose `gid_1` equals the path parent; empty `items`
  (still `200`) if the province exists but has no districts in the data.

**`GET /districts/{gid_2}/subdistricts`**
- Input: `gid_2` path param (e.g. `IDN.7.5_1`).
- Output `200`: `HierarchyListResponse` with `level: "subdistrict"`,
  `parent: <gid_2>`, items `{ code: <gid_3>, name, full_path, level: "subdistrict" }`.
- Output `404`: if no district with that `gid_2` exists.
- Guarantee: only subdistricts whose `gid_2` equals the path parent; empty `items`
  (still `200`) if the district exists but has no subdistricts in the data.

**Contract notes**
- Sort: alphabetical by `name`, case-insensitive (MongoDB collation).
- `code` → geometry mapping: `gid_1` with `level=province`, `gid_2` with
  `level=district`, `gid_3` with `level=subdistrict` — all already accepted by the
  existing geometry endpoint's `_LEVEL_GID_FIELD` map.
- No geometry, centroid, or bounding box is ever returned by these endpoints.

## Dependencies

**Internal (existing, reused):**
- `toponyms` collection and its sparse single-field indexes `gid_1`, `gid_2`,
  `gid_3` — created by `scripts/import_toponyms.py`. The parent-scoped queries are
  served directly by these indexes; **no new index is required**.
- The FastAPI app, its `lifespan`-managed Motor client / `_db` handle, and
  `config.settings.collection_name`.
- Document fields consumed: `level`, `gid_1`, `gid_2`, `gid_3`, `name`,
  `full_path`.

**External:**
- FastAPI and `motor` — already direct dependencies; no new packages.
- MongoDB collation (server feature) for the alphabetical sort.

## Data Flow

```
HTTP request
   │
   ▼
route handler (main.py)  ── validates path params present
   │
   ▼
HierarchyService method (hierarchy.py)
   │   ① parent-existence check (district/subdistrict only):
   │       find_one({<parent gid field>: parent, level: <parent level>})
   │       → if None: raise 404
   │   ② child query:
   │       find({level: <child level>, <parent gid field>: parent},
   │            projection={code field, name, full_path})
   │            .collation({locale}).sort(name, 1)
   │
   ▼
map docs → HierarchyItem list → HierarchyListResponse
   │
   ▼
HTTP 200 (or 404)
```

All operations are reads. No document is created, updated, or deleted. Data
continues to enter the system solely via the import script (unchanged).

## Tradeoffs Considered and Rejected

| Option | Rejected because |
|--------|-----------------|
| Generic `GET /list?level=&parent=` endpoint | Its main advantage is easy extension to new levels, but the RFC fixes the hierarchy at 3 levels (no ADM4). Nested paths enforce parent-scoping structurally and are self-documenting. |
| Always return `200` + empty list for any parent (incl. unknown) | Cannot distinguish a typo'd/invalid parent code from a genuinely childless area; a silently-empty dropdown is hard for clients to debug. Chose `404` for unknown parent. |
| Add the new Pydantic models to `models.py` | RFC constraint requires `models.py` to remain untouched. New models live in `app/hierarchy.py`. |
| Return geometry / centroid / bbox in the list response | Violates the RFC separation-of-concerns; duplicates geometry-serving logic and bloats the payload. Geometry stays with the existing `/geometry` endpoint. |
| Client fetches whole dataset and filters client-side | The problem this RFC exists to solve: error-prone and pushes hierarchy knowledge out of the owning service. |
| Pagination on the list endpoints | Worst-case result sets are small (provinces ~38; districts per province ≤~40; subdistricts per district ≤~dozens). Pagination adds contract complexity with no benefit at this scale. |
| `?q=` typeahead filter within a list | Deferred in the approved RFC (overlaps the existing `/search`); out of scope for this cycle. |

## Deployment Considerations

- Runs on the **existing** FastAPI app, the **existing** MongoDB, and the
  **existing** env vars (`MONGODB_URL`, `MONGODB_DB`, `collection_name`). No new
  infrastructure, no migration, no new configuration.
- Relies on the `gid_1/gid_2/gid_3` indexes already created by the import script.
  If a deployment somehow lacks them, the queries still work but lose index
  acceleration — acceptable given the small collection, and the import script
  creates them on its normal run.
- Endpoints are stateless reads; they inherit whatever scaling, auth, caching, and
  rate-limiting posture the app already has (the RFC explicitly does not introduce
  any here).
- No change to the import pipeline or release process; deploying this is a code-only
  rollout of the new module plus route registrations.

## Open Questions

- **Collation locale for the alphabetical sort.** A generic case-insensitive
  Unicode collation is assumed; whether to use an Indonesian-specific locale
  (`"id"`) is an implementation detail with low risk and no contract impact. To be
  settled in the Implement phase.

---
*Revision history*

| Version | Date       | Author                | Changes       |
|---------|------------|-----------------------|---------------|
| v0.1    | 2026-06-10 | AI-drafted, azonarate | Initial draft |
| v1.0    | 2026-06-10 | AI-drafted, azonarate | Approved by satya — Plan gate closed |
