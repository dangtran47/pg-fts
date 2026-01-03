# Metadata Catalog Search Implementation Analysis

## Executive Summary

**Yes, this is completely feasible with PostgreSQL.** Your existing stack (FastAPI + PostgreSQL + SQLAlchemy) is well-suited for implementing this search functionality. PostgreSQL's built-in full-text search (FTS) capabilities are powerful enough for this use case, and you won't need external search engines unless you have very specific requirements.

---

## Architecture Overview

### Data Model

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│   owners    │    │   schemas   │    │   tables    │
├─────────────┤    ├─────────────┤    ├─────────────┤
│ id          │    │ id          │    │ id          │
│ name        │    │ name        │    │ name        │
│             │    │ description │    │ description │
└─────────────┘    │ owner_id ───┼────│ schema_id ──┼───►
                   └─────────────┘    │ owner_id ───┼───►
                                      └─────────────┘
                                             │
                                             ▼
                                      ┌─────────────┐
                                      │   columns   │
                                      ├─────────────┤
                                      │ id          │
                                      │ name        │
                                      │ description │
                                      │ table_id ───┼───►
                                      └─────────────┘
```

---

## Approach 1: Pure PostgreSQL Full-Text Search (Recommended)

### Why PostgreSQL FTS is Ideal for This Use Case

1. **No additional infrastructure** - uses your existing database
2. **ACID compliance** - search index stays consistent with data
3. **Powerful features** - ranking, highlighting, stemming, stop words
4. **UNION support** - combine results from multiple tables with pagination
5. **Excellent SQLAlchemy support** - well-documented integration

### Implementation Strategy

#### Step 1: Add Search Vectors to Each Table

```sql
-- Add tsvector columns for full-text search
ALTER TABLE schemas ADD COLUMN search_vector tsvector 
  GENERATED ALWAYS AS (
    setweight(to_tsvector('english', coalesce(name, '')), 'A') ||
    setweight(to_tsvector('english', coalesce(description, '')), 'B')
  ) STORED;

ALTER TABLE tables ADD COLUMN search_vector tsvector 
  GENERATED ALWAYS AS (
    setweight(to_tsvector('english', coalesce(name, '')), 'A') ||
    setweight(to_tsvector('english', coalesce(description, '')), 'B')
  ) STORED;

ALTER TABLE columns ADD COLUMN search_vector tsvector 
  GENERATED ALWAYS AS (
    setweight(to_tsvector('english', coalesce(name, '')), 'A') ||
    setweight(to_tsvector('english', coalesce(description, '')), 'B')
  ) STORED;

-- Create GIN indexes for fast searching
CREATE INDEX idx_schemas_search ON schemas USING GIN(search_vector);
CREATE INDEX idx_tables_search ON tables USING GIN(search_vector);
CREATE INDEX idx_columns_search ON columns USING GIN(search_vector);
```

#### Step 2: Create Unified Search View

```sql
CREATE VIEW unified_search AS
-- Schema results
SELECT 
  'schema' AS result_type,
  s.id AS entity_id,
  s.name,
  s.description,
  s.search_vector,
  -- Full context
  s.id AS schema_id,
  s.name AS schema_name,
  NULL::integer AS table_id,
  NULL::text AS table_name,
  NULL::integer AS column_id,
  NULL::text AS column_name,
  o.id AS owner_id,
  o.name AS owner_name
FROM schemas s
JOIN owners o ON s.owner_id = o.id

UNION ALL

-- Table results
SELECT 
  'table' AS result_type,
  t.id AS entity_id,
  t.name,
  t.description,
  t.search_vector,
  -- Full context
  s.id AS schema_id,
  s.name AS schema_name,
  t.id AS table_id,
  t.name AS table_name,
  NULL::integer AS column_id,
  NULL::text AS column_name,
  o.id AS owner_id,
  o.name AS owner_name
FROM tables t
JOIN schemas s ON t.schema_id = s.id
JOIN owners o ON t.owner_id = o.id

UNION ALL

-- Column results (returns both column AND parent table as separate results)
SELECT 
  'column' AS result_type,
  c.id AS entity_id,
  c.name,
  c.description,
  c.search_vector,
  -- Full context
  s.id AS schema_id,
  s.name AS schema_name,
  t.id AS table_id,
  t.name AS table_name,
  c.id AS column_id,
  c.name AS column_name,
  o.id AS owner_id,
  o.name AS owner_name
FROM columns c
JOIN tables t ON c.table_id = t.id
JOIN schemas s ON t.schema_id = s.id
JOIN owners o ON t.owner_id = o.id;
```

#### Step 3: Search Function with Highlighting & Pagination

```sql
CREATE OR REPLACE FUNCTION search_catalog(
  search_terms TEXT,
  filter_owner_id INTEGER DEFAULT NULL,
  filter_schema_id INTEGER DEFAULT NULL,
  page_number INTEGER DEFAULT 1,
  page_size INTEGER DEFAULT 20
)
RETURNS TABLE (
  result_type TEXT,
  entity_id INTEGER,
  name TEXT,
  description TEXT,
  name_highlight TEXT,
  description_highlight TEXT,
  rank REAL,
  schema_id INTEGER,
  schema_name TEXT,
  table_id INTEGER,
  table_name TEXT,
  column_id INTEGER,
  column_name TEXT,
  owner_id INTEGER,
  owner_name TEXT,
  total_count BIGINT
) AS $$
DECLARE
  query tsquery := websearch_to_tsquery('english', search_terms);
  offset_val INTEGER := (page_number - 1) * page_size;
BEGIN
  RETURN QUERY
  WITH search_results AS (
    SELECT 
      us.result_type,
      us.entity_id,
      us.name,
      us.description,
      ts_headline('english', us.name, query, 
        'StartSel=<mark>, StopSel=</mark>, MaxFragments=3') AS name_highlight,
      ts_headline('english', COALESCE(us.description, ''), query,
        'StartSel=<mark>, StopSel=</mark>, MaxFragments=3, MaxWords=50') AS description_highlight,
      ts_rank_cd(us.search_vector, query) AS rank,
      us.schema_id,
      us.schema_name,
      us.table_id,
      us.table_name,
      us.column_id,
      us.column_name,
      us.owner_id,
      us.owner_name
    FROM unified_search us
    WHERE us.search_vector @@ query
      AND (filter_owner_id IS NULL OR us.owner_id = filter_owner_id)
      AND (filter_schema_id IS NULL OR us.schema_id = filter_schema_id)
  ),
  counted AS (
    SELECT *, COUNT(*) OVER() AS total_count
    FROM search_results
  )
  SELECT 
    counted.result_type,
    counted.entity_id,
    counted.name,
    counted.description,
    counted.name_highlight,
    counted.description_highlight,
    counted.rank,
    counted.schema_id,
    counted.schema_name,
    counted.table_id,
    counted.table_name,
    counted.column_id,
    counted.column_name,
    counted.owner_id,
    counted.owner_name,
    counted.total_count
  FROM counted
  ORDER BY counted.rank DESC, counted.name ASC
  LIMIT page_size
  OFFSET offset_val;
END;
$$ LANGUAGE plpgsql;
```

#### Step 4: SQLAlchemy Models

```python
from sqlalchemy import Column, Integer, String, Text, ForeignKey, Index, func
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import relationship, declared_attr
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()

class Owner(Base):
    __tablename__ = 'owners'
    
    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)

class Schema(Base):
    __tablename__ = 'schemas'
    
    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    owner_id = Column(Integer, ForeignKey('owners.id'), nullable=False)
    search_vector = Column(TSVECTOR)
    
    owner = relationship('Owner')
    
    __table_args__ = (
        Index('idx_schemas_search', 'search_vector', postgresql_using='gin'),
    )

class Table(Base):
    __tablename__ = 'tables'
    
    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    schema_id = Column(Integer, ForeignKey('schemas.id'), nullable=False)
    owner_id = Column(Integer, ForeignKey('owners.id'), nullable=False)
    search_vector = Column(TSVECTOR)
    
    schema = relationship('Schema')
    owner = relationship('Owner')
    
    __table_args__ = (
        Index('idx_tables_search', 'search_vector', postgresql_using='gin'),
    )

class Column_(Base):
    __tablename__ = 'columns'
    
    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    table_id = Column(Integer, ForeignKey('tables.id'), nullable=False)
    search_vector = Column(TSVECTOR)
    
    table = relationship('Table')
    
    __table_args__ = (
        Index('idx_columns_search', 'search_vector', postgresql_using='gin'),
    )
```

#### Step 5: FastAPI Service

```python
from fastapi import FastAPI, Query, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text
from pydantic import BaseModel
from typing import List, Optional
from enum import Enum

app = FastAPI()

class ResultType(str, Enum):
    schema = "schema"
    table = "table"
    column = "column"

class SearchResult(BaseModel):
    result_type: ResultType
    entity_id: int
    name: str
    description: Optional[str]
    name_highlight: str
    description_highlight: str
    rank: float
    schema_id: Optional[int]
    schema_name: Optional[str]
    table_id: Optional[int]
    table_name: Optional[str]
    column_id: Optional[int]
    column_name: Optional[str]
    owner_id: int
    owner_name: str

class SearchResponse(BaseModel):
    results: List[SearchResult]
    total_count: int
    page: int
    page_size: int
    total_pages: int

@app.get("/search", response_model=SearchResponse)
async def search_catalog(
    q: str = Query(..., min_length=1, description="Search keywords"),
    owner_id: Optional[int] = Query(None, description="Filter by owner"),
    schema_id: Optional[int] = Query(None, description="Filter by schema"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Results per page"),
    db: Session = Depends(get_db)
):
    """
    Search across schemas, tables, and columns.
    
    - Returns matched entities with highlighted keywords
    - Supports filtering by owner and schema
    - Paginated results sorted by relevance
    """
    
    query = text("""
        SELECT * FROM search_catalog(
            :search_terms,
            :owner_id,
            :schema_id,
            :page,
            :page_size
        )
    """)
    
    result = db.execute(query, {
        "search_terms": q,
        "owner_id": owner_id,
        "schema_id": schema_id,
        "page": page,
        "page_size": page_size
    })
    
    rows = result.fetchall()
    
    if not rows:
        return SearchResponse(
            results=[],
            total_count=0,
            page=page,
            page_size=page_size,
            total_pages=0
        )
    
    total_count = rows[0].total_count
    total_pages = (total_count + page_size - 1) // page_size
    
    results = [
        SearchResult(
            result_type=row.result_type,
            entity_id=row.entity_id,
            name=row.name,
            description=row.description,
            name_highlight=row.name_highlight,
            description_highlight=row.description_highlight,
            rank=row.rank,
            schema_id=row.schema_id,
            schema_name=row.schema_name,
            table_id=row.table_id,
            table_name=row.table_name,
            column_id=row.column_id,
            column_name=row.column_name,
            owner_id=row.owner_id,
            owner_name=row.owner_name
        )
        for row in rows
    ]
    
    return SearchResponse(
        results=results,
        total_count=total_count,
        page=page,
        page_size=page_size,
        total_pages=total_pages
    )
```

#### Step 6: Handle Column Match → Return Table + Column

To return both the table and column when a column matches:

```python
@app.get("/search/expanded", response_model=SearchResponse)
async def search_catalog_expanded(
    q: str = Query(..., min_length=1),
    owner_id: Optional[int] = None,
    schema_id: Optional[int] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db)
):
    """
    Search with expanded results - when a column matches,
    return both the column AND its parent table as separate items.
    """
    
    query = text("""
        WITH base_search AS (
            SELECT * FROM search_catalog(
                :search_terms, :owner_id, :schema_id, 1, 10000
            )
        ),
        expanded AS (
            -- Original results
            SELECT * FROM base_search
            
            UNION
            
            -- Add parent tables for matched columns
            SELECT DISTINCT ON (t.id)
                'table'::text as result_type,
                t.id as entity_id,
                t.name,
                t.description,
                t.name as name_highlight,  -- No highlight for parent
                t.description as description_highlight,
                bs.rank * 0.8 as rank,  -- Slightly lower rank
                bs.schema_id,
                bs.schema_name,
                t.id as table_id,
                t.name as table_name,
                NULL::integer as column_id,
                NULL::text as column_name,
                bs.owner_id,
                bs.owner_name,
                0::bigint as total_count
            FROM base_search bs
            JOIN tables t ON bs.table_id = t.id
            WHERE bs.result_type = 'column'
              AND NOT EXISTS (
                  SELECT 1 FROM base_search 
                  WHERE result_type = 'table' AND entity_id = t.id
              )
        ),
        final AS (
            SELECT *, ROW_NUMBER() OVER (ORDER BY rank DESC, name) as rn,
                   COUNT(*) OVER() as total
            FROM expanded
        )
        SELECT 
            result_type, entity_id, name, description,
            name_highlight, description_highlight, rank,
            schema_id, schema_name, table_id, table_name,
            column_id, column_name, owner_id, owner_name, total as total_count
        FROM final
        WHERE rn > :offset AND rn <= :offset + :limit
        ORDER BY rank DESC, name
    """)
    
    offset = (page - 1) * page_size
    
    result = db.execute(query, {
        "search_terms": q,
        "owner_id": owner_id,
        "schema_id": schema_id,
        "offset": offset,
        "limit": page_size
    })
    
    # ... rest of the response handling
```

---

## Approach 2: Materialized View (Better Performance)

For better performance on large datasets, use a materialized view:

```sql
CREATE MATERIALIZED VIEW search_index AS
SELECT ... -- same as unified_search above
WITH DATA;

CREATE INDEX idx_search_index_vector ON search_index USING GIN(search_vector);
CREATE INDEX idx_search_index_owner ON search_index(owner_id);
CREATE INDEX idx_search_index_schema ON search_index(schema_id);

-- Refresh strategy (run periodically or on data changes)
REFRESH MATERIALIZED VIEW CONCURRENTLY search_index;
```

---

## Alternative Approaches

### Option A: Meilisearch (Simple Self-Hosted)

**Best for:** Fast iteration, simple setup, excellent developer experience

```python
# pip install meilisearch

import meilisearch

client = meilisearch.Client('http://localhost:7700', 'masterKey')

# Index your data
index = client.index('catalog')
index.add_documents([
    {
        'id': 'table_1',
        'type': 'table',
        'name': 'users',
        'description': 'User accounts',
        'schema_name': 'public',
        'owner_name': 'admin'
    },
    # ... more documents
])

# Configure searchable attributes and filtering
index.update_settings({
    'searchableAttributes': ['name', 'description'],
    'filterableAttributes': ['owner_name', 'schema_name', 'type']
})

# Search
results = index.search(
    'user',
    {
        'filter': 'owner_name = "admin"',
        'limit': 20,
        'offset': 0,
        'attributesToHighlight': ['name', 'description']
    }
)
```

**Pros:**
- Sub-50ms search responses
- Built-in typo tolerance
- Excellent highlighting
- Simple REST API
- Easy FastAPI integration

**Cons:**
- Additional service to manage
- Data sync complexity
- MIT license (check enterprise features)

### Option B: Azure AI Search (Azure Ecosystem)

**Best for:** If you're already deep in Azure and need enterprise features

**Note:** Azure AI Search does NOT natively support PostgreSQL as a data source. You would need:
1. Azure Data Factory pipeline to sync PostgreSQL → Azure Blob Storage
2. Create indexer from Blob Storage → Azure AI Search

**Pros:**
- Managed service
- Advanced AI features (semantic search, vector search)
- Enterprise SLA

**Cons:**
- Complex setup with PostgreSQL
- Higher cost
- Vendor lock-in
- Overkill for simple metadata search

### Option C: Elasticsearch (Enterprise Scale)

**Best for:** Very large datasets (millions of records), complex queries

**Pros:**
- Battle-tested at scale
- Rich query DSL
- Excellent analytics

**Cons:**
- Heavy infrastructure
- Complex cluster management
- Higher operational cost

---

## Recommendation Matrix

| Criteria | PostgreSQL FTS | Meilisearch | Azure AI Search | Elasticsearch |
|----------|---------------|-------------|-----------------|---------------|
| **Setup Complexity** | ⭐⭐⭐⭐⭐ Low | ⭐⭐⭐⭐ Low | ⭐⭐ High | ⭐⭐ High |
| **Data Sync** | ⭐⭐⭐⭐⭐ None | ⭐⭐⭐ Moderate | ⭐ Complex | ⭐⭐ Moderate |
| **Performance** | ⭐⭐⭐⭐ Good | ⭐⭐⭐⭐⭐ Excellent | ⭐⭐⭐⭐ Good | ⭐⭐⭐⭐⭐ Excellent |
| **Highlighting** | ⭐⭐⭐⭐ Good | ⭐⭐⭐⭐⭐ Excellent | ⭐⭐⭐⭐ Good | ⭐⭐⭐⭐⭐ Excellent |
| **Cost** | ⭐⭐⭐⭐⭐ Free | ⭐⭐⭐⭐ Low | ⭐⭐ High | ⭐⭐⭐ Medium |
| **Typo Tolerance** | ⭐⭐⭐ With pg_trgm | ⭐⭐⭐⭐⭐ Built-in | ⭐⭐⭐⭐⭐ Built-in | ⭐⭐⭐⭐ Good |
| **Your Stack Fit** | ⭐⭐⭐⭐⭐ Perfect | ⭐⭐⭐⭐ Good | ⭐⭐⭐ OK | ⭐⭐⭐ OK |

---

## Final Recommendation

**Start with PostgreSQL Full-Text Search.** Here's why:

1. **Zero infrastructure overhead** - No new services to deploy
2. **Consistent data** - No sync lag between source and search index
3. **Your current stack** - Works perfectly with FastAPI + SQLAlchemy
4. **Feature complete** - Handles all your requirements:
   - ✅ Multiple keyword search
   - ✅ Highlighting with `ts_headline`
   - ✅ Ranking with `ts_rank_cd`
   - ✅ UNION across tables with pagination
   - ✅ Filter by owner/schema
   - ✅ Full context in results

**If you outgrow PostgreSQL FTS** (>1M records, need sub-10ms response, typo tolerance):
- **Self-hosted preference** → Meilisearch
- **Azure preference** → Stay with PostgreSQL or explore Elasticsearch on Azure

### Quick Start Checklist

1. [ ] Add `search_vector` columns to schemas, tables, columns
2. [ ] Create GIN indexes
3. [ ] Create `unified_search` view
4. [ ] Create `search_catalog` function
5. [ ] Implement FastAPI endpoint
6. [ ] Test with sample data
7. [ ] Add `pg_trgm` extension for fuzzy matching (optional)

---

## Appendix: Adding Fuzzy Search (Optional)

```sql
-- Enable trigram extension for fuzzy matching
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Add trigram indexes
CREATE INDEX idx_schemas_name_trgm ON schemas USING GIN (name gin_trgm_ops);
CREATE INDEX idx_tables_name_trgm ON tables USING GIN (name gin_trgm_ops);
CREATE INDEX idx_columns_name_trgm ON columns USING GIN (name gin_trgm_ops);

-- Combined FTS + fuzzy search
SELECT name, 
       similarity(name, 'usrs') as fuzzy_score,
       ts_rank(search_vector, query) as fts_score
FROM unified_search, websearch_to_tsquery('english', 'users') query
WHERE search_vector @@ query 
   OR name % 'usrs'  -- trigram similarity
ORDER BY GREATEST(fuzzy_score, fts_score) DESC;
```
