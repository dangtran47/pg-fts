"""
Metadata Catalog Search API using FastAPI and PostgreSQL Full-Text Search
"""

from fastapi import FastAPI, Query, Depends, HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from pydantic import BaseModel
from typing import List, Optional
from enum import Enum
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# ============================================================================
# DATABASE SETUP
# ============================================================================

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/fts_learn")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ============================================================================
# PYDANTIC SCHEMAS
# ============================================================================

class ResultType(str, Enum):
    schema = "schema"
    table = "table"
    column = "column"


class SearchResult(BaseModel):
    result_type: ResultType
    entity_id: int
    name: str
    description: Optional[str] = None
    name_highlight: str
    description_highlight: str
    rank: float
    
    # Full context - includes parent information
    schema_id: Optional[int] = None
    schema_name: Optional[str] = None
    table_id: Optional[int] = None
    table_name: Optional[str] = None
    column_id: Optional[int] = None
    column_name: Optional[str] = None
    owner_id: Optional[int] = None
    owner_name: Optional[str] = None


class SearchResponse(BaseModel):
    results: List[SearchResult]
    total_count: int
    page: int
    page_size: int
    total_pages: int
    query: str


class OwnerSchema(BaseModel):
    id: int
    name: str
    email: str


class SchemaSchema(BaseModel):
    id: int
    name: str
    description: Optional[str] = None


# ============================================================================
# FASTAPI APPLICATION
# ============================================================================

app = FastAPI(
    title="Metadata Catalog Search API",
    description="Full-text search across database schemas, tables, and columns with PostgreSQL FTS",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)


@app.get("/search", response_model=SearchResponse, tags=["Search"])
async def search_catalog(
    q: str = Query(..., min_length=1, description="Search keywords (supports AND, OR, NOT, phrases)"),
    owner_id: Optional[int] = Query(None, description="Filter by owner ID"),
    schema_id: Optional[int] = Query(None, description="Filter by schema ID"),
    include_parent_tables: bool = Query(True, description="Include parent tables when columns match"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Results per page"),
    db: Session = Depends(get_db)
):
    """
    Search across schemas, tables, and columns with full-text search.
    
    Features:
    - Full-text search with PostgreSQL FTS (stemming, stop words)
    - Keyword highlighting in results
    - Relevance ranking with ts_rank_cd
    - Filter by owner and schema
    - Pagination support
    - When columns match, optionally return parent tables too
    - Rich context: tables include schema info, columns include table+schema info
    
    Search syntax examples:
    - Simple keywords: `user account`
    - Phrases: `"user account"`
    - Boolean operators: `user AND account`, `user OR customer`, `user -admin`
    - Advanced: `(user OR customer) AND NOT admin`
    
    Ranking priority:
    1. Direct name/description matches (weight A/B)
    2. Column matches that bubble up to parent tables (0.9x rank)
    """
    
    try:
        # Convert search terms to tsquery
        search_query = text("SELECT websearch_to_tsquery('english', :search_terms) as query")
        ts_query_result = db.execute(search_query, {"search_terms": q}).fetchone()
        
        if not ts_query_result.query:
            return SearchResponse(
                results=[],
                total_count=0,
                page=page,
                page_size=page_size,
                total_pages=0,
                query=q
            )
        
        results = []
        
        # Search schemas
        schema_query = text("""
            SELECT 
                'schema' as result_type,
                s.id as entity_id,
                s.name,
                s.description,
                ts_headline('english', s.name, websearch_to_tsquery('english', :search_terms), 
                    'StartSel=<mark>, StopSel=</mark>') as name_highlight,
                ts_headline('english', COALESCE(s.description, ''), websearch_to_tsquery('english', :search_terms),
                    'StartSel=<mark>, StopSel=</mark>, MaxFragments=3, MaxWords=50') as description_highlight,
                -- Enhanced ranking: exact matches get higher score, name matches higher than description
                (CASE 
                    WHEN LOWER(s.name) = LOWER(:search_terms) THEN 10.0
                    WHEN LOWER(s.name) LIKE LOWER('%' || :search_terms || '%') THEN 8.0 + ts_rank_cd(s.search_vector, websearch_to_tsquery('english', :search_terms))
                    ELSE 5.0 + ts_rank_cd(s.search_vector, websearch_to_tsquery('english', :search_terms))
                END) as rank,
                s.id as schema_id,
                s.name as schema_name,
                NULL::integer as table_id,
                NULL::text as table_name,
                NULL::integer as column_id,
                NULL::text as column_name,
                NULL::integer as owner_id,
                NULL::text as owner_name
            FROM schemas s
            WHERE s.search_vector @@ websearch_to_tsquery('english', :search_terms)
        """)
        
        schema_results = db.execute(schema_query, {"search_terms": q}).fetchall()
        results.extend(schema_results)
        
        # Search tables
        table_query = text("""
            SELECT 
                'table' as result_type,
                t.id as entity_id,
                t.name,
                t.description,
                ts_headline('english', t.name, websearch_to_tsquery('english', :search_terms), 
                    'StartSel=<mark>, StopSel=</mark>') as name_highlight,
                ts_headline('english', COALESCE(t.description, ''), websearch_to_tsquery('english', :search_terms),
                    'StartSel=<mark>, StopSel=</mark>, MaxFragments=3, MaxWords=50') as description_highlight,
                -- Enhanced ranking: exact matches get higher score, name matches higher than description
                (CASE 
                    WHEN LOWER(t.name) = LOWER(:search_terms) THEN 9.0
                    WHEN LOWER(t.name) LIKE LOWER('%' || :search_terms || '%') THEN 7.0 + ts_rank_cd(t.search_vector, websearch_to_tsquery('english', :search_terms))
                    ELSE 4.0 + ts_rank_cd(t.search_vector, websearch_to_tsquery('english', :search_terms))
                END) as rank,
                s.id as schema_id,
                s.name as schema_name,
                t.id as table_id,
                t.name as table_name,
                NULL::integer as column_id,
                NULL::text as column_name,
                t.owner_id,
                o.name as owner_name
            FROM tables t
            JOIN schemas s ON t.schema_id = s.id
            LEFT JOIN owners o ON t.owner_id = o.id
            WHERE t.search_vector @@ websearch_to_tsquery('english', :search_terms)
                AND (:owner_id IS NULL OR t.owner_id = :owner_id)
                AND (:schema_id IS NULL OR t.schema_id = :schema_id)
        """)
        
        table_results = db.execute(table_query, {
            "search_terms": q, 
            "owner_id": owner_id, 
            "schema_id": schema_id
        }).fetchall()
        results.extend(table_results)
        
        # Search columns
        column_query = text("""
            SELECT 
                'column' as result_type,
                c.id as entity_id,
                c.name,
                c.description,
                ts_headline('english', c.name, websearch_to_tsquery('english', :search_terms), 
                    'StartSel=<mark>, StopSel=</mark>') as name_highlight,
                ts_headline('english', COALESCE(c.description, ''), websearch_to_tsquery('english', :search_terms),
                    'StartSel=<mark>, StopSel=</mark>, MaxFragments=3, MaxWords=50') as description_highlight,
                -- Enhanced ranking: exact matches get higher score, partial name matches, then description
                (CASE 
                    WHEN LOWER(c.name) = LOWER(:search_terms) THEN 8.0
                    WHEN LOWER(c.name) LIKE LOWER(:search_terms || '%') THEN 6.5 + ts_rank_cd(c.search_vector, websearch_to_tsquery('english', :search_terms))
                    WHEN LOWER(c.name) LIKE LOWER('%' || :search_terms || '%') THEN 6.0 + ts_rank_cd(c.search_vector, websearch_to_tsquery('english', :search_terms))
                    ELSE 3.0 + ts_rank_cd(c.search_vector, websearch_to_tsquery('english', :search_terms))
                END) as rank,
                s.id as schema_id,
                s.name as schema_name,
                t.id as table_id,
                t.name as table_name,
                c.id as column_id,
                c.name as column_name,
                t.owner_id,
                o.name as owner_name
            FROM columns c
            JOIN tables t ON c.table_id = t.id
            JOIN schemas s ON t.schema_id = s.id
            LEFT JOIN owners o ON t.owner_id = o.id
            WHERE c.search_vector @@ websearch_to_tsquery('english', :search_terms)
                AND (:owner_id IS NULL OR t.owner_id = :owner_id)
                AND (:schema_id IS NULL OR t.schema_id = :schema_id)
        """)
        
        column_results = db.execute(column_query, {
            "search_terms": q, 
            "owner_id": owner_id, 
            "schema_id": schema_id
        }).fetchall()
        results.extend(column_results)
        
        # Add parent tables for column matches if requested
        if include_parent_tables and column_results:
            table_ids = {row.table_id for row in column_results}
            existing_table_ids = {row.entity_id for row in table_results}
            
            # Get parent tables that aren't already in results
            missing_table_ids = table_ids - existing_table_ids
            
            if missing_table_ids:
                parent_table_query = text("""
                    SELECT 
                        'table' as result_type,
                        t.id as entity_id,
                        t.name,
                        t.description,
                        t.name as name_highlight,
                        COALESCE(t.description, '') as description_highlight,
                        0.5 as rank,  -- Lower rank for parent tables
                        s.id as schema_id,
                        s.name as schema_name,
                        t.id as table_id,
                        t.name as table_name,
                        NULL::integer as column_id,
                        NULL::text as column_name,
                        t.owner_id,
                        o.name as owner_name
                    FROM tables t
                    JOIN schemas s ON t.schema_id = s.id
                    LEFT JOIN owners o ON t.owner_id = o.id
                    WHERE t.id = ANY(:table_ids)
                """)
                
                parent_results = db.execute(parent_table_query, {
                    "table_ids": list(missing_table_ids)
                }).fetchall()
                results.extend(parent_results)
        
        # Sort by rank (primary) and name length (secondary) for better differentiation
        results = sorted(results, key=lambda x: (x.rank, -len(x.name), x.name), reverse=True)
        
        # Apply pagination
        total_count = len(results)
        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size
        paginated_results = results[start_idx:end_idx]
        
        total_pages = (total_count + page_size - 1) // page_size
        
        search_results = [
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
            for row in paginated_results
        ]
        
        return SearchResponse(
            results=search_results,
            total_count=total_count,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
            query=q
        )
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")


@app.get("/owners", response_model=List[OwnerSchema], tags=["Filters"])
async def list_owners(db: Session = Depends(get_db)):
    """List all owners for filter dropdown."""
    try:
        result = db.execute(text("SELECT id, name, email FROM owners ORDER BY name"))
        rows = result.fetchall()
        
        return [
            OwnerSchema(id=row.id, name=row.name, email=row.email)
            for row in rows
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch owners: {str(e)}")


@app.get("/schemas", response_model=List[SchemaSchema], tags=["Filters"])
async def list_schemas(
    owner_id: Optional[int] = Query(None, description="Filter schemas by owner ID"),
    db: Session = Depends(get_db)
):
    """List all schemas for filter dropdown, optionally filtered by owner."""
    try:
        if owner_id:
            query = text("""
                SELECT DISTINCT s.id, s.name, s.description 
                FROM schemas s 
                JOIN tables t ON s.id = t.schema_id 
                WHERE t.owner_id = :owner_id 
                ORDER BY s.name
            """)
            result = db.execute(query, {"owner_id": owner_id})
        else:
            query = text("SELECT id, name, description FROM schemas ORDER BY name")
            result = db.execute(query)
        
        rows = result.fetchall()
        
        return [
            SchemaSchema(id=row.id, name=row.name, description=row.description)
            for row in rows
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch schemas: {str(e)}")


@app.get("/health", tags=["Health"])
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": "metadata-catalog-search"}


# ============================================================================
# EXAMPLE USAGE AND TESTING
# ============================================================================

@app.get("/search/examples", tags=["Examples"])
async def search_examples():
    """
    Provide example search queries to help users understand the capabilities.
    """
    return {
        "examples": [
            {
                "query": "user",
                "description": "Simple keyword search - finds 'user' in names/descriptions"
            },
            {
                "query": "user account",
                "description": "Multiple keywords - finds records containing both words (AND by default)"
            },
            {
                "query": "\"user account\"",
                "description": "Phrase search - finds exact phrase 'user account'"
            },
            {
                "query": "user AND profile",
                "description": "Boolean AND - both words must be present"
            },
            {
                "query": "user OR customer",
                "description": "Boolean OR - either word can be present"
            },
            {
                "query": "user -admin",
                "description": "Exclusion - contains 'user' but NOT 'admin'"
            },
            {
                "query": "(user OR customer) AND email",
                "description": "Complex boolean - grouped conditions"
            }
        ],
        "filters": {
            "owner_id": "Filter results to specific owner (get list from /owners)",
            "schema_id": "Filter results to specific schema (get list from /schemas)",
            "include_parent_tables": "When column matches, also return parent table (default: true)"
        },
        "ranking": "Results ranked by relevance: name matches > description matches > column matches"
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)