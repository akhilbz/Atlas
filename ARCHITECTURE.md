# Atlas — Technical Architecture

## System overview

```
┌─────────────────────────────────────────────────────────┐
│                    Next.js Frontend                      │
│   (TypeScript, Tailwind, shadcn/ui, Apollo Client)       │
└────────────────┬──────────────────┬──────────────────────┘
                 │ GraphQL          │ SSE (streaming)
                 │                  │
┌────────────────▼──────────────────▼──────────────────────┐
│                    FastAPI Backend                        │
│                                                          │
│  ┌─────────────┐ ┌──────────────┐ ┌───────────────────┐  │
│  │   GraphQL    │ │  REST API    │ │  WebSocket/SSE    │  │
│  │ (Strawberry) │ │ (auth, file  │ │  (streaming       │  │
│  │             │ │  upload)     │ │   responses)      │  │
│  └──────┬──────┘ └──────┬───────┘ └────────┬──────────┘  │
│         │               │                  │              │
│  ┌──────▼───────────────▼──────────────────▼──────────┐  │
│  │              Services Layer                        │  │
│  │  auth | documents | embedding | retrieval |        │  │
│  │  generation | agent                                │  │
│  └──────┬─────────────────────────────┬───────────────┘  │
│         │                             │                   │
│  ┌──────▼──────┐              ┌───────▼───────────────┐  │
│  │  LangGraph  │              │   Celery Workers      │  │
│  │  Agent      │              │   (background jobs)   │  │
│  │  ┌────────┐ │              └───────┬───────────────┘  │
│  │  │ Tools: │ │                      │                   │
│  │  │ search │ │                      │                   │
│  │  │ web    │ │                      │                   │
│  │  │ analyze│ │                      │                   │
│  │  │ save   │ │                      │                   │
│  │  └────────┘ │                      │                   │
│  └─────────────┘                      │                   │
└────────────────┬──────────────────────┼───────────────────┘
                 │                      │
    ┌────────────▼──────────┐    ┌──────▼──────┐
    │   PostgreSQL + pgvector│    │    Redis    │
    │                        │    │  (cache +   │
    │  users                 │    │   broker)   │
    │  documents             │    └─────────────┘
    │  chunks (+ embeddings) │
    │  conversations         │
    │  messages              │
    └────────────────────────┘
```

## Database schema

### users
| Column | Type | Notes |
|--------|------|-------|
| id | UUID | Primary key, generated |
| email | VARCHAR(255) | Unique, indexed |
| hashed_password | VARCHAR(255) | bcrypt |
| created_at | TIMESTAMP | Default now() |
| updated_at | TIMESTAMP | Auto-update |

### documents
| Column | Type | Notes |
|--------|------|-------|
| id | UUID | Primary key |
| user_id | UUID | FK → users, indexed |
| title | VARCHAR(500) | |
| content | TEXT | Full extracted text |
| source_url | VARCHAR(2000) | Nullable, for URL ingestion |
| source_type | ENUM | 'upload', 'url', 'note' |
| file_path | VARCHAR(500) | Nullable, path to raw file |
| tags | JSONB | Auto-generated + user tags |
| summary | TEXT | LLM-generated summary |
| status | ENUM | 'processing', 'ready', 'failed' |
| created_at | TIMESTAMP | |
| updated_at | TIMESTAMP | |

### chunks
| Column | Type | Notes |
|--------|------|-------|
| id | UUID | Primary key |
| document_id | UUID | FK → documents, indexed |
| content | TEXT | Chunk text (~500 tokens) |
| embedding | VECTOR(1536) | OpenAI text-embedding-3-small |
| chunk_index | INTEGER | Position in document |
| token_count | INTEGER | For context window budgeting |
| created_at | TIMESTAMP | |

**Indexes on chunks:**
- HNSW index on embedding column for fast similarity search
- GIN index on document's content column for full-text search (tsvector)

### conversations
| Column | Type | Notes |
|--------|------|-------|
| id | UUID | Primary key |
| user_id | UUID | FK → users, indexed |
| title | VARCHAR(500) | Auto-generated from first message |
| created_at | TIMESTAMP | |
| updated_at | TIMESTAMP | |

### messages
| Column | Type | Notes |
|--------|------|-------|
| id | UUID | Primary key |
| conversation_id | UUID | FK → conversations, indexed |
| role | ENUM | 'user', 'assistant' |
| content | TEXT | Message text |
| citations | JSONB | [{chunk_id, document_id, text}] |
| tool_calls | JSONB | Agent tool usage log |
| created_at | TIMESTAMP | |

## Data flows

### Document ingestion flow
```
User uploads PDF
  → POST /api/documents (multipart form)
  → Validate file type and size
  → Extract text (PyMuPDF for PDF)
  → Save Document record (status: 'processing')
  → Return 201 immediately
  → Queue Celery task: process_document(doc_id)
    → Chunk text (recursive splitter, ~500 tokens, 50 overlap)
    → Generate embeddings (OpenAI text-embedding-3-small, batch)
    → Store Chunk records with vectors
    → Auto-generate tags and summary (LLM call)
    → Update Document status → 'ready'
    → Invalidate relevant caches
```

### RAG query flow
```
User asks a question
  → POST /api/ask (SSE endpoint)
  → Embed the query (OpenAI)
  → Hybrid search:
    → Vector similarity search (pgvector, cosine, top 10)
    → Full-text search (PostgreSQL tsvector, top 10)
    → Reciprocal rank fusion to merge results
    → Return top 5 chunks
  → Build prompt:
    → System prompt with instructions
    → Retrieved chunks with source metadata
    → Recent conversation history (last 5 messages)
    → User's question
  → Stream response (Claude/GPT via SSE)
  → Map citations: match response claims to source chunks
  → Save Message record with citations
  → Return streamed response + citations
```

### Agent flow (LangGraph)
```
User asks a complex question
  → Route to LangGraph agent
  → Agent state graph:
    → CLASSIFY: Is this a simple lookup or research task?
    → PLAN: Which tools are needed? (stream plan to user)
    → EXECUTE: Run tools in sequence
      → search_knowledge_base: hybrid search
      → web_search: Tavily API (if local results insufficient)
      → analyze_document: summarize a specific doc
      → save_note: create new doc (requires user approval)
    → SYNTHESIZE: Combine tool results into final answer
    → RESPOND: Stream final answer with citations
  → All intermediate steps streamed to frontend
  → User can interrupt and redirect at any point
```

## API design

### REST endpoints (auth + streaming + files)
- POST /api/auth/signup
- POST /api/auth/login
- POST /api/auth/refresh
- POST /api/documents/upload (multipart)
- GET /api/ask (SSE streaming)
- GET /api/health

### GraphQL (everything else)
- Query: documents, document, conversations, conversation, search
- Mutation: createDocument, updateDocument, deleteDocument, createConversation, deleteConversation
- Subscription: documentStatus, messageStream (optional)

## Caching strategy
- **Embedding search results:** Cache by (query_hash, user_id) with 5-minute TTL. Same question = same results for a short window.
- **Document metadata:** Cache frequently accessed documents in Redis. Invalidate on update/delete.
- **User sessions:** Store JWT refresh tokens in Redis for fast validation.
- **LLM responses:** Do NOT cache. Every response should reflect the current state of the knowledge base.

## Security
- JWT authentication on all endpoints (httpOnly cookies for frontend, Bearer token for API)
- Password hashing with bcrypt (12 rounds)
- File upload validation: allowed types (PDF, TXT, MD), max size (20MB)
- Rate limiting: 100 requests/minute per user, 20 LLM calls/minute per user
- Input sanitization on all text inputs
- CORS: allow only the frontend origin in production
- SQL injection prevention: parameterized queries only (SQLAlchemy handles this)

## Cost management
- Embedding model: text-embedding-3-small ($0.02/1M tokens) — cheapest option
- Chat model: Claude Sonnet or GPT-4o-mini for most queries, GPT-4o/Claude Opus for complex agent tasks
- Batch embeddings: send chunks in batches of 100 to reduce API calls
- Cache search results to avoid redundant embedding calls
- Rate limit LLM calls per user to prevent cost spikes
