# Atlas

A personal AI research agent that turns scattered documents into a searchable, queryable knowledge base. Upload PDFs, paste URLs, write notes — then ask questions across everything you've saved. Answers stream in real-time with citations back to the exact source.

## What it does

- **Ingest** PDFs, URLs, and markdown notes with instant upload confirmation (processing happens in the background)
- **Search** your knowledge base semantically — ask questions in natural language, not just keywords
- **Chat** with an AI that cites every claim back to a specific chunk in a specific document
- **Agent mode** — a LangGraph-powered agent that plans, searches locally and on the web, analyzes documents, and saves findings back to your library
- **Library** — browse, filter, and tag all your documents; auto-generated summaries and tags via LLM

## Tech stack

| Layer | Technology |
|---|---|
| Frontend | Next.js 14 (App Router), TypeScript, Tailwind CSS, shadcn/ui, Apollo Client |
| Backend | Python 3.12, FastAPI, SQLAlchemy 2.0, Alembic, Pydantic v2 |
| Database | PostgreSQL 16 + pgvector, Redis |
| GraphQL | Strawberry (integrated with FastAPI) |
| AI | OpenAI (embeddings), Anthropic Claude (generation), LangChain, LangGraph |
| Background jobs | Celery |
| Infrastructure | Docker Compose (local), Railway/Render (production), GitHub Actions (CI) |

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Next.js Frontend                      │
│   (TypeScript, Tailwind, shadcn/ui, Apollo Client)       │
└────────────────┬──────────────────┬──────────────────────┘
                 │ GraphQL          │ SSE (streaming)
┌────────────────▼──────────────────▼──────────────────────┐
│                    FastAPI Backend                        │
│                                                           │
│   GraphQL (Strawberry) │ REST (auth, upload) │ SSE        │
│                                                           │
│              Services: auth | documents |                 │
│              embedding | retrieval | generation | agent   │
│                                                           │
│         LangGraph Agent          Celery Workers           │
└────────────────┬──────────────────────────────────────────┘
                 │
    ┌────────────▼───────────┐    ┌─────────────┐
    │  PostgreSQL + pgvector  │    │    Redis    │
    │  users, documents,      │    │  cache +    │
    │  chunks, conversations  │    │  broker     │
    └─────────────────────────┘    └─────────────┘
```

REST handles auth, file uploads, and SSE streaming. GraphQL handles everything else.

## Getting started

### Prerequisites

- Docker + Docker Compose
- Python 3.12
- Node.js 18+
- pnpm

### 1. Clone and configure

```bash
git clone <repo-url>
cd atlas
cp .env.example .env
# Fill in your API keys in .env
```

### 2. Start infrastructure

```bash
docker-compose up -d
```

This starts PostgreSQL 16 (with pgvector) and Redis.

### 3. Backend

```bash
cd backend
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

alembic upgrade head             # Run database migrations
uvicorn app.main:app --reload    # Start API server on :8000
```

API docs available at `http://localhost:8000/docs`.

### 4. Frontend

```bash
cd frontend
pnpm install
pnpm dev                         # Starts on :3000
```

### 5. Celery worker (for document processing)

```bash
cd backend
celery -A app.tasks worker --loglevel=info
```

## Environment variables

```
DATABASE_URL=postgresql://atlas:atlas@localhost:5435/atlas
REDIS_URL=redis://localhost:6379/0
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
JWT_SECRET=<random-string>
JWT_ALGORITHM=HS256
JWT_EXPIRATION_MINUTES=30
ENVIRONMENT=development
```

## Running tests

```bash
cd backend
python -m pytest -v
```

> Use `python -m pytest` rather than `pytest` directly to ensure the correct Python interpreter and installed packages are used.

## Project structure

```
atlas/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI app entry point
│   │   ├── config.py            # Settings via pydantic-settings
│   │   ├── database.py          # SQLAlchemy engine + session
│   │   ├── models/              # SQLAlchemy ORM models
│   │   ├── schemas/             # Pydantic request/response schemas
│   │   ├── routes/              # FastAPI route handlers
│   │   ├── services/            # Business logic
│   │   ├── graphql/             # Strawberry GraphQL schema
│   │   ├── tasks/               # Celery background tasks
│   │   └── utils/               # Chunking, PDF extraction, scraping
│   ├── alembic/                 # Database migrations
│   ├── tests/
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── app/                 # Next.js App Router pages
│   │   ├── components/          # React components
│   │   ├── lib/                 # Apollo client, utils
│   │   ├── graphql/             # Queries, mutations, generated types
│   │   └── hooks/               # Custom React hooks
│   └── package.json
├── docker-compose.yml
├── PRD.md
├── ARCHITECTURE.md
└── README.md
```

## Build phases

| Phase | Scope | Status |
|---|---|---|
| 1 | Foundation: infra, models, JWT auth | Complete |
| 2 | Document ingestion: upload, extract, chunk, embed, Celery | In progress |
| 3 | RAG pipeline: hybrid search, SSE streaming, citations | Planned |
| 4 | GraphQL layer | Planned |
| 5 | Frontend: auth UI, library, chat | Planned |
| 6 | LangGraph agent: multi-tool, human-in-the-loop | Planned |
| 7 | Polish: caching, rate limiting, dashboard, CI/CD | Planned |

### Phase 2 — Document ingestion breakdown

| Piece | Scope | Status |
|---|---|---|
| 1 | File upload route (PDF, TXT, MD) with auth and size validation | Complete |
| 2 | URL scraping utility (httpx + BeautifulSoup) | Complete |
| 3 | Chunking utility — hybrid sentence/section-aware algorithm with tiktoken | Complete |
| 4 | Embedding service — OpenAI text-embedding-3-small, batched | In progress |
| 5 | Celery worker — process_document task: extract → chunk → embed → store | Planned |
| 6 | Document library endpoints — GET list, GET detail, DELETE | Planned |

## Key design decisions

- **REST + GraphQL coexist** — REST for streaming and file uploads; GraphQL for all other data operations
- **pgvector over a dedicated vector DB** — keeps the stack to one database; migrate to Pinecone/Weaviate only if it becomes a bottleneck
- **Manual RAG before LangChain** — the pipeline is implemented by hand first, then abstracted; both implementations remain in the codebase
- **Celery for background jobs** — document processing (chunking + embedding) is async so uploads feel instant
- **Cursor-based pagination everywhere** — no offset pagination

## API overview

### REST
- `POST /api/auth/signup`
- `POST /api/auth/login`
- `POST /api/auth/refresh`
- `POST /api/documents/upload`
- `GET /api/ask` (SSE streaming)
- `GET /api/health`

### GraphQL
- Queries: `documents`, `document`, `conversations`, `conversation`, `search`
- Mutations: `createDocument`, `updateDocument`, `deleteDocument`, `createConversation`, `deleteConversation`
