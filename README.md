# Local AI Chatbot Backend — Phase 1

Independent FastAPI service for local Ollama chat and MySathi manual retrieval. Frontend chatbot calls go directly to this AI server. Existing application APIs remain on their existing backend; this project has no AWS SDK or integration. PostgreSQL stores chatbot sessions/messages and the pgvector knowledge base. Inference and embeddings use local Ollama models.

## Architecture

`Frontend → AI Server (FastAPI) → PostgreSQL (history) + Ollama (inference)`

The API keeps the most recent `MAX_CONTEXT_MESSAGES` messages, adds the configured system prompt, then sends them to Ollama using its local `/api/chat` endpoint. The history cap counts messages, not turns.

## Requirements

Python 3.12+, PostgreSQL 14+ (or Docker), Ollama installed on the AI Server host, and Qwen3 14B. Docker Compose is optional. Ollama is intentionally not included in Compose.

## Python setup

```bash
cd ai-chatbot-backend
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp -n .env.example .env
```

Set a strong unique `CHAT_API_KEY` and database password in `.env` before exposing this service. `.env` is ignored by Git. The sample database credentials and API key are placeholders only. Compose publishes its PostgreSQL service on loopback port 5434 to avoid colliding with an existing PostgreSQL listener on 5432 or 5433.

## PostgreSQL setup

Create database `ai_chatbot`, then set `DATABASE_URL` in `.env`, for example:

```env
DATABASE_URL=postgresql+asyncpg://postgres:YOUR_PASSWORD@localhost:5434/ai_chatbot
```

Apply schema migrations:

```bash
alembic upgrade head
```

Rollback the most recent migration with `alembic downgrade -1`.

## Ollama setup

Install Ollama on the AI Server host, then download and start the model:

```bash
ollama pull qwen3:14b
ollama serve
```

Defaults are `OLLAMA_BASE_URL=http://127.0.0.1:11434`, `OLLAMA_MODEL=qwen3:14b`, and `OLLAMA_TIMEOUT=120`; configure them in `.env`. Keep Ollama bound to loopback or a private interface and firewall port 11434 from public access. The API never calls an external AI provider.

## Local development

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Check `curl http://localhost:8000/health`, `/health/database`, and `/health/ollama`. Interactive OpenAPI docs are at `/docs`; ReDoc is at `/redoc`.

## Docker deployment

Set `.env` and use `docker compose up --build -d`. Compose starts FastAPI and PostgreSQL only. The container reaches Ollama on the host through `host.docker.internal`; change `OLLAMA_BASE_URL` in the container environment to `http://host.docker.internal:11434`. On Linux, Compose configures that hostname with `host-gateway`. Ollama must listen on an address reachable from the container, with host firewall rules restricting access. Do not publish Ollama port 11434 publicly. The API container runs `alembic upgrade head` at startup.

## Authentication and endpoints

Protected routes require `Authorization: Bearer <CHAT_API_KEY>`:

- `POST /api/v1/chat` — send message, optionally with a UUID `session_id`
- `GET /api/v1/sessions?limit=50` — list active sessions
- `GET /api/v1/sessions/{session_id}` — get a session
- `GET /api/v1/sessions/{session_id}/messages` — get its messages
- `DELETE /api/v1/sessions/{session_id}` — deactivate a session

Public health routes: `GET /health`, `/health/ollama`, `/health/database`.

Example:

```bash
curl -X POST http://localhost:8000/api/v1/chat \
  -H 'Authorization: Bearer YOUR_CHAT_API_KEY' \
  -H 'Content-Type: application/json' \
  -d '{"message":"How can I book a wheelchair?"}'
```

Messages are limited by `MAX_MESSAGE_LENGTH`. CORS origins are comma-separated in `CORS_ORIGINS`. `RATE_LIMIT_PER_MINUTE` is a process-local in-memory per-IP limit; it is not shared across workers or instances and should be replaced with Redis-backed limiting for scaled deployments.

## Tests

Unit tests mock Ollama and do not require a real LLM. Install dependencies and run `pytest`. Full endpoint/database integration requires PostgreSQL and is separate from the isolated unit suite.

## Troubleshooting

- Database health returns 503: confirm PostgreSQL is running, database exists, credentials are correct, then run migrations.
- Ollama health returns 503: confirm `ollama serve`, URL reachability, and `ollama list` contains the exact configured model tag.
- Container cannot reach host Ollama: configure `OLLAMA_BASE_URL=http://host.docker.internal:11434`, allow host gateway traffic, and ensure Ollama listens on an interface reachable by the container.
- 401: send the exact bearer key configured in `.env`.
- 429: wait for the one-minute window to expire or adjust the configured development limit.

## Production recommendations

Use TLS/reverse proxy, strong rotated API keys, network restrictions, secret management, database backups, monitoring, and a shared rate limiter. Do not expose Ollama directly to the internet. Consider ownership checks before adding authenticated end-user IDs; session IDs are currently bearer-accessible to anyone who knows them and has the shared API key.

## Local MySathi RAG

The chatbot can retrieve passages from the supplied MySathi bilingual product and operations manual before sending a question to the existing local Qwen chat model. Text and tables are extracted in document order, headings are retained, and English/Hindi text is preserved. No fine-tuning, internet search, AWS integration, or public upload endpoint is used. Retrieved passages are supplied as reference data and the RAG system prompt tells the model to ignore any instructions inside them. The `/api/v1/chat` request and response schemas, authentication, and chat logging remain unchanged.

### RAG prerequisites and configuration

- PostgreSQL 16 with the pgvector server extension. The Compose database uses `pgvector/pgvector:pg16`.
- Local Ollama with `qwen3:14b` for generation and `bge-m3:latest` for multilingual embeddings.
- The `pgvector` Python package is installed from `requirements.txt`.

The current installed `bge-m3:latest` model reports and returns 1024-element vectors. `EMBEDDING_DIMENSIONS=1024` matches the migration's `vector(1024)` column. Embedding calls validate the model's actual returned dimension; a mismatch fails clearly rather than writing incompatible vectors. If a different dimension model is selected, make a migration that alters the vector column and HNSW index before changing the configured dimension.

RAG settings are in `.env`: `RAG_ENABLED`, `RAG_SYSTEM_PROMPT`, `EMBEDDING_MODEL`, `EMBEDDING_DIMENSIONS`, `RAG_TOP_K`, `RAG_SIMILARITY_THRESHOLD`, `RAG_CHUNK_SIZE`, `RAG_CHUNK_OVERLAP`, and `RAG_EMBEDDING_BATCH_SIZE`. Defaults are 8 retrieved chunks, cosine similarity threshold 0.50, 1800 character chunks, 240 character overlap, and 32 texts per embedding request. I embedded the source chunks and 15 manual-grounded evaluation questions with local `bge-m3:latest`: exact reference evidence appeared in the top 8 for 15/15 cases. The best matching evidence scored at least 0.504; four unrelated sample questions scored at most 0.463. The top 8 context fits under the configured 18,000-character context cap. These are initial values measured for this manual and model; inspect retrieval output and retune when the source or model changes.

### Start PostgreSQL, Ollama, and the API

From the project directory:

```bash
cp -n .env.example .env
# Set strong CHAT_API_KEY and POSTGRES_PASSWORD values; keep .env private.
docker compose up -d db
pg_isready -h 127.0.0.1 -p 5434 -U postgres
systemctl status ollama
```

If Ollama is managed by systemd, ensure `ollama.service` is active instead of starting a second server. Install missing local models with:

```bash
ollama pull qwen3:14b
ollama pull bge-m3:latest
```

Apply the new vector and knowledge tables migration, then start FastAPI:

```bash
.venv/bin/python -m alembic upgrade head
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
```

`RAG_ENABLED=true` is the default. Set it to `false` to temporarily restore the original general Ollama prompt while retaining the existing API contract.

### Ingest the supplied training manual

Run from `/home/desktop-7cj2sm7/Desktop/ai-chatbot-backend` after migrations and Ollama are available:

```bash
.venv/bin/python -m app.rag.ingest --file "/home/desktop-7cj2sm7/Downloads/MySathi_User_Mobile_App_Master_Product_Operations_Training_Manual_Final.docx"
```

The command computes a SHA-256 hash. Repeating an identical file skips it without duplicating chunks. A changed file with the same filename becomes a new active version; its earlier version remains stored but is excluded from retrieval. The CLI reports document name, page metadata when available, chunks and embeddings created, duplicate skips, and errors.

When using the Compose database, the host-side CLI must use the published port `5434` in `DATABASE_URL`. Alternatively, run ingestion in the API container and mount the manual read-only:

```bash
docker compose run --rm \
  -v "/home/desktop-7cj2sm7/Downloads/MySathi_User_Mobile_App_Master_Product_Operations_Training_Manual_Final.docx:/tmp/mysathi-manual.docx:ro" \
  --entrypoint python api -m app.rag.ingest --file /tmp/mysathi-manual.docx
```

The supplied DOCX has no embedded rendered page-break positions, and its document page-count property is not reliable. Ingestion therefore leaves page numbers null instead of assigning fabricated citations. It also contains no embedded images, so text and table extraction covers its current content.

### Test retrieval and chat

Search without involving Qwen generation:

```bash
.venv/bin/python -m app.rag.search "How can I book a wheelchair?"
```

Search results include their filename, section, subsection, page if available, cosine similarity, and content. The internal CLI requires local database access; no public retrieval route was added.

Run the stored manual evidence evaluation after ingestion:

```bash
.venv/bin/python -m app.rag.evaluate
```

Test the authenticated chatbot using the key configured in `.env`:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/chat \
  -H 'Authorization: Bearer YOUR_CHAT_API_KEY' \
  -H 'Content-Type: application/json' \
  -d '{"message":"How can I book a wheelchair?"}'
```

Run unit tests with `.venv/bin/python -m pytest -q`. The evaluation references in `tests/data/rag_evaluation.json` quote evidence from the manual; they do not add outside product facts.

### pgvector troubleshooting

If the migration reports that PostgreSQL cannot load the `vector` extension, the PostgreSQL server package is missing pgvector. For the project's Compose database, use `docker compose pull db && docker compose up -d db` so it runs `pgvector/pgvector:pg16`. For an existing host PostgreSQL installation, install the pgvector server extension package matching that exact PostgreSQL major version, restart PostgreSQL if required, then rerun `alembic upgrade head`. The migration runs `CREATE EXTENSION IF NOT EXISTS vector` and does not remove the shared extension on downgrade.

## Admin panel frontend

`admin-panel/` is a separate Next.js + TypeScript + Tailwind application in this repository. It does not replace the public chatbot frontend. It contains `/login`, `/dashboard`, `/users`, `/users/[userId]`, `/queries`, `/sessions`, and `/sessions/[sessionId]`. Query, user, and session tables request paginated results; list pages do not download the full chat history. Dashboard metrics render only from API responses and are not seeded with sample values.

Run it in a second terminal after starting FastAPI:

```bash
cd admin-panel
npm ci
cp -n .env.example .env.local
npm run dev
```

Set `ADMIN_API_ORIGIN` in `admin-panel/.env.local` to the FastAPI origin (default `http://127.0.0.1:8000`). Next.js rewrites `/api/v1/admin/*` to that origin, so browser code uses same-origin requests and never receives a database URL or admin secret. The frontend expects admin login to set a signed, `HttpOnly`, `SameSite=Strict` cookie named `admin_session` (also `Secure` in production); logout must clear it. The Next.js route proxy checks for the cookie to guide navigation, while authorization must still be enforced and validated by every backend admin endpoint.

### Admin API integration status

The frontend uses the implemented `/api/v1/admin/*` backend routes; the normal chatbot bearer key is not accepted as admin authentication. Lists return `{items, page, page_size, total, pages}`. Login accepts `{username, password}` and issues the HttpOnly session cookie. Never expose `ADMIN_PASSWORD_HASH`, session-signing secrets, or the normal chat API key to frontend code.

The public chat body remains `session_id` and `message`; verified application identity is passed separately in a signed header. Without configured identity validation, new chats remain anonymous. Existing `chat_messages` store user/assistant text, UTC timestamps, model, assistant generation latency, and newly added nullable RAG metadata.

### Admin backend setup and identity integration

The FastAPI admin backend uses a separate Argon2 password hash and revocable database-backed `admin_sessions`. Generate a hash interactively (the password is not placed in shell history) from the repository root:

```bash
.venv/bin/python -c 'from getpass import getpass; from argon2 import PasswordHasher; print(PasswordHasher().hash(getpass("Admin password: ")))'
```

Set `ADMIN_USERNAME`, the resulting `ADMIN_PASSWORD_HASH`, a cryptographically random `ADMIN_SESSION_SECRET` of at least 32 characters, and a suitable `ADMIN_SESSION_TTL_SECONDS` in the private `.env`. For example, generate the session secret with `python -c 'import secrets; print(secrets.token_urlsafe(48))'`. Set `ADMIN_COOKIE_SECURE=true` in production behind HTTPS. The raw session token exists only in the HttpOnly cookie; PostgreSQL stores an HMAC hash and revocation/expiry metadata. Run `alembic upgrade head` before starting the service.

Admin routes are under `/api/v1/admin`; login is `POST /auth/login`, logout is `POST /auth/logout`, and authenticated identity is `GET /auth/me`. Dashboard, paginated query logs/detail/export, users/user detail/user query history, session list/detail, and date-grouped stats are exposed below the same prefix. Protected routes use the `admin_session` cookie and do not accept the public chatbot API key.

The inspected project has no AWS JWT verifier configuration or issuer/audience/claim documentation. Therefore no AWS token details are guessed. If the application backend can issue a signed HS256 JWT, agree on a shared key, issuer, audience, and claims (`sub` as user ID; optional `email` and `name`), then configure `USER_IDENTITY_JWT_SECRET`, `USER_IDENTITY_JWT_ISSUER`, and `USER_IDENTITY_JWT_AUDIENCE` on the AI server and issue it in `X-Application-Identity` alongside the existing chatbot `Authorization: Bearer <CHAT_API_KEY>`. The AI server verifies signature, expiration, issuer, and audience before associating a newly created chat session. Missing identity continues to support old anonymous clients. Production refuses identity tokens if required identity settings are incomplete; it does not trust user IDs in request JSON. Coordinate secret rotation and token TTL with the application backend before enabling this integration.

Migration `0003_admin_observability` adds nullable identity and retrieval-audit fields plus `admin_sessions`; `0004_admin_search_indexes` adds PostgreSQL trigram indexes for large-dataset substring searches. These migrations preserve existing data and leave legacy identity null. `chat_messages.rag_used` and `retrieved_chunks` capture RAG evidence for new queries without storing embeddings. Older records naturally have unknown RAG state. Admin query lists omit assistant response bodies; query detail and session detail return conversation content to authenticated admins.
