"""add catalog search function

Revision ID: 9449339023ee
Revises: 3f300c263188
Create Date: 2026-01-03 23:14:25.806560

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9449339023ee'
down_revision: Union[str, Sequence[str], None] = '3f300c263188'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the catalog search function."""
    op.execute("""
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
                    NULL::integer AS owner_id,
                    NULL::text AS owner_name,
                    FALSE AS is_parent_result
                FROM schemas s
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
                    t.owner_id,
                    o.name,
                    FALSE
                FROM tables t
                JOIN schemas s ON t.schema_id = s.id
                LEFT JOIN owners o ON t.owner_id = o.id
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
                    t.owner_id,
                    o.name,
                    FALSE
                FROM columns c
                JOIN tables t ON c.table_id = t.id
                JOIN schemas s ON t.schema_id = s.id
                LEFT JOIN owners o ON t.owner_id = o.id
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
                    t.owner_id,
                    o.name,
                    TRUE
                FROM direct_matches dm
                JOIN tables t ON dm.table_id = t.id
                JOIN schemas s ON t.schema_id = s.id
                LEFT JOIN owners o ON t.owner_id = o.id
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
    """)


def downgrade() -> None:
    """Drop the catalog search function."""
    op.execute("DROP FUNCTION IF EXISTS search_catalog(TEXT, INTEGER, INTEGER, BOOLEAN, INTEGER, INTEGER);")
