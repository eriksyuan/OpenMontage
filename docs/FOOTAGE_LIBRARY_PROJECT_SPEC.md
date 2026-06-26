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
4. **Provides** a **web admin console** (后台管理页面) for operators to upload, tag, browse, preview, and manage clips — **required in v1**, not optional.
5. **Integrates** with OpenMontage without embedding storage logic in OpenMontage.

OpenMontage remains a **thin client**: search → fetch proxy to local cache → compose. It never holds master files or COS credentials.

---

## 2. Non-Goals (Do Not Build in v1)

- Remotion / video composition
- **Public-facing** consumer portal (素材库对外展示站 — 不做；**内部 Admin 后台必做**，见 §10)
- User-facing video editor / timeline editor
- 123pan / other cloud drives as primary storage (COS only for v1; archive backends are future work)
- Streaming large files through the API body (always use COS pre-signed URLs)
- Multi-region replication
- Billing / payment (only optional quota counters per API key)
- Multi-tenant RBAC with fine-grained roles (v1: single admin login + API keys)

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

Create a **monorepo** with Python API backend + React admin frontend:

```
openmontage-footage/
├── README.md
├── pyproject.toml              # Python 3.11+, FastAPI, uvicorn, pydantic v2
├── .env.example
├── openapi.yaml                # Generated from FastAPI; must match §8–§9
├── Dockerfile                  # Multi-stage: API + admin static build
├── docker-compose.yml          # api + admin (nginx) + optional worker
│
├── app/                        # ===== Backend (FastAPI) =====
│   ├── main.py                 # FastAPI app, CORS, static mount for /admin
│   ├── config.py
│   ├── auth.py                 # Bearer keys + admin session (§10.2)
│   ├── models/
│   ├── storage/
│   ├── index/
│   ├── ingest/
│   ├── api/
│   │   ├── v1_public.py
│   │   └── v1_admin.py         # Includes UI-oriented list/stats routes (§9)
│   └── cli/
│       └── main.py
│
├── admin/                      # ===== Frontend Admin Console (Required v1) =====
│   ├── package.json            # React 19 + Vite + TypeScript
│   ├── vite.config.ts
│   ├── index.html
│   ├── tailwind.config.ts      # Tailwind CSS v4
│   ├── src/
│   │   ├── main.tsx
│   │   ├── App.tsx
│   │   ├── api/                # Typed fetch client → backend OpenAPI
│   │   │   └── client.ts
│   │   ├── auth/               # Login, session token storage
│   │   │   └── AuthProvider.tsx
│   │   ├── pages/
│   │   │   ├── LoginPage.tsx
│   │   │   ├── DashboardPage.tsx
│   │   │   ├── ClipsPage.tsx           # Grid/list + filters
│   │   │   ├── ClipDetailPage.tsx      # Preview + edit metadata
│   │   │   ├── UploadPage.tsx          # Drag-drop + batch upload
│   │   │   ├── IngestJobsPage.tsx      # Job queue & progress
│   │   │   ├── CollectionsPage.tsx     # Manage collections taxonomy
│   │   │   ├── SearchPreviewPage.tsx   # Test semantic search (admin)
│   │   │   └── SettingsPage.tsx        # Health, API keys display, COS status
│   │   ├── components/
│   │   │   ├── layout/         # Sidebar, Header, AppShell
│   │   │   ├── clips/          # ClipCard, ClipGrid, VideoPlayer, TagInput
│   │   │   ├── upload/         # DropZone, UploadQueue, ProgressBar
│   │   │   └── ui/             # Button, Modal, Toast, Pagination, EmptyState
│   │   ├── hooks/
│   │   │   ├── useClips.ts
│   │   │   ├── useIngestJob.ts
│   │   │   └── useUpload.ts
│   │   └── lib/
│   │       └── format.ts
│   └── public/
│
├── tests/
├── scripts/
└── deploy/
    └── nginx.conf              # Serve admin SPA + reverse proxy /v1 → api
```

**Backend:** Python 3.11+, FastAPI, Typer, `cos-python-sdk-v5`, ffmpeg/ffprobe  
**Admin frontend:** React 19, Vite, TypeScript, Tailwind CSS v4, React Router  
**Admin UI language:** 中文界面为主（labels、按钮、空状态、错误提示），代码与 API 字段保持英文

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

# Admin Web Console
ADMIN_SESSION_SECRET=change-me-in-production   # JWT/session signing
ADMIN_PASSWORD=your-admin-password             # v1 single-operator login
ADMIN_SESSION_TTL_HOURS=24
ADMIN_CORS_ORIGINS=http://localhost:5173,https://footage.example.com
ADMIN_BASE_PATH=/admin                         # SPA mount path in production
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
| **Admin Web Console** upload page (`POST /v1/admin/ingest`) | admin session | **Required** |
| `POST /v1/admin/ingest` (multipart file) | admin session or admin API key | **Required** |
| `POST /v1/admin/ingest` (JSON `{ "source_url": "..." }`) | admin | Optional |
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

### 9.6 Admin UI support endpoints (Required for Web Console)

These routes power the **后台管理页面**. All require `admin` scope (session cookie or Bearer admin key).

#### `POST /v1/admin/auth/login`

Browser login — avoids storing raw API keys in frontend source.

**Request:**

```json
{ "password": "your-admin-password" }
```

**Response 200:**

```json
{
  "token": "eyJ...",
  "expires_at": 1719480000,
  "scope": "admin"
}
```

Frontend stores token in `sessionStorage` (or HttpOnly cookie if backend sets it). Subsequent requests: `Authorization: Bearer <token>`.

Alternative login: `{ "api_key": "sk_admin_..." }` for power users.

#### `POST /v1/admin/auth/logout`

Invalidate session (no-op if JWT stateless; document behavior).

#### `GET /v1/admin/stats`

Dashboard metrics.

```json
{
  "clip_count": 1234,
  "active_count": 1200,
  "processing_count": 3,
  "failed_count": 2,
  "archived_count": 29,
  "ingest_jobs_today": 15,
  "collections_count": 7,
  "storage_bytes_estimate": 53687091200,
  "recent_ingests": [
    { "job_id": "...", "clip_id": "...", "status": "active", "filename": "sample.mp4", "created_at": 1719400000 }
  ]
}
```

#### `GET /v1/admin/clips`

Paginated clip browser for admin grid.

**Query params:**

| Param | Default | Description |
|-------|---------|-------------|
| `page` | 1 | Page number |
| `page_size` | 24 | 12 / 24 / 48 |
| `status` | `active` | `active` \| `processing` \| `failed` \| `archived` \| `all` |
| `collection` | — | Filter by collection |
| `kind` | — | `video` \| `image` |
| `q` | — | Keyword search on tags + source_tags + clip_id |
| `sort` | `added_at_desc` | `added_at_desc` \| `added_at_asc` \| `duration_desc` |

**Response 200:**

```json
{
  "page": 1,
  "page_size": 24,
  "total": 156,
  "items": [
    {
      "clip_id": "footage_a1b2c3d4",
      "kind": "video",
      "status": "active",
      "duration": 12.4,
      "width": 1920,
      "height": 1080,
      "collections": ["nature"],
      "tags": ["forest"],
      "source_tags": "misty forest morning",
      "thumb_url": "https://...presigned.../frame_02.jpg",
      "added_at": 1719400000
    }
  ]
}
```

#### `GET /v1/admin/ingest/jobs`

List ingest jobs (newest first).

**Query:** `page`, `page_size`, `status` (optional filter)

**Response:** `{ "page", "page_size", "total", "items": [ IngestJob ] }`

#### `GET /v1/admin/collections`

List all collections with clip counts.

```json
{
  "collections": [
    { "name": "nature", "clip_count": 420, "description": "" },
    { "name": "city", "clip_count": 88, "description": "" }
  ]
}
```

#### `POST /v1/admin/collections`

Create or update collection metadata (does not ingest clips).

```json
{ "name": "chinese-history-drama", "description": "古装剧情类影视素材" }
```

#### `DELETE /v1/admin/collections/{name}`

Remove collection label from taxonomy. **Does not** delete clips — only removes collection name from registry (clips retain the tag until edited).

#### `POST /v1/admin/clips/{clip_id}/preview-url`

Return short-lived presigned URL for **proxy video** or image thumb — used by admin `<video>` player.

```json
{
  "clip_id": "footage_xxx",
  "url": "https://...",
  "expires_at": 1719400900,
  "kind": "video"
}
```

#### `POST /v1/admin/search-preview`

Same body as `POST /v1/search` but admin-only; returns full clip metadata + preview URLs for UI search lab page.

---

## 10. Admin Web Console (后台管理页面) — Required v1

The admin console is the **primary operator interface** for uploading and managing footage. CLI and curl are secondary; the code agent **must** ship a working SPA.

### 10.1 Goals

Operators (非开发者) must be able to:

1. Log in securely
2. Upload single/batch video and image files with drag-and-drop
3. Fill metadata (collections, tags, mood, license, shot_type, source_tags)
4. Watch ingest progress until `active` or see failure reason
5. Browse all clips in a visual grid with thumbnails
6. Preview proxy video inline
7. Edit metadata and archive clips
8. Manage collection taxonomy
9. Test semantic search (same engine OpenMontage uses)
10. View system health (COS, catalog, ffmpeg)

### 10.2 Authentication UX

**Login page** (`/admin/login`):

- Fields: 管理员密码 (maps to `ADMIN_PASSWORD`) **or** Admin API Key (advanced toggle)
- On success → redirect to `/admin/dashboard`
- Store JWT/session token; attach to all API calls
- Auto-logout on 401; show 登录已过期 toast

**Do not** embed admin API keys in frontend build artifacts or `VITE_*` env vars.

### 10.3 Page Specifications

#### Dashboard (`/admin/dashboard`)

| Widget | Data source | UI |
|--------|-------------|-----|
| 素材总数 | `/v1/admin/stats` | Stat cards: 总数 / 可用 / 处理中 / 失败 / 已归档 |
| 今日入库 | stats | Number |
| 存储占用 | stats | Human-readable GB |
| 最近入库 | stats.recent_ingests | Table: 文件名, 状态, 时间, 跳转详情 |
| 系统状态 | `/v1/admin/health` | Green/red badges: COS / Catalog / FFmpeg / CLIP |

Primary CTA button: **上传素材** → `/admin/upload`

#### Upload (`/admin/upload`)

**Layout:**

```
┌─────────────────────────────────────────────────────────┐
│  上传素材                                                │
├─────────────────────────────────────────────────────────┤
│  ┌─────────────────────────────────────────────────┐   │
│  │  拖拽文件到此处，或点击选择                        │   │
│  │  支持 MP4 MOV MKV WebM JPG PNG WebP              │   │
│  │  单文件最大 2GB · 可多选                          │   │
│  └─────────────────────────────────────────────────┘   │
│                                                         │
│  默认元数据（应用于本批所有文件）                          │
│  ┌ Collections multi-select ─────────────────────┐     │
│  ┌ Tags chip input ──────────────────────────────┐     │
│  ┌ Mood multi-select ────────────────────────────┐     │
│  ┌ 授权类型 / 创作者 / 景别 / 时段 ────────────────┐     │
│  ┌ 检索描述 source_tags (textarea) ──────────────┐     │
│                                                         │
│  上传队列                                                │
│  ┌ file.mp4  ████████░░ 80%  indexing  [取消] ────┐     │
│  └ forest.jpg  ✓ 已完成  [查看] ──────────────────┘     │
└─────────────────────────────────────────────────────────┘
```

**Behavior:**

1. User selects files → show queue rows immediately
2. For each file: `POST /v1/admin/ingest` multipart with shared metadata + per-file defaults
3. Poll `GET /v1/admin/ingest/{job_id}` every 2s until terminal state
4. Progress bar mapped to job `progress` (0–1) and `status` label (上传中 / 转码中 / 索引中 / 完成 / 失败)
5. On success: row shows thumbnail + link to clip detail
6. On failure: show `error` message inline with retry button
7. Support **batch upload** (sequential or max 3 concurrent uploads — configurable)

**Per-file metadata override (v1 nice-to-have, v1.1 if tight):** expand row to edit tags before upload starts.

#### Clips Library (`/admin/clips`)

- **View:** responsive grid (card = thumb + duration badge + clip_id truncated + collection chips)
- **Filters sidebar:** status, collection, kind (video/image), keyword search
- **Sort:** 最新入库 / 最早 / 时长
- **Pagination:** 24 per page
- **Bulk actions (v1):** multi-select → 批量归档
- **Empty state:** 暂无素材，去上传

Click card → Clip Detail

#### Clip Detail (`/admin/clips/:clipId`)

**Layout:**

```
┌──────────────────┬──────────────────────────────────────┐
│  Video/Image     │  clip_id: footage_xxx    [复制]       │
│  preview player  │  状态: 可用                           │
│  (proxy URL)     │  1920×1080 · 12.4s · motion 0.35     │
│                  │  ─────────────────────────────────    │
│  Filmstrip of    │  Collections [editable multi-select]  │
│  5 thumb frames  │  Tags [chip input]                    │
│                  │  Mood / 景别 / 时段 / 授权 / 创作者      │
│                  │  检索描述 source_tags [textarea]       │
│                  │  [保存] [归档] [下载原片] [下载代理]      │
└──────────────────┴──────────────────────────────────────┘
```

- Load preview via `POST /v1/admin/clips/{id}/preview-url`
- Save → `PATCH /v1/admin/clips/{id}` with toast 保存成功
- 归档 → confirm modal → `DELETE /v1/admin/clips/{id}`
- Download buttons → open presigned URL in new tab

#### Ingest Jobs (`/admin/jobs`)

- Table: job_id, filename, clip_id, status, progress, created_at, error
- Filter by status
- Click row → job detail or clip detail if active
- Auto-refresh every 5s when any job is non-terminal

#### Collections (`/admin/collections`)

- List collections with clip counts
- Add collection: name + description (中文描述 OK)
- Cannot delete collection if clip_count > 0 without confirmation (or block with message)

#### Search Preview (`/admin/search`)

- Same UI as OpenMontage would use: query input + optional filters (collection, kind, duration)
- Call `POST /v1/admin/search-preview`
- Results grid with **score** displayed (0.00–1.00) for tuning tags/descriptions
- Purpose: operators verify CLIP indexing quality before OpenMontage production

#### Settings (`/admin/settings`)

- Read-only: API version, COS bucket/region, CLIP model, catalog path
- Health check button → `/v1/admin/health`
- Display **read-only** OpenMontage connection snippet:

  ```
  FOOTAGE_LIBRARY_API_URL=https://...
  FOOTAGE_LIBRARY_ACCESS_KEY=sk_read_...  (masked, copy button for admin)
  ```

- Logout button

### 10.4 UI/UX Requirements

| Requirement | Detail |
|-------------|--------|
| Language | 简体中文 UI copy |
| Responsive | Desktop-first; usable at 1280px+; upload page OK at 1024px |
| Loading | Skeleton cards on clip grid; spinner on preview load |
| Errors | Toast notifications; never silent fail |
| Video player | HTML5 `<video>` with proxy URL; show duration |
| Accessibility | Form labels, keyboard focus on modals, sufficient contrast |
| Theme | Light default; neutral grays + one accent color (e.g. blue) |

**Component library:** shadcn/ui or Headless UI + Tailwind — agent's choice, but must look professional, not raw HTML.

### 10.5 Frontend Technical Requirements

```json
// admin/package.json dependencies (minimum)
{
  "dependencies": {
    "react": "^19",
    "react-dom": "^19",
    "react-router-dom": "^7",
    "tailwindcss": "^4"
  },
  "devDependencies": {
    "typescript": "^5",
    "vite": "^6",
    "@vitejs/plugin-react": "^4"
  }
}
```

- **API client:** typed functions in `src/api/client.ts`; base URL from `import.meta.env.VITE_API_BASE_URL` (default `/` when proxied)
- **Dev proxy:** Vite dev server proxies `/v1` → `http://localhost:8080`
- **Production:** build `admin/dist` → served by nginx at `/admin/` or FastAPI `StaticFiles`
- **Routing:** SPA fallback — all `/admin/*` routes serve `index.html`

### 10.6 Deployment (docker-compose)

```yaml
services:
  api:
    build: .
    ports: ["8080:8080"]
    env_file: .env
    volumes: ["catalog-data:/var/lib/footage-library/catalog"]

  admin:
    build:
      context: ./admin
      dockerfile: Dockerfile
    ports: ["3000:80"]
    depends_on: [api]
    environment:
      VITE_API_BASE_URL: ""   # same-origin via nginx proxy

  # deploy/nginx.conf:
  #   /admin/  → admin container static
  #   /v1/     → api:8080
```

Single public port (e.g. 443 via nginx): operators visit `https://footage.example.com/admin/`.

### 10.7 Admin Frontend Acceptance Criteria

- [ ] Login with `ADMIN_PASSWORD` works; invalid password shows error
- [ ] Upload 1 MP4 via drag-drop → job progresses → clip appears in library grid
- [ ] Clip detail plays proxy video in browser
- [ ] Edit tags + source_tags → save → search preview finds clip with new query
- [ ] Archive clip → disappears from default library view
- [ ] Collections page shows correct counts
- [ ] Dashboard stats match actual catalog counts
- [ ] `npm run build` in `admin/` succeeds; production bundle served at `/admin/`

---

## 11. CLI (Internal Ops)

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

## 12. Authentication & Rate Limits

### 12.1 API keys

Parse `FOOTAGE_API_KEYS`:

```
sk_read_abc123:read,sk_admin_def456:admin
```

Middleware:

- Missing/invalid key → `401`
- `read` key on admin route → `403`

### 12.2 Rate limits (v1 simple)

In-memory per key:

- `read`: 60 search/min, 120 download URL/min
- `admin`: 10 ingest/min

Return `429` with `Retry-After` header.

### 12.3 Admin session auth

In addition to Bearer API keys, support **browser session** for admin UI:

- `POST /v1/admin/auth/login` validates `ADMIN_PASSWORD` or admin-scoped API key
- Issue signed JWT (HS256, `ADMIN_SESSION_SECRET`, TTL from `ADMIN_SESSION_TTL_HOURS`)
- JWT payload: `{ "sub": "admin", "scope": "admin", "exp": ... }`
- Middleware accepts either valid JWT **or** Bearer key with `admin` scope on `/v1/admin/*`

CORS: allow origins from `ADMIN_CORS_ORIGINS` with credentials if using cookies.

---

## 13. Error Format

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

## 14. OpenMontage Integration Contract (Downstream)

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

## 15. Collections & Taxonomy (Generic)

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

## 16. Implementation Phases & Acceptance Criteria

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

### Phase 4 — Admin API & Ops

**Deliver:**

- [ ] PATCH/DELETE clip admin routes
- [ ] Admin UI routes: stats, clips list, collections, auth login (§9.6)
- [ ] `footage reindex`, `footage sync-catalog`
- [ ] Rate limiting + structured errors
- [ ] Dockerfile (API) + docker-compose skeleton
- [ ] README with env setup, COS bucket policy notes

**Accept:** Docker API up → ingest via curl → search → download works end-to-end.

### Phase 5 — Admin Web Console (后台) **Required**

**Deliver:**

- [ ] React + Vite + Tailwind admin app under `admin/` (§10)
- [ ] All pages: Login, Dashboard, Upload, Clips, Clip Detail, Jobs, Collections, Search Preview, Settings
- [ ] Drag-drop upload with job polling and progress UI
- [ ] Inline video preview on clip detail
- [ ] nginx or FastAPI static serving at `/admin/`
- [ ] Admin Dockerfile + docker-compose `admin` service

**Accept:** Operator opens `http://localhost:3000/admin/` (or compose URL) → logs in → uploads MP4 → sees clip in grid → previews video → edits tags → search preview finds it. All §10.7 checkboxes pass.

### Phase 6 — Polish & OpenMontage Handoff

**Deliver:**

- [ ] OpenMontage curl examples in README
- [ ] `openapi.yaml` complete including §9.6 admin UI routes
- [ ] Basic Playwright or Vitest smoke test for login + upload flow (optional but recommended)

**Accept:** Full §22 Definition of Done.

---

## 17. Testing Requirements

| Test | Requirement |
|------|-------------|
| `test_embedder_dim` | Output vectors shape `(N,512)`, unit norm |
| `test_catalog_atomic_write` | Concurrent append does not corrupt index |
| `test_search_ranking` | Known clip ranks above random unrelated clip |
| `test_ingest_video` | Fixture MP4 → active record + npy row added |
| `test_presign` | Mock COS client returns HTTPS URL |
| `test_auth_scopes` | read key blocked from admin routes |

| `test_auth_scopes` | read key blocked from admin routes |
| `admin/build` | CI runs `npm run build` in `admin/` without error |

Use pytest for backend. For frontend: at minimum `npm run build` in CI; optional Vitest component tests or Playwright e2e for login → upload happy path.

---

## 18. Security Checklist

- [ ] Never log `COS_SECRET_KEY` or API keys
- [ ] COS bucket policy: private; only server role has Put/Get
- [ ] Pre-signed URLs short-lived; read keys cannot presign `original` unless admin
- [ ] Validate uploaded MIME/types; reject executables
- [ ] Max upload size enforced at reverse proxy + app layer
- [ ] CORS: restrict to known origins in production (configurable)
- [ ] Admin JWT secret rotated in production; `ADMIN_PASSWORD` not default
- [ ] Admin SPA never ships with embedded API keys
- [ ] Content-Security-Policy on admin static assets (basic)

---

## 19. COS Bucket Policy Notes (README)

Document for operators:

1. Create bucket in same region as API server (lower latency).
2. Block public read; all access via pre-signed URLs or server credentials.
3. Enable lifecycle rule optional: move `original/` to IA after 90 days (operator choice).
4. CAM sub-account with minimal policy: `cos:PutObject`, `cos:GetObject`, `cos:HeadObject`, `cos:DeleteObject` on `bucket/prefix/*`.

---

## 20. Example curl Flow (Copy to README)

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

## 21. Definition of Done

The project is **complete** when a code agent can demonstrate:

1. Fresh clone + `.env` + `docker compose up` (API + admin)
2. Open **`/admin/`** in browser → login → upload MP4 via UI → clip appears in library
3. Clip detail plays proxy video; metadata edit persists
4. Search preview page returns ingested clip for relevant query
5. Public API: search + download works with **read** API key (OpenMontage path)
6. Catalog files exist locally and (if enabled) on COS
7. `pytest` passes; `cd admin && npm run build` passes
8. `openapi.yaml` served at `/openapi.json` matches §8–§9 including §9.6

---

## 22. OpenMontage File References (Read-Only Context)

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
