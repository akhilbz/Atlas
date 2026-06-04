# Atlas — AI Research Agent

## What is this project?
Atlas is a personal AI research agent. Users upload documents (PDFs, text, URLs), and an AI agent can search, analyze, and answer questions across everything they've saved — with citations back to source material. Think of it as a second brain with a reasoning engine.

## Tech stack
- **Backend:** Python 3.12, FastAPI, SQLAlchemy 2.0, Alembic, Pydantic v2
- **Database:** PostgreSQL 16 with pgvector extension, Redis for caching + Celery broker
- **GraphQL:** Strawberry (integrated with FastAPI)
- **Frontend:** Next.js 14 (App Router), TypeScript, Tailwind CSS, shadcn/ui, Apollo Client
- **AI:** OpenAI API (embeddings + chat), Anthropic API (Claude for generation), LangChain, LangGraph
- **Infrastructure:** Docker Compose (local), Railway/Render (production), GitHub Actions (CI)

## Project structure
```
atlas/
├── backend/
│   ├── app/
│   │   ├── main.py                  # FastAPI app entry point
│   │   ├── config.py                # Settings via pydantic-settings
│   │   ├── database.py              # SQLAlchemy engine, session factory
│   │   ├── models/                  # SQLAlchemy ORM models
│   │   │   ├── user.py
│   │   │   ├── document.py
│   │   │   ├── chunk.py
│   │   │   ├── conversation.py
│   │   │   └── message.py
│   │   ├── schemas/                 # Pydantic request/response schemas
│   │   │   ├── user.py
│   │   │   ├── document.py
│   │   │   ├── conversation.py
│   │   │   └── search.py
│   │   ├── routes/                  # FastAPI route handlers
│   │   │   ├── auth.py
│   │   │   ├── documents.py
│   │   │   ├── conversations.py
│   │   │   ├── search.py
│   │   │   └── ask.py
│   │   ├── services/                # Business logic layer
│   │   │   ├── auth.py
│   │   │   ├── documents.py
│   │   │   ├── embedding.py
│   │   │   ├── retrieval.py
│   │   │   ├── generation.py
│   │   │   └── agent.py
│   │   ├── graphql/                 # Strawberry GraphQL layer
│   │   │   ├── schema.py
│   │   │   ├── types.py
│   │   │   ├── queries.py
│   │   │   ├── mutations.py
│   │   │   └── dataloaders.py
│   │   ├── tasks/                   # Celery background tasks
│   │   │   └── embedding.py
│   │   └── utils/
│   │       ├── chunking.py
│   │       ├── pdf.py
│   │       └── scraping.py
│   ├── alembic/
│   ├── tests/
│   │   ├── conftest.py
│   │   ├── test_auth.py
│   │   ├── test_documents.py
│   │   ├── test_search.py
│   │   └── test_rag.py
│   ├── alembic.ini
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── app/                     # Next.js App Router pages
│   │   ├── components/              # React components
│   │   ├── lib/                     # Apollo client, utils
│   │   ├── graphql/                 # Queries, mutations, generated types
│   │   └── hooks/                   # Custom React hooks
│   ├── package.json
│   └── next.config.js
├── docker-compose.yml
├── PRD.md
├── ARCHITECTURE.md
└── README.md
```

## Coding standards

### Python
- Use type hints everywhere. Run mypy for type checking.
- Use Pydantic v2 (BaseModel, field_validator, model_dump).
- Use SQLAlchemy 2.0 style (Mapped, mapped_column, not the old Column style).
- Use async where appropriate (async def endpoints, but sync SQLAlchemy sessions are fine to start).
- Use structlog for logging. Log all API calls, database queries, and errors.
- Write pytest tests for all routes and services. Use httpx.AsyncClient for API tests.
- Use ruff for linting, black for formatting.
- Error handling: raise HTTPException with proper status codes. Never return bare 500s.

### TypeScript / Next.js
- Strict TypeScript. No `any` types.
- Use Next.js App Router (not Pages Router).
- Use server components by default, 'use client' only when needed.
- Use Apollo Client for GraphQL. Auto-generate types with graphql-codegen.
- Use Tailwind CSS + shadcn/ui for styling. No custom CSS files.
- Component files use PascalCase. Utility files use camelCase.

### General
- Every function has a docstring explaining what it does.
- Commits are atomic and descriptive: "Add JWT auth with refresh tokens" not "update code".
- No hardcoded values. All config via environment variables (pydantic-settings).
- Tests before deploying. CI must pass.

## Key design decisions
- **REST + GraphQL coexist:** REST for streaming (SSE) and file uploads. GraphQL for everything else.
- **RAG built from scratch first, then LangChain:** We implement the pipeline manually (chunking, embedding, retrieval, generation) before introducing LangChain. Both implementations remain in the codebase.
- **pgvector over a dedicated vector DB:** Keeps the stack simple. One database for everything. Switch to Pinecone/Weaviate only if pgvector becomes a bottleneck.
- **Celery for background jobs:** Document processing (chunking + embedding) runs async. Users get instant upload confirmation.
- **Cursor-based pagination everywhere:** No offset pagination. Cursor-based is more performant and consistent.

## Environment variables needed
```
DATABASE_URL=postgresql://atlas:atlas@localhost:5432/atlas
REDIS_URL=redis://localhost:6379/0
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
JWT_SECRET=<random-string>
JWT_ALGORITHM=HS256
JWT_EXPIRATION_MINUTES=30
ENVIRONMENT=development
```

## Commands
```bash
# Start local development
docker-compose up -d                    # PostgreSQL + Redis
cd backend && pip install -r requirements.txt
alembic upgrade head                    # Run migrations
uvicorn app.main:app --reload           # Start FastAPI

# Run tests
cd backend && pytest -v

# Frontend (after week 2)
cd frontend && npm install
npm run dev
```
