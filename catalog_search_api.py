"""
Complete PostgreSQL Full-Text Search Implementation for Metadata Catalog
FastAPI + SQLAlchemy + PostgreSQL

Run with:
    pip install fastapi uvicorn sqlalchemy psycopg2-binary pydantic
    uvicorn main:app --reload
"""

from fastapi import FastAPI, Query, Depends, HTTPException
from sqlalchemy import (
    create_engine, Column, Integer, String, Text, ForeignKey, 
    Index, text, event, DDL
)
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Session, relationship, sessionmaker, declarative_base
from pydantic import BaseModel
from typing import List, Optional
from enum import Enum
from contextlib import contextmanager

# ============================================================================
# DATABASE SETUP
# ============================================================================

DATABASE_URL = "postgresql://user:password@localhost:5432/catalog_db"

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ============================================================================
# MODELS
# ============================================================================

class Owner(Base):
    __tablename__ = 'owners'
    
    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False, unique=True)


class Schema(Base):
    __tablename__ = 'schemas'
    
    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    owner_id = Column(Integer, ForeignKey('owners.id'), nullable=False)
    search_vector = Column(TSVECTOR)
    
    owner = relationship('Owner', backref='schemas')
    
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
    
    schema = relationship('Schema', backref='tables')
    owner = relationship('Owner', backref='tables')
    
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
    
    table = relationship('Table', backref='columns')
    
    __table_args__ = (
        Index('idx_columns_search', 'search_vector', postgresql_using='gin'),
    )


# ============================================================================
# DATABASE TRIGGERS (Auto-update search vectors)
# ============================================================================

# Trigger functions and triggers for auto-updating search_vector
SEARCH_VECTOR_TRIGGER_FUNCTION = """
CREATE OR REPLACE FUNCTION update_search_vector()
RETURNS trigger AS $$
BEGIN
    NEW.search_vector := 
        setweight(to_tsvector('english', coalesce(NEW.name, '')), 'A') ||
        setweight(to_tsvector('english', coalesce(NEW.description, '')), 'B');
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

SCHEMA_TRIGGER = """
DROP TRIGGER IF EXISTS schemas_search_vector_update ON schemas;
CREATE TRIGGER schemas_search_vector_update
    BEFORE INSERT OR UPDATE ON schemas
    FOR EACH ROW EXECUTE FUNCTION update_search_vector();
"""

TABLE_TRIGGER = """
DROP TRIGGER IF EXISTS tables_search_vector_update ON tables;
CREATE TRIGGER tables_search_vector_update
    BEFORE INSERT OR UPDATE ON tables
    FOR EACH ROW EXECUTE FUNCTION update_search_vector();
"""

COLUMN_TRIGGER = """
DROP TRIGGER IF EXISTS columns_search_vector_update ON columns;
CREATE TRIGGER columns_search_vector_update
    BEFORE INSERT OR UPDATE ON columns
    FOR EACH ROW EXECUTE FUNCTION update_search_vector();
"""


# ============================================================================
# SEARCH FUNCTION
# ============================================================================

SEARCH_FUNCTION = """
CREATE OR REPLACE FUNCTION search_catalog(
    search_terms TEXT,
    filter_owner_id INTEGER DEFAULT NULL,
    filter_schema_id INTEGER DEFAULT NULL,
    include_parent_tables BOOLEAN DEFAULT TRUE,
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
    WITH 
    -- Direct matches
    direct_matches AS (
        -- Schema matches
        SELECT 
            'schema'::text AS result_type,
            s.id AS entity_id,
            s.name,
            s.description,
            ts_headline('english', s.name, query, 
                'StartSel=<mark>, StopSel=</mark>') AS name_highlight,
            ts_headline('english', COALESCE(s.description, ''), query,
                'StartSel=<mark>, StopSel=</mark>, MaxFragments=3, MaxWords=50') AS description_highlight,
            ts_rank_cd(s.search_vector, query) AS rank,
            s.id AS schema_id,
            s.name AS schema_name,
            NULL::integer AS table_id,
            NULL::text AS table_name,
            NULL::integer AS column_id,
            NULL::text AS column_name,
            o.id AS owner_id,
            o.name AS owner_name,
            FALSE AS is_parent_result
        FROM schemas s
        JOIN owners o ON s.owner_id = o.id
        WHERE s.search_vector @@ query
        
        UNION ALL
        
        -- Table matches
        SELECT 
            'table'::text,
            t.id,
            t.name,
            t.description,
            ts_headline('english', t.name, query, 
                'StartSel=<mark>, StopSel=</mark>'),
            ts_headline('english', COALESCE(t.description, ''), query,
                'StartSel=<mark>, StopSel=</mark>, MaxFragments=3, MaxWords=50'),
            ts_rank_cd(t.search_vector, query),
            s.id,
            s.name,
            t.id,
            t.name,
            NULL::integer,
            NULL::text,
            o.id,
            o.name,
            FALSE
        FROM tables t
        JOIN schemas s ON t.schema_id = s.id
        JOIN owners o ON t.owner_id = o.id
        WHERE t.search_vector @@ query
        
        UNION ALL
        
        -- Column matches
        SELECT 
            'column'::text,
            c.id,
            c.name,
            c.description,
            ts_headline('english', c.name, query, 
                'StartSel=<mark>, StopSel=</mark>'),
            ts_headline('english', COALESCE(c.description, ''), query,
                'StartSel=<mark>, StopSel=</mark>, MaxFragments=3, MaxWords=50'),
            ts_rank_cd(c.search_vector, query),
            s.id,
            s.name,
            t.id,
            t.name,
            c.id,
            c.name,
            o.id,
            o.name,
            FALSE
        FROM columns c
        JOIN tables t ON c.table_id = t.id
        JOIN schemas s ON t.schema_id = s.id
        JOIN owners o ON t.owner_id = o.id
        WHERE c.search_vector @@ query
    ),
    
    -- Add parent tables for column matches (when include_parent_tables is true)
    with_parents AS (
        SELECT * FROM direct_matches
        
        UNION ALL
        
        SELECT DISTINCT ON (t.id)
            'table'::text,
            t.id,
            t.name,
            t.description,
            t.name,  -- No highlight for parent
            COALESCE(t.description, ''),
            dm.rank * 0.9,  -- Slightly lower rank than direct match
            s.id,
            s.name,
            t.id,
            t.name,
            NULL::integer,
            NULL::text,
            o.id,
            o.name,
            TRUE
        FROM direct_matches dm
        JOIN tables t ON dm.table_id = t.id
        JOIN schemas s ON t.schema_id = s.id
        JOIN owners o ON t.owner_id = o.id
        WHERE dm.result_type = 'column'
          AND include_parent_tables
          AND NOT EXISTS (
              SELECT 1 FROM direct_matches 
              WHERE result_type = 'table' AND entity_id = t.id
          )
    ),
    
    -- Apply filters
    filtered AS (
        SELECT * FROM with_parents
        WHERE (filter_owner_id IS NULL OR with_parents.owner_id = filter_owner_id)
          AND (filter_schema_id IS NULL OR with_parents.schema_id = filter_schema_id)
    ),
    
    -- Deduplicate and count
    deduped AS (
        SELECT DISTINCT ON (filtered.result_type, filtered.entity_id)
            filtered.*
        FROM filtered
        ORDER BY filtered.result_type, filtered.entity_id, filtered.rank DESC
    ),
    
    counted AS (
        SELECT *, COUNT(*) OVER() AS total_count
        FROM deduped
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
    ORDER BY counted.rank DESC, counted.result_type, counted.name
    LIMIT page_size
    OFFSET offset_val;
END;
$$ LANGUAGE plpgsql;
"""


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
    
    # Full context
    schema_id: Optional[int] = None
    schema_name: Optional[str] = None
    table_id: Optional[int] = None
    table_name: Optional[str] = None
    column_id: Optional[int] = None
    column_name: Optional[str] = None
    owner_id: int
    owner_name: str
    
    class Config:
        from_attributes = True


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
    
    class Config:
        from_attributes = True


class SchemaSchema(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    owner_id: int
    
    class Config:
        from_attributes = True


# ============================================================================
# FASTAPI APPLICATION
# ============================================================================

app = FastAPI(
    title="Metadata Catalog Search API",
    description="Full-text search across schemas, tables, and columns",
    version="1.0.0"
)


@app.on_event("startup")
async def setup_database():
    """Create tables and install search functions on startup."""
    Base.metadata.create_all(bind=engine)
    
    with engine.connect() as conn:
        conn.execute(text(SEARCH_VECTOR_TRIGGER_FUNCTION))
        conn.execute(text(SCHEMA_TRIGGER))
        conn.execute(text(TABLE_TRIGGER))
        conn.execute(text(COLUMN_TRIGGER))
        conn.execute(text(SEARCH_FUNCTION))
        conn.commit()


@app.get("/search", response_model=SearchResponse, tags=["Search"])
async def search_catalog(
    q: str = Query(..., min_length=1, description="Search keywords (supports AND, OR, NOT)"),
    owner_id: Optional[int] = Query(None, description="Filter by owner ID"),
    schema_id: Optional[int] = Query(None, description="Filter by schema ID"),
    include_parent_tables: bool = Query(True, description="Include parent tables when columns match"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Results per page"),
    db: Session = Depends(get_db)
):
    """
    Search across schemas, tables, and columns.
    
    Features:
    - Full-text search with stemming and stop words
    - Keyword highlighting in results
    - Relevance ranking
    - Filter by owner and schema
    - Pagination
    - When a column matches, optionally return its parent table too
    
    Search syntax:
    - Simple: `user account`
    - Phrase: `"user account"`
    - AND: `user AND account`
    - OR: `user OR account`
    - NOT: `user -admin`
    """
    
    query = text("""
        SELECT * FROM search_catalog(
            :search_terms,
            :owner_id,
            :schema_id,
            :include_parent_tables,
            :page,
            :page_size
        )
    """)
    
    result = db.execute(query, {
        "search_terms": q,
        "owner_id": owner_id,
        "schema_id": schema_id,
        "include_parent_tables": include_parent_tables,
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
            total_pages=0,
            query=q
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
        total_pages=total_pages,
        query=q
    )


@app.get("/owners", response_model=List[OwnerSchema], tags=["Filters"])
async def list_owners(db: Session = Depends(get_db)):
    """List all owners for filter dropdown."""
    return db.query(Owner).order_by(Owner.name).all()


@app.get("/schemas", response_model=List[SchemaSchema], tags=["Filters"])
async def list_schemas(
    owner_id: Optional[int] = None,
    db: Session = Depends(get_db)
):
    """List all schemas for filter dropdown, optionally filtered by owner."""
    query = db.query(Schema)
    if owner_id:
        query = query.filter(Schema.owner_id == owner_id)
    return query.order_by(Schema.name).all()


# ============================================================================
# SEED DATA (for testing)
# ============================================================================

@app.post("/seed", tags=["Admin"])
async def seed_database(db: Session = Depends(get_db)):
    """Seed database with sample data for testing."""
    
    # Clear existing data
    db.query(Column_).delete()
    db.query(Table).delete()
    db.query(Schema).delete()
    db.query(Owner).delete()
    
    # Create owners
    owners = [
        Owner(name="Data Engineering"),
        Owner(name="Analytics"),
        Owner(name="Product")
    ]
    db.add_all(owners)
    db.flush()
    
    # Create schemas
    schemas = [
        Schema(name="raw", description="Raw ingested data from source systems", owner_id=owners[0].id),
        Schema(name="staging", description="Cleaned and validated staging area", owner_id=owners[0].id),
        Schema(name="analytics", description="Analytics-ready data models", owner_id=owners[1].id),
        Schema(name="reporting", description="Business intelligence reporting tables", owner_id=owners[1].id),
    ]
    db.add_all(schemas)
    db.flush()
    
    # Create tables
    tables = [
        Table(name="users", description="User account information and profiles", schema_id=schemas[0].id, owner_id=owners[0].id),
        Table(name="orders", description="Customer order transactions", schema_id=schemas[0].id, owner_id=owners[0].id),
        Table(name="products", description="Product catalog with pricing", schema_id=schemas[0].id, owner_id=owners[2].id),
        Table(name="dim_users", description="User dimension table for analytics", schema_id=schemas[2].id, owner_id=owners[1].id),
        Table(name="fact_orders", description="Order fact table with metrics", schema_id=schemas[2].id, owner_id=owners[1].id),
        Table(name="daily_sales", description="Daily aggregated sales report", schema_id=schemas[3].id, owner_id=owners[1].id),
    ]
    db.add_all(tables)
    db.flush()
    
    # Create columns
    columns = [
        # users table columns
        Column_(name="user_id", description="Unique identifier for each user", table_id=tables[0].id),
        Column_(name="email", description="User email address", table_id=tables[0].id),
        Column_(name="created_at", description="Account creation timestamp", table_id=tables[0].id),
        Column_(name="is_premium", description="Premium subscription status", table_id=tables[0].id),
        
        # orders table columns
        Column_(name="order_id", description="Unique order identifier", table_id=tables[1].id),
        Column_(name="user_id", description="Reference to user who placed order", table_id=tables[1].id),
        Column_(name="total_amount", description="Total order value in USD", table_id=tables[1].id),
        Column_(name="order_date", description="Date order was placed", table_id=tables[1].id),
        
        # products table columns
        Column_(name="product_id", description="Unique product identifier", table_id=tables[2].id),
        Column_(name="product_name", description="Display name of product", table_id=tables[2].id),
        Column_(name="price", description="Current selling price", table_id=tables[2].id),
        Column_(name="category", description="Product category classification", table_id=tables[2].id),
        
        # dim_users columns
        Column_(name="user_key", description="Surrogate key for user dimension", table_id=tables[3].id),
        Column_(name="user_id", description="Natural key from source system", table_id=tables[3].id),
        Column_(name="user_segment", description="Customer segmentation category", table_id=tables[3].id),
        
        # fact_orders columns
        Column_(name="order_key", description="Surrogate key for order fact", table_id=tables[4].id),
        Column_(name="revenue", description="Order revenue in local currency", table_id=tables[4].id),
        Column_(name="quantity", description="Number of items in order", table_id=tables[4].id),
        
        # daily_sales columns
        Column_(name="report_date", description="Date of sales report", table_id=tables[5].id),
        Column_(name="total_revenue", description="Total daily revenue", table_id=tables[5].id),
        Column_(name="order_count", description="Number of orders placed", table_id=tables[5].id),
    ]
    db.add_all(columns)
    db.commit()
    
    return {
        "message": "Database seeded successfully",
        "counts": {
            "owners": len(owners),
            "schemas": len(schemas),
            "tables": len(tables),
            "columns": len(columns)
        }
    }


# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
