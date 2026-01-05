# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Bio-RAG is an AI-powered biomedical research platform that provides RAG-based Q&A, semantic paper search, and research trend analysis for PubMed papers. The platform supports Korean language queries with automatic translation.

## Repository Structure

```
bio-rag/
├── backend/          # Python FastAPI backend
│   ├── src/
│   │   ├── api/v1/   # REST endpoints (auth, search, chat, library, trends, vectordb)
│   │   ├── core/     # Config, database, security
│   │   ├── models/   # SQLAlchemy ORM models
│   │   ├── services/ # Business logic (pubmed, embedding, search, rag)
│   │   ├── data/     # JSON-based persistent storage
│   │   └── tasks/    # Celery async tasks
│   └── tests/
├── frontend/         # React + TypeScript frontend
│   └── src/
│       ├── pages/    # Route pages (8 pages)
│       ├── components/
│       ├── services/ # API client (api.ts)
│       ├── store/    # Zustand state management
│       └── types/    # TypeScript interfaces
└── docker-compose.yml
```

## Common Commands

All commands should be run from the `bio-rag/` directory.

### Development

```bash
# Start both servers (requires parallel make)
make dev

# Backend only (port 8000)
cd backend && source venv/bin/activate && uvicorn src.main:app --reload --port 8000

# Frontend only (port 3000)
cd frontend && npm run dev
```

### Testing

```bash
# Backend tests with coverage
cd backend && source venv/bin/activate && pytest tests/ -v --cov=src

# Frontend tests
cd frontend && npm run test

# Run single backend test
cd backend && source venv/bin/activate && pytest tests/test_search.py -v
```

### Linting & Formatting

```bash
# Backend (ruff)
cd backend && source venv/bin/activate && ruff check src/
cd backend && source venv/bin/activate && ruff format src/

# Frontend (eslint)
cd frontend && npm run lint

# TypeScript type check
cd frontend && npx tsc --noEmit
```

### Docker

```bash
docker-compose up -d --build   # Start all services
docker-compose logs -f         # View logs
docker-compose down            # Stop services
```

### Database Migrations

```bash
cd backend && source venv/bin/activate
alembic revision --autogenerate -m "description"  # Create migration
alembic upgrade head                               # Apply migrations
```

## Architecture

### Hybrid Search System

The platform uses a weighted hybrid search combining:
- **Dense Search (70%)**: OpenAI embeddings (1536 dimensions) via Qdrant
- **Sparse Search (30%)**: SPLADE BM25 for keyword matching

### RAG Pipeline

```
User Query → Korean Detection/Translation → Vector Search → Context Building → GPT-4 Generation → Source Attribution
```

### Key Services

- **vectordb.py** (44KB): Main hybrid search implementation - largest API module
- **ai_chat.py**: OpenAI/GPT-4 integration for RAG responses
- **pubmed.py**: PubMed API client with rate limiting (10 req/sec)
- **embedding/generator.py**: OpenAI embedding generation
- **api.ts** (frontend): Axios client with auth interceptors

### State Management

- **Backend**: JSON file storage for users/library data (`backend/src/data/`)
- **Frontend**: Zustand stores for auth, chat, and search state
- **Caching**: React Query with 10min staleTime

## Technical Constraints

- **Python**: 3.11+ required (async/await features)
- **Node**: 20+ recommended
- **Database**: PostgreSQL with asyncpg (async driver)
- **Vector DB**: Qdrant (local or Docker on port 6333)
- **AI Models**: OpenAI GPT-4 for generation, text-embedding-3-small for embeddings
- **Chunking**: 500 tokens with 100 token overlap

## Environment Variables

Required in `backend/.env`:
```
OPENAI_API_KEY=<required>
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/bio_rag
QDRANT_HOST=localhost
QDRANT_PORT=6333
JWT_SECRET_KEY=<generate-secure-key>
```

Optional:
```
PUBMED_API_KEY=<for-higher-rate-limits>
COHERE_API_KEY=<optional>
```

## Code Patterns

### Backend
- Use Pydantic models for all request/response validation
- All database operations use async/await with SQLAlchemy
- External API calls must include retry logic with tenacity
- Errors should be logged via structlog

### Frontend
- TypeScript strict mode is enabled
- Use path alias `@/` for imports from `src/`
- Components use TailwindCSS for styling (dark mode theme)
- API calls go through `services/api.ts`

## CI/CD

GitHub Actions runs on PR:
- Backend: `ruff check src/` + `pytest tests/`
- Frontend: `npm run lint` + `tsc --noEmit` + `npm run build`
- Docker build verification
