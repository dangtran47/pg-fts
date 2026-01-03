"""add search vectors and indexes for full text search

Revision ID: 3f300c263188
Revises: 48308cdeb059
Create Date: 2026-01-03 23:13:44.199844

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import TSVECTOR


# revision identifiers, used by Alembic.
revision: str = '3f300c263188'
down_revision: Union[str, Sequence[str], None] = '48308cdeb059'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add search_vector columns to each table
    op.add_column('schemas', sa.Column('search_vector', TSVECTOR))
    op.add_column('tables', sa.Column('search_vector', TSVECTOR))
    op.add_column('columns', sa.Column('search_vector', TSVECTOR))
    
    # Create GIN indexes for fast full-text search
    op.create_index('idx_schemas_search', 'schemas', ['search_vector'], postgresql_using='gin')
    op.create_index('idx_tables_search', 'tables', ['search_vector'], postgresql_using='gin')
    op.create_index('idx_columns_search', 'columns', ['search_vector'], postgresql_using='gin')
    
    # Create trigger function for auto-updating search vectors
    op.execute("""
        CREATE OR REPLACE FUNCTION update_search_vector()
        RETURNS trigger AS $$
        BEGIN
            NEW.search_vector := 
                setweight(to_tsvector('english', coalesce(NEW.name, '')), 'A') ||
                setweight(to_tsvector('english', coalesce(NEW.description, '')), 'B');
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    
    # Create triggers for each table
    op.execute("""
        DROP TRIGGER IF EXISTS schemas_search_vector_update ON schemas;
        CREATE TRIGGER schemas_search_vector_update
            BEFORE INSERT OR UPDATE ON schemas
            FOR EACH ROW EXECUTE FUNCTION update_search_vector();
    """)
    
    op.execute("""
        DROP TRIGGER IF EXISTS tables_search_vector_update ON tables;
        CREATE TRIGGER tables_search_vector_update
            BEFORE INSERT OR UPDATE ON tables
            FOR EACH ROW EXECUTE FUNCTION update_search_vector();
    """)
    
    op.execute("""
        DROP TRIGGER IF EXISTS columns_search_vector_update ON columns;
        CREATE TRIGGER columns_search_vector_update
            BEFORE INSERT OR UPDATE ON columns
            FOR EACH ROW EXECUTE FUNCTION update_search_vector();
    """)
    
    # Update existing data
    op.execute("""
        UPDATE schemas SET search_vector = 
            setweight(to_tsvector('english', coalesce(name, '')), 'A') ||
            setweight(to_tsvector('english', coalesce(description, '')), 'B');
    """)
    
    op.execute("""
        UPDATE tables SET search_vector = 
            setweight(to_tsvector('english', coalesce(name, '')), 'A') ||
            setweight(to_tsvector('english', coalesce(description, '')), 'B');
    """)
    
    op.execute("""
        UPDATE columns SET search_vector = 
            setweight(to_tsvector('english', coalesce(name, '')), 'A') ||
            setweight(to_tsvector('english', coalesce(description, '')), 'B');
    """)


def downgrade() -> None:
    """Downgrade schema."""
    # Drop triggers
    op.execute("DROP TRIGGER IF EXISTS schemas_search_vector_update ON schemas;")
    op.execute("DROP TRIGGER IF EXISTS tables_search_vector_update ON tables;")
    op.execute("DROP TRIGGER IF EXISTS columns_search_vector_update ON columns;")
    
    # Drop trigger function
    op.execute("DROP FUNCTION IF EXISTS update_search_vector();")
    
    # Drop indexes
    op.drop_index('idx_columns_search', table_name='columns')
    op.drop_index('idx_tables_search', table_name='tables')
    op.drop_index('idx_schemas_search', table_name='schemas')
    
    # Drop columns
    op.drop_column('columns', 'search_vector')
    op.drop_column('tables', 'search_vector')
    op.drop_column('schemas', 'search_vector')
