import os
import random
from faker import Faker
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv
from models import Owner, Schema, Table, Column, Base

load_dotenv()

fake = Faker()

DATABASE_URL = os.getenv('DATABASE_URL')
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Data generation helpers
SCHEMA_TYPES = [
    'public', 'sales', 'marketing', 'finance', 'hr', 'inventory', 
    'analytics', 'logs', 'audit', 'staging'
]

TABLE_CATEGORIES = [
    'users', 'orders', 'products', 'customers', 'transactions', 'invoices',
    'employees', 'departments', 'projects', 'tasks', 'campaigns', 'leads',
    'inventory_items', 'suppliers', 'warehouses', 'reports', 'logs', 'sessions',
    'categories', 'tags', 'comments', 'reviews', 'notifications', 'settings'
]

COLUMN_TYPES = [
    'id', 'name', 'email', 'password', 'phone', 'address', 'city', 'state',
    'zip_code', 'country', 'created_at', 'updated_at', 'deleted_at', 'status',
    'title', 'description', 'content', 'price', 'quantity', 'amount', 'total',
    'date_started', 'date_completed', 'priority', 'category', 'tag', 'score',
    'rating', 'comment', 'notes', 'metadata', 'configuration', 'settings'
]

def generate_owners(session, count=5):
    """Generate random owners with realistic data."""
    owners = []
    for _ in range(count):
        owner = Owner(
            name=fake.name(),
            email=fake.unique.email()
        )
        owners.append(owner)
        session.add(owner)
    session.commit()
    return owners

def generate_schemas(session, count=10):
    """Generate random schemas with meaningful names and descriptions."""
    schemas = []
    for _ in range(count):
        schema_name = random.choice(SCHEMA_TYPES) + f"_{fake.word()}"
        schema_desc = fake.text(max_nb_chars=200)
        
        schema = Schema(
            name=schema_name,
            description=schema_desc
        )
        schemas.append(schema)
        session.add(schema)
    session.commit()
    return schemas

def generate_tables(session, schemas, owners, count=100):
    """Generate random tables with realistic names and optional owners."""
    tables = []
    for _ in range(count):
        table_category = random.choice(TABLE_CATEGORIES)
        table_suffix = fake.word() if random.choice([True, False]) else ""
        table_name = f"{table_category}_{table_suffix}" if table_suffix else table_category
        
        table_desc = fake.text(max_nb_chars=150)
        schema = random.choice(schemas)
        owner = random.choice(owners + [None] * 3)  # 75% chance of having an owner
        
        table = Table(
            name=table_name,
            description=table_desc,
            schema_id=schema.id,
            owner_id=owner.id if owner else None
        )
        tables.append(table)
        session.add(table)
    session.commit()
    return tables

def generate_columns(session, tables, count=1000):
    """Generate random columns with meaningful names for each table."""
    columns = []
    tables_per_column_batch = count // len(tables)
    remaining_columns = count % len(tables)
    
    for i, table in enumerate(tables):
        # Calculate how many columns this table should have
        columns_for_table = tables_per_column_batch
        if i < remaining_columns:
            columns_for_table += 1
        
        # Ensure each table has at least 3 columns and at most 25
        columns_for_table = max(3, min(25, columns_for_table))
        
        # Generate columns for this table
        used_column_names = set()
        for _ in range(columns_for_table):
            # Ensure unique column names per table
            attempts = 0
            while attempts < 50:  # Prevent infinite loop
                base_name = random.choice(COLUMN_TYPES)
                column_name = f"{base_name}_{fake.word()}" if random.choice([True, False]) else base_name
                
                if column_name not in used_column_names:
                    used_column_names.add(column_name)
                    break
                attempts += 1
            else:
                # Fallback if we can't find a unique name
                column_name = f"column_{len(used_column_names) + 1}"
                used_column_names.add(column_name)
            
            column_desc = fake.text(max_nb_chars=100)
            
            column = Column(
                name=column_name,
                description=column_desc,
                table_id=table.id
            )
            columns.append(column)
            session.add(column)
    
    session.commit()
    return columns

def seed_database():
    """Main function to seed the database with test data."""
    session = SessionLocal()
    try:
        # Clear existing data (optional - remove if you want to append)
        print("Clearing existing data...")
        session.query(Column).delete()
        session.query(Table).delete()
        session.query(Schema).delete()
        session.query(Owner).delete()
        session.commit()
        
        print("Generating 5 owners...")
        owners = generate_owners(session, 5)
        
        print("Generating 10 schemas...")
        schemas = generate_schemas(session, 10)
        
        print("Generating 100 tables...")
        tables = generate_tables(session, schemas, owners, 100)
        
        print("Generating 1000 columns...")
        columns = generate_columns(session, tables, 1000)
        
        print(f"\n✅ Database seeded successfully!")
        print(f"   - {len(owners)} owners created")
        print(f"   - {len(schemas)} schemas created")
        print(f"   - {len(tables)} tables created")
        print(f"   - {len(columns)} columns created")
        
    except Exception as e:
        session.rollback()
        print(f"❌ Error seeding database: {e}")
        raise
    finally:
        session.close()

if __name__ == "__main__":
    seed_database()