"""fix search function ambiguous column reference

Revision ID: bf22d91ea9e2
Revises: 9449339023ee
Create Date: 2026-01-03 23:31:58.319773

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'bf22d91ea9e2'
down_revision: Union[str, Sequence[str], None] = '9449339023ee'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Fix the search function to resolve ambiguous column references."""
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
                    NULL::text AS owner_name
                FROM schemas s
                WHERE s.search_vector @@ query
                
                UNION ALL
                
                -- Table matches
                SELECT 
                    'table'::text AS result_type,
                    t.id AS entity_id,
                    t.name,
                    t.description,
                    ts_headline('english', t.name, query, 
                        'StartSel=<mark>, StopSel=</mark>') AS name_highlight,
                    ts_headline('english', COALESCE(t.description, ''), query,
                        'StartSel=<mark>, StopSel=</mark>, MaxFragments=3, MaxWords=50') AS description_highlight,
                    ts_rank_cd(t.search_vector, query) AS rank,
                    s.id AS schema_id,
                    s.name AS schema_name,
                    t.id AS table_id,
                    t.name AS table_name,
                    NULL::integer AS column_id,
                    NULL::text AS column_name,
                    t.owner_id AS owner_id,
                    o.name AS owner_name
                FROM tables t
                JOIN schemas s ON t.schema_id = s.id
                LEFT JOIN owners o ON t.owner_id = o.id
                WHERE t.search_vector @@ query
                
                UNION ALL
                
                -- Column matches
                SELECT 
                    'column'::text AS result_type,
                    c.id AS entity_id,
                    c.name,
                    c.description,
                    ts_headline('english', c.name, query, 
                        'StartSel=<mark>, StopSel=</mark>') AS name_highlight,
                    ts_headline('english', COALESCE(c.description, ''), query,
                        'StartSel=<mark>, StopSel=</mark>, MaxFragments=3, MaxWords=50') AS description_highlight,
                    ts_rank_cd(c.search_vector, query) AS rank,
                    s.id AS schema_id,
                    s.name AS schema_name,
                    t.id AS table_id,
                    t.name AS table_name,
                    c.id AS column_id,
                    c.name AS column_name,
                    t.owner_id AS owner_id,
                    o.name AS owner_name
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
                    'table'::text AS result_type,
                    t.id AS entity_id,
                    t.name,
                    t.description,
                    t.name AS name_highlight,  -- No highlight for parent
                    COALESCE(t.description, '') AS description_highlight,
                    dm.rank * 0.9 AS rank,  -- Slightly lower rank than direct match
                    s.id AS schema_id,
                    s.name AS schema_name,
                    t.id AS table_id,
                    t.name AS table_name,
                    NULL::integer AS column_id,
                    NULL::text AS column_name,
                    t.owner_id AS owner_id,
                    o.name AS owner_name
                FROM direct_matches dm
                JOIN tables t ON dm.table_id = t.id
                JOIN schemas s ON t.schema_id = s.id
                LEFT JOIN owners o ON t.owner_id = o.id
                WHERE dm.result_type = 'column'
                  AND include_parent_tables = true
                  AND NOT EXISTS (
                      SELECT 1 FROM direct_matches dm2
                      WHERE dm2.result_type = 'table' AND dm2.entity_id = t.id
                  )
            ),
            
            -- Apply filters
            filtered AS (
                SELECT * FROM with_parents wp
                WHERE (filter_owner_id IS NULL OR wp.owner_id = filter_owner_id)
                  AND (filter_schema_id IS NULL OR wp.schema_id = filter_schema_id)
            ),
            
            -- Deduplicate and count
            deduped AS (
                SELECT DISTINCT ON (f.result_type, f.entity_id)
                    f.*
                FROM filtered f
                ORDER BY f.result_type, f.entity_id, f.rank DESC
            ),
            
            counted AS (
                SELECT d.*, COUNT(*) OVER() AS total_count
                FROM deduped d
            )
            
            SELECT 
                c.result_type,
                c.entity_id,
                c.name,
                c.description,
                c.name_highlight,
                c.description_highlight,
                c.rank,
                c.schema_id,
                c.schema_name,
                c.table_id,
                c.table_name,
                c.column_id,
                c.column_name,
                c.owner_id,
                c.owner_name,
                c.total_count
            FROM counted c
            ORDER BY c.rank DESC, c.result_type, c.name
            LIMIT page_size
            OFFSET offset_val;
        END;
        $$ LANGUAGE plpgsql;
    """)


def downgrade() -> None:
    """Revert to previous version of search function."""
    # The previous version will still be available from the previous migration
    pass
