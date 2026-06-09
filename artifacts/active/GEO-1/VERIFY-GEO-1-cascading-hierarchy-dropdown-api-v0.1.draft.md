# Verification Record: Cascading Hierarchy Dropdown API

Version: v0.1
Status: Draft
Author: AI-drafted, azonarate
Approver:
Date: 2026-06-10
Related ticket: GEO-1
Design Doc reference: Design Doc GEO-1 "Cascading Hierarchy Dropdown API" v1.0 (Approved, approver: satya)

---

## Scope

Verified: the three new listing endpoints and their contracts as specified in
Design Doc GEO-1 v1.0 — `GET /provinces`, `GET /provinces/{gid_1}/districts`,
`GET /districts/{gid_2}/subdistricts` — plus the RFC requirement that existing
endpoints behave identically.

Verification was performed against the **live service** running in Docker
(`docker compose up`), backed by MongoDB populated with the full GADM v4.1
Indonesian dataset via `scripts/import_toponyms.py` (34 provinces, 502 districts,
6695 subdistricts; 7231 documents). Tests hit real HTTP endpoints — see
`tests/verify_geo1.py`. Test cases were derived from the Design Doc interface
contracts, not from reading the implementation.

Not verified in this cycle (out of scope per RFC):
- Free-text `?q=` filtering — deferred in the approved RFC.
- Geometry correctness of the GADM data itself — owned by the import pipeline,
  not this feature.
- Caching, rate limiting, authentication — RFC explicitly introduces none.
- Performance/load — result sets are small by design; no perf target was set.

## Coverage Map

| Design Doc section | Requirement / contract | Test ID | Covered? |
|-------------------|------------------------|---------|----------|
| Interfaces · GET /provinces | 200; returns every province; level="province", parent=null, count matches | TC-01 | ✓ |
| Interfaces · item shape | Each item has code + name + full_path + level | TC-01 | ✓ |
| Architecture · identity only | No geometry/centroid/bbox in list responses | TC-09 | ✓ |
| Contract notes · sort | Provinces sorted alphabetically by name | TC-02 | ✓ |
| Interfaces · districts | 200; only districts of the parent province; level="district" | TC-03 | ✓ |
| Constraints · parent-scoped | District codes scoped under the parent province GID | TC-03 | ✓ |
| Contract notes · sort | Districts sorted alphabetically by name | TC-04 | ✓ |
| Interfaces · subdistricts | 200; only subdistricts of the parent district; level="subdistrict" | TC-06 | ✓ |
| Constraints · parent-scoped | Subdistrict codes scoped under the parent district GID | TC-06 | ✓ |
| Contract notes · sort | Subdistricts sorted alphabetically by name | TC-07 | ✓ |
| Interfaces · 404 | Unknown parent province → 404 | TC-05 | ✓ |
| Interfaces · 404 | Unknown parent district → 404 | TC-08 | ✓ |
| Success criteria · empty list | Parent exists but has no children → 200 empty list (not 404) | TC-10 | ✓ |
| Contract notes · code→geometry | Returned GID resolves via existing /geometry/{level}/{code} | TC-11 | ✓ |
| RFC constraint · no regression | Existing /search behaves identically | TC-12 | ✓ |
| RFC constraint · no regression | Existing /geometry behaves identically | TC-12 | ✓ |

All contracts covered; no ✗ rows.

## Test Cases

| Test ID | Description | Input | Expected output | Result | Notes |
|---------|-------------|-------|-----------------|--------|-------|
| TC-01 | List all provinces | `GET /provinces` | 200; level=province, parent=null, count=34, items have code/name/full_path | Pass | 34 provinces returned |
| TC-02 | Provinces sorted | `GET /provinces` | Names in case-insensitive ascending order | Pass | |
| TC-03 | Districts of a province (scoped) | `GET /provinces/IDN.1_1/districts` | 200; 23 districts, all level=district, codes under `IDN.1.` | Pass | parent-scoping enforced |
| TC-04 | Districts sorted | as TC-03 | Names ascending | Pass | |
| TC-05 | Unknown province → 404 | `GET /provinces/IDN.NONEXIST_9/districts` | 404 | Pass | distinguishes typo from empty |
| TC-06 | Subdistricts of a district (scoped) | `GET /districts/IDN.1.2_1/subdistricts` | 200; 12 subdistricts, level=subdistrict, codes under `IDN.1.2.` | Pass | |
| TC-07 | Subdistricts sorted | as TC-06 | Names ascending | Pass | |
| TC-08 | Unknown district → 404 | `GET /districts/IDN.NONEXIST.9_9/subdistricts` | 404 | Pass | |
| TC-09 | No geometry in lists | `GET /provinces` items | No geometry/centroid/bbox keys | Pass | separation of concerns |
| TC-10 | Childless parent → empty 200 | Insert synthetic childless province, `GET …/districts`, then delete | 200, count=0 | Pass | synthetic doc cleaned up after |
| TC-11 | GID resolves geometry | `GET /geometry/subdistrict/IDN.1.2.1_1` | 200 with non-null geometry | Pass | cascade end-to-end |
| TC-12 | Existing endpoints unchanged | `GET /search?q=…`, `GET /geometry/province/{gid}` | 200; expected shapes | Pass | no regression |

Execution: `docker compose exec -T geocode-service python - < tests/verify_geo1.py`
→ **17 assertions passed, 0 failed.**

## Gaps

| Requirement | Reason not covered | Deferred to / accepted |
|------------|-------------------|------------------------|
| `?q=` typeahead filtering | Out of scope per approved RFC | Deferred — possible future enhancement |
| Collation locale correctness for non-ASCII Indonesian names | `_NAME_COLLATION` uses locale `"id"`, strength 2; sort verified as case-insensitive ascending on the real dataset (TC-02/04/07), but locale-specific ordering of diacritics was not exhaustively asserted | Accepted — ASSUMPTION flag in code; low risk, no contract impact |

## Findings

No defects. Behaviour matches the Design Doc interface contracts on every tested
path. The `ASSUMPTION:` flag in `app/hierarchy.py` (collation locale) was
exercised indirectly by the sort tests (TC-02/04/07), which passed; the engineer
should still consciously confirm or remove that flag before merge per the
Implement-phase standard.

## Acceptance Decision

All Design Doc interface contracts and the RFC no-regression constraint are
verified against the live service with full data. Recommended for acceptance as
**done**, conditional on the engineer resolving the collation `ASSUMPTION:` flag
during PR review.

Acceptance to be granted by a named human approver (not the AI author).

---
*Revision history*

| Version | Date       | Author                | Changes       |
|---------|------------|-----------------------|---------------|
| v0.1    | 2026-06-10 | AI-drafted, azonarate | Initial draft |
