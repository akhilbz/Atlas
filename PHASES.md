# Atlas — Build Phases

## Phase 1 — Foundation `Complete`

Infrastructure, data models, and authentication.

| Task | Status |
|---|---|
| Docker Compose (PostgreSQL 16 + pgvector, Redis) | Complete |
| SQLAlchemy models (User, Document, Chunk, Conversation, Message) | Complete |
| Alembic migrations (pgvector extension, HNSW index, GIN index) | Complete |
| Pydantic schemas and settings via pydantic-settings | Complete |
| JWT auth — signup, login, refresh, protected routes | Complete |
| Test infrastructure — isolated transactions, dependency overrides | Complete |

---

## Phase 2 — Document Ingestion `In progress`

Everything needed to take a document from upload to searchable chunks in the database.

| Piece | Scope | Status |
|---|---|---|
| 1 | File upload route — PDF, TXT, MD with auth and size validation | Complete |
| 2 | URL scraping utility — httpx + BeautifulSoup, tag stripping | Complete |
| 3 | Chunking utility — hybrid sentence/section-aware algorithm with tiktoken | Complete |
| 4 | Embedding service — OpenAI text-embedding-3-small, batched API calls | In progress |
| 5 | Celery worker — process_document task: extract → chunk → embed → store | Planned |
| 6 | Document library endpoints — GET list (paginated), GET detail, DELETE | Planned |

### Chunking algorithm (Piece 3)
Splits text in two stages: first on markdown headings (`#`, `##`, etc.) so chunks never cross section boundaries, then groups sentences up to 500 tokens with 1-sentence overlap. Each `TextChunk` carries a `section` field (the heading text) for use in citations downstream. Known limitation: regex sentence splitting misfires on abbreviations (`Dr.`, `1.`) but the fragments land in the same chunk at 500-token sizes so it doesn't affect retrieval quality.

---

## Phase 3 — RAG Pipeline `Planned`

Retrieval-augmented generation with streaming responses and source citations.

| Task | Status |
|---|---|
| Hybrid search — vector similarity (pgvector cosine) + full-text (tsvector) | Planned |
| Reciprocal rank fusion to merge search results | Planned |
| Prompt builder — chunks + conversation history + system instructions | Planned |
| SSE streaming endpoint (`GET /api/ask`) | Planned |
| Citation mapping — link response claims to source chunks | Planned |
| Message persistence with citations stored as JSONB | Planned |

---

## Phase 4 — GraphQL Layer `Planned`

Strawberry GraphQL schema for all non-streaming, non-upload operations.

| Task | Status |
|---|---|
| Types for Document, Chunk, Conversation, Message | Planned |
| Queries: documents, document, conversations, conversation, search | Planned |
| Mutations: createDocument, updateDocument, deleteDocument, createConversation | Planned |
| DataLoaders for N+1 prevention | Planned |
| Apollo Client integration with codegen | Planned |

---

## Phase 5 — Frontend `Planned`

Next.js 14 App Router UI with TypeScript, Tailwind CSS, and shadcn/ui.

| Task | Status |
|---|---|
| Auth pages — signup, login, token refresh | Planned |
| Document library — grid/list view, filter by tags, pagination | Planned |
| Upload flow — drag-and-drop, URL input, progress indicator | Planned |
| Chat interface — streaming responses, citation links, conversation history | Planned |
| Document detail view — full text, chunks, linked conversations | Planned |

---

## Phase 6 — LangGraph Agent `Planned`

Multi-tool agent with human-in-the-loop and streaming intermediate steps.

| Task | Status |
|---|---|
| Agent state graph (classify → plan → execute → synthesize → respond) | Planned |
| `search_knowledge_base` tool — hybrid search across user's docs | Planned |
| `web_search` tool — Tavily API when local knowledge is insufficient | Planned |
| `analyze_document` tool — summarize or extract key points | Planned |
| `save_note` tool — create document from findings (requires user approval) | Planned |
| Stream intermediate steps to frontend | Planned |

---

## Phase 7 — Polish `Planned`

Caching, rate limiting, observability, and CI/CD.

| Task | Status |
|---|---|
| Redis caching — embedding search results, document metadata | Planned |
| Rate limiting — 100 req/min per user, 20 LLM calls/min per user | Planned |
| Dashboard — document count, query history, knowledge base growth chart | Planned |
| GitHub Actions CI — lint, type check, test on every PR | Planned |
| Production deployment — Railway/Render with environment secrets | Planned |
