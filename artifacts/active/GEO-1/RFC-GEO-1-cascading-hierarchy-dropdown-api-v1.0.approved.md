# RFC: Cascading Hierarchy Dropdown API

Version: v1.0
Status: Approved
Author: AI-drafted, azonarate
Approver: satya
Date: 2026-06-10
Related ticket: GEO-1

---

## Problem Statement

The geocode service today exposes only free-text search (GET /search) and
geometry lookup by code (GET /geometry/{level}/{code}). A consuming application
that wants to let a user pick a location through cascading dropdowns
(province → district → subdistrict) has no way to obtain the list of valid
children for a chosen parent.

Concretely, there is no endpoint that answers:
- "Give me all provinces."
- "Given province X, give me only its districts."
- "Given district Y (e.g. Jakarta Selatan), give me only its subdistricts."

Without this, a client building a dropdown UI must either fetch the entire
toponym dataset and filter client-side, or guess codes — both of which are
error-prone and push administrative-hierarchy knowledge out of the service that
owns it.

## Why It Matters

Cascading dropdowns are the standard UX for selecting an administrative area
when the user does not know the exact name to type (the case /search already
serves). Any downstream service that needs structured location input is currently
blocked from building this without re-implementing hierarchy traversal itself.

There is no hard deadline; the trigger is that a downstream service wants to
integrate location selection and needs a stable, server-owned hierarchy API to
call.

## Why It Matters — Intended Flow

The cascade is driven entirely by tiered parent-scoped filtering, then resolved
once via the existing geometry endpoint:

```
1. Province dropdown   → list API: all provinces
2. Pick a province     → list API: districts WITHIN that province     (tier-1 filter)
3. Pick a district     → list API: subdistricts WITHIN that district  (tier-2 filter)
4. Pick final area     → GET /geometry/{level}/{code} → resolved location
```

The "filter" the client needs is satisfied by this tiered parent-scoping alone;
no free-text filtering within a list is required for the cascade to work.

## Constraints

- No changes to existing behaviour. The current /search, /geometry/{level}/{code},
  and /health endpoints, the models, the search.py ranking logic, the
  import script, and the MongoDB schema must remain untouched. The new capability
  is purely additive (new endpoints only).
- Separation of concerns — list vs. resolve. The new endpoints return only
  identity data per area: the GID code(s) plus name (and full_path). They
  do not return geometry, centroid, or bounding box. The returned GID is the
  key the caller passes into the existing GET /geometry/{level}/{code} endpoint
  ("the second API") to resolve the actual location. This keeps the dropdown API
  lightweight and avoids duplicating geometry-serving logic.
- Parent-scoped results (tiered filtering). A child list must be filtered to
  exactly one parent: selecting Jakarta Selatan returns only the subdistricts
  within Jakarta Selatan. This tiered scoping is the core requirement.
- Read-only. No write paths; data continues to come from the import script.
- Same stack. FastAPI + Motor/MongoDB, served on the existing app, reusing the
  existing toponyms collection and its existing indexes (gid_1, gid_2,
  gid_3 already indexed by the import script).

## Success Criteria

- A client can render a province → district → subdistrict cascade using only the
  new endpoints, with each child request scoped to the selected parent.
- The list endpoints return GID code(s) + name for every area, and the final
  selected GID successfully resolves through the existing /geometry/{level}/{code}
  endpoint with no change to that endpoint.
- Existing endpoints behave identically before and after the change (verified).
- For a parent with no children present in the data, the endpoint returns an empty
  list (not an error).
- Lists are returned sorted alphabetically by name.

## Out of Scope

- Returning geometry, centroid, or bounding box from the new endpoints (caller
  uses the existing /geometry endpoint for that).
- Any change to free-text search, ranking, or the import pipeline.
- Free-text (?q=) substring/typeahead filtering within a child list. The cascade
  is fully served by tiered parent-scoping; text filtering overlaps with the
  existing /search endpoint and is deferred as a possible separate enhancement.
- Caching, rate limiting, and authentication (inherit whatever the service has;
  not introduced here).
- A 4th administrative level below subdistrict (data only goes to ADM3).

## Resolved Questions

- Free-text ?q= filter on list endpoints — DEFERRED (out of scope). The core
  cascade requirement is tiered parent-scoping, which the per-level list
  structure satisfies on its own. ?q= overlaps with the existing /search
  endpoint and can be added later additively if a real need emerges.
- Ticket ID — CONFIRMED as GEO-1.
- Sort order of lists — alphabetical by name.

## Open Questions

- Endpoint shape (generic `/list?level=&parent=` vs nested per-level paths such
  as `/provinces`, `/provinces/{gid}/districts`). This is a Design-phase (Plan)
  decision and is intentionally left open here; the RFC only commits to exposing
  per-level listing scoped to parent. Engineer leans toward a single generic
  list endpoint; to be settled in the Design Doc.

---
Revision history

| Version | Date       | Author                | Changes                                                                 |
|---------|------------|-----------------------|-------------------------------------------------------------------------|
| v0.1    | 2026-06-09 | AI-drafted, azonarate | Initial draft                                                           |
| v0.1    | 2026-06-10 | AI-drafted, azonarate | Resolved open questions (?q= deferred, GEO-1 confirmed, sort by name); added intended cascade flow |
| v1.0    | 2026-06-10 | AI-drafted, azonarate | Approved by satya — Align gate closed                                   |
