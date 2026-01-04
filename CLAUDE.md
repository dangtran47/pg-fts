# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a PostgreSQL Full-Text Search learning project that implements a metadata catalog search system. The project demonstrates advanced PostgreSQL FTS capabilities with a FastAPI backend for searching across database schemas, tables, and columns.

## Key Architecture

### Database Design
- **4-level hierarchy**: Owners → Schemas → Tables → Columns
- **Full-Text Search**: Each entity (schemas, tables, columns) has a `search_vector` TSVECTOR column with GIN indexes
- **Auto-updating**: Database triggers automatically maintain search vectors when data changes
- **Advanced ranking**: Custom relevance scoring with exact matches, partial matches, and context-aware ranking

### API Structure
- **Primary endpoint**: `/search` - unified search across all entity types with sophisticated ranking
- **Filter endpoints**: `/owners` and `/schemas` for building search filters
- **Response includes**: Full context (parent schema/table info), highlighted matches, matched columns for table results

### Data Models (SQLAlchemy)
- `Owner`: Has name, email, and relationships to tables
- `Schema`: Contains tables, has search_vector for FTS
- `Table`: Belongs to schema and owner, has search_vector
- `Column`: Belongs to table, has search_vector

## Development Commands

### Essential Setup
```bash
make setup                    # Full project setup (venv, deps, db, migrate, seed)
make install                  # Install dependencies with uv
```

### Database Management
```bash
make db-up                    # Start PostgreSQL container
make db-down                  # Stop database
make db-reset                 # Complete reset (down, up, migrate, seed)
make db-connect              # Connect to database via psql
```

### Migrations
```bash
make migrate                  # Run migrations to latest
make migrate-status           # Show current migration version
make migrate-history          # Show migration history
make migrate-downgrade        # Downgrade one migration
```

### Data Management
```bash
make seed                     # Generate test data (5 owners, 10 schemas, 100 tables, 1000 columns)
python seed_data.py           # Direct seeding script
```

### API Server
```bash
make api-dev                  # Start API with auto-reload
make api                      # Start production API server
```

### Cleanup
```bash
make clean                    # Remove venv and Docker volumes
```

## Database Configuration

- **Connection**: `postgresql://postgres:postgres@localhost:5432/fts_learn`
- **Container**: `pg_fts_db` (PostgreSQL 15 Alpine)
- **Port**: 5432
- **Environment variables**: Supports `DATABASE_URL` override via `.env`

## Testing the Search API

The API runs on `http://localhost:8000` with:
- **Docs**: `/docs` (Swagger UI)
- **Health check**: `/health`
- **Examples**: `/search/examples` (shows search syntax examples)

### Search Features
- Simple keywords: `user account`
- Phrases: `"user account"`
- Boolean operators: `user AND account`, `user OR customer`, `user -admin`
- Complex queries: `(user OR customer) AND email`
- Filters: `owner_id`, `schema_id`
- Parent table inclusion: When columns match, parent tables are optionally included

## Migration System

Uses Alembic with timestamped filenames. Key migrations:
1. Base schema creation (owners, schemas, tables, columns)
2. Search vector columns and GIN indexes
3. Database search function creation
4. Search function fixes and improvements

The search functionality is implemented at the database level with a custom PostgreSQL function for optimal performance.

## Dependencies

Core stack:
- **FastAPI**: REST API framework
- **SQLAlchemy 2.x**: ORM and database toolkit
- **Alembic**: Database migrations
- **PostgreSQL**: Database with FTS extensions
- **Docker**: Database containerization
- **uv**: Python package management

Development dependencies managed in `pyproject.toml`.