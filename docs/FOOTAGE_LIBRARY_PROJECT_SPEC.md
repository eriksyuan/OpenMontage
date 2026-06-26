# OpenMontage Footage Library — Code Agent Implementation Spec

> **Audience:** Code agent building the **standalone** repository `openmontage-footage` (name flexible).
> **Consumer:** OpenMontage video production platform connects via **OpenAPI + Bearer Access Key**.
> **Storage:** Tencent Cloud COS (对象存储) as primary blob store.
> **Scope:** Universal footage library — **not** limited to history/drama; history is one `collection` among many.

---

## 1. Mission

Build a self-hosted **footage library service** that:

1. **Ingests** video/image assets (upload, metadata, transcoding, thumbnails, CLIP indexing).
2. **Stores** originals + proxies + thumbnails on **Tencent COS**.
3. **Exposes** a versioned **REST OpenAPI** for semantic search and signed download URLs.
4. **Integrates** with OpenMontage without embedding storage logic in OpenMontage.

OpenMontage remains a **thin client**: search → fetch proxy to local cache → compose. It never holds master files or COS credentials.

---

## 2. Non-Goals (Do Not Build in v1)

- Remotion / video composition
- User-facing video editor
- 123pan / other cloud drives as primary storage (COS only for v1; archive backends are future work)
- Streaming large files through the API body (always use COS pre-signed URLs)
- Multi-region replication
- Billing / payment (only optional quota counters per API key)

---

## 3. Reference: OpenMontage Contracts

Align with existing OpenMontage types so integration is trivial later.

### 3.1 Clip index shape (`ClipRecord` + extensions)

Base fields mirror `lib/corpus.py` in OpenMontage:

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `clip_id` | string | yes | Format: `footage_<uuid>` or `footage_<slug>` |
| `source` | string | yes | Always `"footage_library"` for API consumers |
| `source_id` | string | yes | Internal id without prefix |
| `source_url` | string | no | Human landing page if any |
| `kind` | enum | yes | `"video"` \| `"image"` |
| `duration` | float | yes | Seconds; `0` for images |
| `width` | int | yes | |
| `height` | int | yes | |
| `creator` | string | no | |
| `license` | string | no | e.g. `"internal"`, `"commercial"`, `"editorial"` |
| `source_tags` | string | no | Flat text for CLIP tag channel + display |
| `shot_type` | string | no | `wide` \| `medium` \| `close` \| `extreme_close` \| `""` |
| `time_of_day` | string | no | `day` \| `golden` \| `night` \| `""` |
| `motion_score` | float | no | Mean abs diff between sampled frames (see §7.3) |
| `dominant_colors` | int[3][] | no | Optional, can be `[]` in v1 |
| `added_at` | float | yes | Unix timestamp |

**Extensions (footage-library-specific):**

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `collections` | string[] | no | e.g. `["nature","city","chinese-history-drama"]` |
| `tags` | string[] | no | Free-form tags |
| `mood` | string[] | no | e.g. `["tense","calm"]` |
| `status` | enum | yes | `active` \| `processing` \| `failed` \| `archived` |
| `storage` | object | yes | See §5.2 |
| `thumb_urls` | string[] | no | HTTPS URLs to frame JPGs (for agent preview) |

### 3.2 CLIP model (must match OpenMontage)

Use **exactly**:

- Model: `openai/clip-vit-base-patch32`
- Dimension: **512**
- Vectors: **L2-normalized** float32
- Visual embedding: average of frame embeddings, re-normalized (same as `pool_frames()` in OpenMontage `lib/clip_embedder.py`)
- Tag embedding: CLIP text embedding of `source_tags` (fallback: joined `tags` or `"untitled"`)

Store:

- `embeddings.npy` — shape `(N, 512)` visual
- `tag_embeddings.npy` — shape `(N, 512)` text
- Row `i` in `index.jsonl` line `i` aligns with row `i` in both `.npy` files (same as OpenMontage `Corpus` class).

### 3.3 Search scoring (match OpenMontage fused rank)

Default fused score for query text `q`:

```
score = (1 - tag_weight) * cos(clip_emb, embed(q)) + tag_weight * cos(tag_emb, embed(q))
```

Default `tag_weight = 0.3`.

Optional filters (applied before or after ranking):

- `collections` — clip must intersect
- `tags` — any match
- `kind` — `video` \| `image`
- `motion_min` — minimum `motion_score`
- `min_duration` / `max_duration`
- `exclude_ids` — skip clip_ids
- `status` — default only `active`

---

## 4. Repository Layout

Create a new Python project with this structure:

```
openmontage-footage/
├── README.md
├── pyproject.toml              # Python 3.11+, FastAPI, uvicorn, pydantic v2
├── .env.example
├── openapi.yaml                # Generated from FastAPI or hand-written; must match §8
├── Dockerfile
├── docker-compose.yml          # api + optional postgres for v2 scale
│
├── app/
│   ├── main.py                 # FastAPI app, router mount, lifespan
│   ├── config.py               # pydantic-settings from env
│   ├── auth.py                 # Bearer key validation, admin vs read scopes
│   ├── models/
│   │   ├── clip.py             # ClipRecord pydantic models
│   │   ├── ingest.py           # Ingest job models
│   │   └── api.py              # Request/response DTOs
│   ├── storage/
│   │   ├── cos.py              # Tencent COS upload/download/presign
│   │   └── paths.py            # Key naming helpers
│   ├── index/
│   │   ├── catalog.py          # Load/save index.jsonl + npy, row alignment
│   │   ├── embedder.py         # CLIP wrapper (same semantics as OpenMontage)
│   │   └── search.py           # Fused ranking, filters, MMR optional
│   ├── ingest/
│   │   ├── pipeline.py         # Orchestrate ingest job steps
│   │   ├── probe.py            # ffprobe width/height/duration
│   │   ├── transcode.py        # ffmpeg proxy + thumbs
│   │   └── worker.py           # Background task runner (asyncio or arq/celery)
│   ├── api/
│   │   ├── v1_public.py        # /v1/info, /v1/search, /v1/clips/*
│   │   └── v1_admin.py         # /v1/admin/*
│   └── cli/
│       └── main.py             # Typer CLI: ingest, reindex, doctor
│
├── tests/
│   ├── test_search.py
│   ├── test_ingest.py
│   ├── test_cos_mock.py
│   └── fixtures/sample.mp4
│
└── scripts/
    └── bootstrap_catalog.py    # Empty catalog init
```

**Language:** Python 3.11+  
**API framework:** FastAPI  
**CLI:** Typer  
**COS SDK:** `cos-python-sdk-v5` (official Tencent)  
**Media:** ffmpeg + ffprobe (system dependencies, document in README)

---

## 5. Tencent Cloud COS

### 5.1 Environment variables

```bash
# COS
COS_SECRET_ID=AKID...
COS_SECRET_KEY=...
COS_REGION=ap-guangzhou          # e.g. ap-beijing, ap-shanghai
COS_BUCKET=your-bucket-1250000000

# Optional path prefix inside bucket
COS_PREFIX=footage               # default: footage

# Catalog persistence
# v1: local disk path synced to COS periodically
CATALOG_DIR=/var/lib/footage-library/catalog
CATALOG_SYNC_TO_COS=true         # upload index.jsonl + npy after each ingest

# API
FOOTAGE_API_HOST=0.0.0.0
FOOTAGE_API_PORT=8080
FOOTAGE_API_KEYS=sk_read_xxx:read,sk_admin_yyy:admin   # comma-separated key:scope

# Ingest
PROXY_MAX_HEIGHT=720
PROXY_CRF=23
THUMBS_PER_VIDEO=5
MAX_UPLOAD_BYTES=2147483648      # 2GB default

# Search
TAG_WEIGHT_DEFAULT=0.3
SEARCH_DEFAULT_TOP_K=10
```

### 5.2 Object key layout

All keys relative to bucket (with optional `COS_PREFIX`):

```
{prefix}/original/{clip_id}.mp4
{prefix}/proxy/{clip_id}_720p.mp4
{prefix}/thumb/{clip_id}/frame_00.jpg
{prefix}/thumb/{clip_id}/frame_01.jpg
...
{prefix}/catalog/index.jsonl
{prefix}/catalog/embeddings.npy
{prefix}/catalog/tag_embeddings.npy
```

`storage` object in catalog:

```json
{
  "original": "cos://{bucket}/{prefix}/original/{clip_id}.mp4",
  "proxy": "cos://{bucket}/{prefix}/proxy/{clip_id}_720p.mp4",
  "thumb_prefix": "cos://{bucket}/{prefix}/thumb/{clip_id}/"
}
```

### 5.3 COS operations required

Implement in `app/storage/cos.py`:

| Function | Purpose |
|----------|---------|
| `upload_file(local_path, cos_key)` | Put object |
| `download_file(cos_key, local_path)` | Get object |
| `presign_get(cos_key, expires_seconds=900)` | Pre-signed HTTPS URL for clients |
| `exists(cos_key)` | Head object |
| `delete(cos_key)` | Delete (admin archive) |

**Pre-signed URL expiry:** default **900 seconds (15 min)** for download endpoints.

OpenMontage downloads directly from COS using the signed URL — **not** through your API body.

---

## 6. Ingest Pipeline

### 6.1 Triggers

| Entry | Auth | v1 |
|-------|------|-----|
| `POST /v1/admin/ingest` (multipart file) | admin key | **Required** |
| `POST /v1/admin/ingest` (JSON `{ "source_url": "..." }`) | admin key | Optional |
| CLI `footage ingest ./file.mp4 --collection nature --tags a,b` | local | **Required** |

### 6.2 Ingest job state machine

```
pending → uploading → transcoding → indexing → active
                              ↘ failed (with error message)
```

Persist jobs in SQLite (`ingest_jobs.db`) or JSONL under `CATALOG_DIR/jobs/` for v1.

### 6.3 Steps (implement in order)

1. **Validate input**
   - Allowed video: `.mp4`, `.mov`, `.mkv`, `.webm`
   - Allowed image: `.jpg`, `.jpeg`, `.png`, `.webp`
   - Reject if over `MAX_UPLOAD_BYTES`

2. **Allocate `clip_id`**
   - `footage_` + url-safe uuid4 hex (e.g. `footage_a1b2c3d4e5f6`)

3. **Upload original → COS** `original/{clip_id}.{ext}`

4. **Probe** via ffprobe: width, height, duration (video only)

5. **Transcode proxy** (video only)
   - ffmpeg: max height 720, H.264, AAC if audio present
   - Output: `proxy/{clip_id}_720p.mp4`
   - Upload proxy to COS

6. **Extract thumbnails**
   - Video: `THUMBS_PER_VIDEO` evenly spaced frames → JPG
   - Image: copy/resize as `frame_00.jpg` only
   - Upload to `thumb/{clip_id}/frame_NN.jpg`

7. **Compute motion_score** (video)
   - Same cheap metric as OpenMontage corpus_builder: mean absolute pixel diff between first and middle thumbnail (OpenCV). Store float.

8. **Build metadata**
   - Merge request fields: `collections`, `tags`, `mood`, `license`, `creator`, `source_tags`, `shot_type`, `time_of_day`
   - If `source_tags` empty: join `tags` with spaces

9. **CLIP index**
   - Visual: embed all thumb JPGs → pool → 512-d vector
   - Tag: embed `source_tags` → 512-d vector
   - Append row to catalog (atomic write — see §7)

10. **Set status** `active`, return clip record

### 6.4 Admin ingest request body

```json
{
  "collections": ["nature", "aerial"],
  "tags": ["forest", "fog", "drone"],
  "mood": ["calm"],
  "license": "internal",
  "creator": "team-a",
  "source_tags": "misty forest aerial morning light",
  "shot_type": "wide",
  "time_of_day": "golden"
}
```

Multipart: field name `file` for binary; JSON metadata as form field `metadata` (stringified JSON) or separate JSON endpoint variant.

### 6.5 Idempotency

- Re-ingest same file → new `clip_id` (v1). Do not dedupe by hash in v1.
- Reindex command (`footage reindex`) rebuilds embeddings from existing catalog rows without re-upload.

---

## 7. Catalog Management

### 7.1 Files

Under `CATALOG_DIR/`:

```
index.jsonl       # one JSON object per line, UTF-8
embeddings.npy    # float32 (N, 512)
tag_embeddings.npy
meta.json         # { "model_id", "clip_count", "updated_at", "cos_bucket" }
```

### 7.2 Atomic updates

On each successful ingest:

1. Load catalog into memory
2. Append record + embeddings
3. Write to temp files: `index.jsonl.tmp`, etc.
4. `os.replace()` atomically
5. If `CATALOG_SYNC_TO_COS=true`, upload all three catalog files to COS

Use a file lock (`filelock`) around catalog mutations for concurrent ingest safety.

### 7.3 Startup

On API boot:

1. If local catalog missing but COS catalog exists → download from COS
2. Load `index.jsonl` + npy into memory (acceptable for v1 up to ~50k clips)
3. Expose clip count in `/v1/info`

For >50k clips, document PostgreSQL+pgvector as v2 migration path (not required in v1).

---

## 8. OpenAPI — Public Endpoints (v1)

Base URL: `https://footage-api.example.com`  
Auth header: `Authorization: Bearer <access_key>`

Keys with scope `read` may call public routes only. Keys with scope `admin` may call admin routes.

### 8.1 `GET /v1/info`

**Response 200:**

```json
{
  "service": "openmontage-footage",
  "version": "1.0.0",
  "clip_count": 1234,
  "active_clip_count": 1200,
  "collections": ["nature", "city", "business", "chinese-history-drama"],
  "embedding": {
    "model_id": "openai/clip-vit-base-patch32",
    "dim": 512
  },
  "storage": {
    "backend": "tencent_cos",
    "bucket": "your-bucket-1250000000",
    "region": "ap-guangzhou"
  }
}
```

### 8.2 `POST /v1/search`

**Request:**

```json
{
  "query": "misty forest aerial morning",
  "top_k": 10,
  "tag_weight": 0.3,
  "filters": {
    "collections": ["nature"],
    "tags_any": ["forest"],
    "kind": "video",
    "motion_min": 0.0,
    "min_duration": 3.0,
    "max_duration": 60.0,
    "exclude_ids": ["footage_abc123"]
  }
}
```

**Response 200:**

```json
{
  "query": "misty forest aerial morning",
  "top_k": 10,
  "results": [
    {
      "clip_id": "footage_a1b2c3d4",
      "score": 0.87,
      "kind": "video",
      "duration": 12.4,
      "width": 1920,
      "height": 1080,
      "motion_score": 0.35,
      "source_tags": "misty forest aerial morning light",
      "collections": ["nature"],
      "tags": ["forest", "fog"],
      "shot_type": "wide",
      "time_of_day": "golden",
      "thumb_urls": [
        "https://...presigned.../frame_02.jpg"
      ]
    }
  ]
}
```

`thumb_urls`: return 1–2 presigned thumb URLs (middle frame preferred) so OpenMontage agent can visually verify without downloading video.

### 8.3 `GET /v1/clips/{clip_id}`

**Response 200:** Full clip record (§3.1) excluding raw embedding vectors.

**Response 404:** `{ "error": { "code": "not_found", "message": "..." } }`

### 8.4 `GET /v1/clips/{clip_id}/download`

**Query params:**

| Param | Default | Values |
|-------|---------|--------|
| `quality` | `proxy` | `proxy` \| `original` |

**Response 200:**

```json
{
  "clip_id": "footage_a1b2c3d4",
  "quality": "proxy",
  "url": "https://bucket.cos.ap-guangzhou.myqcloud.com/...",
  "expires_at": 1719400900,
  "bytes": 5242880,
  "content_type": "video/mp4",
  "checksum_sha256": "optional-in-v1"
}
```

Scope `read` may download `proxy` only. Scope `admin` may download `original`.

### 8.5 `POST /v1/clips/batch-download`

**Request:**

```json
{
  "clip_ids": ["footage_a", "footage_b"],
  "quality": "proxy"
}
```

**Response 200:**

```json
{
  "downloads": [
    { "clip_id": "footage_a", "url": "...", "expires_at": 1719400900 },
    { "clip_id": "footage_b", "url": "...", "expires_at": 1719400900 }
  ]
}
```

---

## 9. OpenAPI — Admin Endpoints (v1)

All require `admin` scope.

### 9.1 `POST /v1/admin/ingest`

- Content-Type: `multipart/form-data`
- Fields: `file` (required), `metadata` (JSON string, optional)
- **Response 202:**

```json
{
  "job_id": "ingest_7f3a...",
  "clip_id": "footage_a1b2c3d4",
  "status": "pending"
}
```

### 9.2 `GET /v1/admin/ingest/{job_id}`

```json
{
  "job_id": "ingest_7f3a...",
  "clip_id": "footage_a1b2c3d4",
  "status": "indexing",
  "progress": 0.8,
  "error": null,
  "clip": null
}
```

When `status=active`, include full `clip` object.

### 9.3 `PATCH /v1/admin/clips/{clip_id}`

Update metadata fields: `collections`, `tags`, `mood`, `source_tags`, `shot_type`, `time_of_day`, `license`, `status`.

If `source_tags` changes → recompute tag embedding row and save catalog.

### 9.4 `DELETE /v1/admin/clips/{clip_id}`

Soft delete: set `status=archived`. Do not delete COS objects in v1 (optional hard delete flag `?hard=true` for admin).

### 9.5 `GET /v1/admin/health`

COS connectivity, catalog loaded, ffmpeg available, CLIP model loadable, disk space.

---

## 10. CLI (Internal Ops)

Install entry point: `footage = app.cli.main:app`

| Command | Purpose |
|---------|---------|
| `footage doctor` | Run health checks (COS, ffmpeg, catalog, keys) |
| `footage ingest PATH [--collection c] [--tags t1,t2] [--json]` | Sync ingest one file |
| `footage ingest-dir DIR [--collection c] [--tags t1,t2]` | Batch ingest |
| `footage reindex [--clip-id ID]` | Rebuild embeddings |
| `footage sync-catalog` | Push/pull catalog between disk and COS |
| `footage serve` | Alias for uvicorn app.main:app |

CLI uses same ingest pipeline as admin API (call shared `ingest.pipeline` module).

---

## 11. Authentication & Rate Limits

### 11.1 API keys

Parse `FOOTAGE_API_KEYS`:

```
sk_read_abc123:read,sk_admin_def456:admin
```

Middleware:

- Missing/invalid key → `401`
- `read` key on admin route → `403`

### 11.2 Rate limits (v1 simple)

In-memory per key:

- `read`: 60 search/min, 120 download URL/min
- `admin`: 10 ingest/min

Return `429` with `Retry-After` header.

---

## 12. Error Format

All errors JSON:

```json
{
  "error": {
    "code": "invalid_request",
    "message": "Human readable message",
    "details": {}
  }
}
```

Standard codes: `unauthorized`, `forbidden`, `not_found`, `invalid_request`, `rate_limited`, `internal_error`, `ingest_failed`.

---

## 13. OpenMontage Integration Contract (Downstream)

After this project ships, OpenMontage will add (separate PR):

```bash
FOOTAGE_LIBRARY_API_URL=https://footage-api.example.com
FOOTAGE_LIBRARY_ACCESS_KEY=sk_read_abc123
```

Tools:

- `footage_search` → `POST /v1/search`
- `footage_fetch` → `GET /v1/clips/{id}/download?quality=proxy` + HTTP GET to signed URL → `~/.openmontage/footage_cache/{clip_id}.mp4`

**Your API response fields must remain stable** — OpenMontage agents depend on `clip_id`, `score`, `duration`, `thumb_urls`, download `url`.

Document in README a **"OpenMontage Quick Start"** section with curl examples.

---

## 14. Collections & Taxonomy (Generic)

Ship with **seed collections** (empty, documented in README only — no hardcoded content):

| Collection | Example use |
|------------|-------------|
| `nature` | Landscapes, wildlife |
| `city` | Urban B-roll |
| `business` | Office, meetings |
| `technology` | Devices, data centers |
| `people` | Crowds, portraits (rights permitting) |
| `abstract` | Textures, light leaks |
| `chinese-history-drama` | Period drama clips (one niche among many) |

Agents filter by `collections` at search time. **Do not** bake history-specific logic into ingest or ranking.

---

## 15. Implementation Phases & Acceptance Criteria

### Phase 1 — Foundation (MVP)

**Deliver:**

- [ ] FastAPI app with `/v1/info`, health
- [ ] COS upload/presign module with mocked tests
- [ ] Catalog load/save with file lock
- [ ] CLIP embedder matching OpenMontage semantics
- [ ] CLI `footage doctor`, `footage serve`

**Accept:** `footage doctor` passes with valid `.env` and empty catalog.

### Phase 2 — Ingest

**Deliver:**

- [ ] Full ingest pipeline (upload → proxy → thumbs → index)
- [ ] `POST /v1/admin/ingest` + job status endpoint
- [ ] CLI `footage ingest`

**Accept:** Ingest a 10s sample MP4 → clip appears in catalog → COS has original + proxy + thumbs → `status=active`.

### Phase 3 — Search & Download

**Deliver:**

- [ ] `POST /v1/search` with fused CLIP scoring + filters
- [ ] `GET /v1/clips/{id}` and `/download`
- [ ] `POST /v1/clips/batch-download`
- [ ] Presigned thumb URLs in search results

**Accept:** Search query related to ingested clip returns it in top 3; download URL fetches playable proxy MP4.

### Phase 4 — Admin & Ops

**Deliver:**

- [ ] PATCH/DELETE clip admin routes
- [ ] `footage reindex`, `footage sync-catalog`
- [ ] Rate limiting + structured errors
- [ ] Dockerfile + docker-compose
- [ ] README with env setup, COS bucket policy notes, OpenMontage curl examples

**Accept:** Docker compose up → ingest via curl → search → download works end-to-end.

---

## 16. Testing Requirements

| Test | Requirement |
|------|-------------|
| `test_embedder_dim` | Output vectors shape `(N,512)`, unit norm |
| `test_catalog_atomic_write` | Concurrent append does not corrupt index |
| `test_search_ranking` | Known clip ranks above random unrelated clip |
| `test_ingest_video` | Fixture MP4 → active record + npy row added |
| `test_presign` | Mock COS client returns HTTPS URL |
| `test_auth_scopes` | read key blocked from admin routes |

Use pytest. Mock COS and ffmpeg in unit tests; one optional integration test marked `@pytest.mark.integration` requiring real COS credentials.

---

## 17. Security Checklist

- [ ] Never log `COS_SECRET_KEY` or API keys
- [ ] COS bucket policy: private; only server role has Put/Get
- [ ] Pre-signed URLs short-lived; read keys cannot presign `original` unless admin
- [ ] Validate uploaded MIME/types; reject executables
- [ ] Max upload size enforced at reverse proxy + app layer
- [ ] CORS: restrict to known origins in production (configurable)

---

## 18. COS Bucket Policy Notes (README)

Document for operators:

1. Create bucket in same region as API server (lower latency).
2. Block public read; all access via pre-signed URLs or server credentials.
3. Enable lifecycle rule optional: move `original/` to IA after 90 days (operator choice).
4. CAM sub-account with minimal policy: `cos:PutObject`, `cos:GetObject`, `cos:HeadObject`, `cos:DeleteObject` on `bucket/prefix/*`.

---

## 19. Example curl Flow (Copy to README)

```bash
# Info
curl -s -H "Authorization: Bearer $FOOTAGE_READ_KEY" \
  https://api.example.com/v1/info | jq

# Ingest (admin)
curl -s -X POST -H "Authorization: Bearer $FOOTAGE_ADMIN_KEY" \
  -F "file=@sample.mp4" \
  -F 'metadata={"collections":["nature"],"tags":["forest","fog"]}' \
  https://api.example.com/v1/admin/ingest | jq

# Poll job
curl -s -H "Authorization: Bearer $FOOTAGE_ADMIN_KEY" \
  https://api.example.com/v1/admin/ingest/ingest_xxx | jq

# Search
curl -s -X POST -H "Authorization: Bearer $FOOTAGE_READ_KEY" \
  -H "Content-Type: application/json" \
  -d '{"query":"forest fog morning","top_k":5,"filters":{"collections":["nature"]}}' \
  https://api.example.com/v1/search | jq

# Download proxy
curl -s -H "Authorization: Bearer $FOOTAGE_READ_KEY" \
  "https://api.example.com/v1/clips/footage_xxx/download?quality=proxy" | jq -r .url \
  | xargs curl -L -o proxy.mp4
```

---

## 20. Definition of Done

The project is **complete** when a code agent can demonstrate:

1. Fresh clone + `.env` + `docker compose up`
2. Admin ingest of sample video via curl or CLI
3. Public search returns ingested clip with score and thumb URL
4. Download returns valid COS pre-signed URL; file plays in ffprobe
5. Catalog files exist locally and (if enabled) on COS
6. `pytest` passes (integration tests optional/skipped in CI)
7. `openapi.yaml` served at `/openapi.json` matches §8–§9

---

## 21. OpenMontage File References (Read-Only Context)

When implementing CLIP/search compatibility, mirror these OpenMontage files (do not copy the repo; reimplement equivalent logic):

| File | Purpose |
|------|---------|
| `lib/corpus.py` | `ClipRecord` fields, index.jsonl + npy alignment |
| `lib/clip_embedder.py` | Model id, normalization, pool_frames |
| `tools/video/corpus_builder.py` | Thumb extraction, motion_score, ingest steps |
| `tools/video/clip_search.py` | Fused ranking parameters (`tag_weight`, filters) |
| `tools/video/clip_cache.py` | Pattern reference for OpenMontage-side cache (not implemented here) |

---

*End of spec — hand this document to the code agent as the single source of truth for building `openmontage-footage`.*
