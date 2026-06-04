# Atlas — Product Requirements Document

## Vision
Atlas is a personal AI research agent that turns scattered information into searchable, queryable knowledge. Users upload documents, paste URLs, and save notes. An AI agent searches across everything, reasons about what it finds, and delivers cited answers in real-time.

## Problem
Knowledge workers spend hours searching through documents, re-reading articles, and trying to remember where they saw a specific piece of information. Existing tools (Notion, Google Drive, bookmarks) store information but don't understand it. You can search by keyword, but you can't ask "what were the key arguments against this approach across all the papers I've read?"

## Solution
Atlas ingests your documents, understands them semantically, and gives you an AI agent that can:
- Answer questions using your personal knowledge base with citations
- Search the web when your documents don't have the answer
- Analyze and summarize specific documents on demand
- Save new findings back to your knowledge base
- Auto-tag and organize incoming documents

## Target user
Engineers, researchers, students, and knowledge workers who consume large amounts of information and need to retrieve and synthesize it quickly. The first user is the builder (you) — you'll use Atlas to research startups, organize technical knowledge, and prepare for work.

## Core features

### 1. Document ingestion
- Upload PDFs and text files via drag-and-drop
- Paste a URL to scrape and ingest article content
- Manual note creation with markdown support
- Auto-extraction of text from PDFs (PyMuPDF)
- Background processing: upload is instant, chunking + embedding happens async
- Progress indicator showing processing status

### 2. Knowledge base (Library)
- Browse all documents in grid or list view
- Filter by tags, search by title
- Auto-generated tags and summaries via LLM
- Document detail view: full text, metadata, chunks, linked conversations
- Cursor-based pagination for large libraries

### 3. AI chat with citations
- Ask questions in natural language
- AI retrieves relevant chunks from your knowledge base
- Responses stream in real-time (token by token)
- Every claim is cited with a link to the source document and chunk
- Conversation history is persisted
- Multiple conversation threads

### 4. AI agent (LangGraph)
- Multi-tool agent that can:
  - search_knowledge_base: semantic + keyword hybrid search across your docs
  - web_search: search the internet when local knowledge is insufficient
  - analyze_document: summarize or extract key points from a specific document
  - save_note: create a new document from the agent's findings (with user approval)
- Shows intermediate reasoning steps in the UI ("Searching knowledge base...", "Found 3 relevant documents...", "Searching web for additional context...")
- Human-in-the-loop: asks for confirmation before taking actions (saving notes)
- Suggested follow-up questions after each response

### 5. Dashboard
- Total documents, conversations, and queries
- Most queried topics (chart)
- Recent activity feed
- Knowledge base growth over time

## Non-functional requirements
- **Performance:** Search results in <500ms. Streaming response starts within 1s.
- **Security:** All endpoints require authentication. File uploads validated by type and size. No SQL injection. Proper CORS configuration.
- **Reliability:** Background jobs retry on failure (3 attempts with exponential backoff). Graceful degradation when LLM APIs are unavailable.
- **Observability:** Structured logging, error tracking, request correlation IDs.
- **Cost control:** Cache embedding search results. Rate limit LLM API calls per user.

## What Atlas is NOT
- Not a multi-user collaboration tool (single user per account, no sharing)
- Not a replacement for Google Docs (no document editing)
- Not a general-purpose chatbot (grounded in your documents, not general knowledge)
- Not a production SaaS (no billing, no admin panel, no multi-tenancy)

## Success metrics (for the builder)
- Can upload a 50-page PDF and ask questions about it within 2 minutes
- Citations are accurate — every claim traces back to a real chunk in a real document
- Agent correctly decides when to search locally vs search the web
- The app feels fast: uploads are instant, streaming is smooth, search is snappy
- Codebase is clean enough that any engineer could read and understand it
