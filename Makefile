.PHONY: help setup db-up db-down db-reset migrate migrate-status migrate-history migrate-downgrade seed clean install api api-dev

# Default target
help:
	@echo "Available commands:"
	@echo "  setup      - Set up the project (create venv, install deps)"
	@echo "  install    - Install Python dependencies using uv"
	@echo "  db-up      - Start PostgreSQL database with Docker"
	@echo "  db-down    - Stop PostgreSQL database"
	@echo "  db-reset   - Reset database (down, up, migrate, seed)"
	@echo "  migrate         - Run Alembic migrations"
	@echo "  migrate-status  - Show current migration status"
	@echo "  migrate-history - Show migration history"
	@echo "  migrate-downgrade - Downgrade to previous migration"
	@echo "  seed       - Seed database with test data"
	@echo "  api        - Start search API server (production)"
	@echo "  api-dev    - Start search API server (development with reload)"
	@echo "  clean      - Remove virtual environment and Docker volumes"

# Set up the project
setup: install db-up migrate seed
	@echo "✅ Project setup complete!"

# Install dependencies
install:
	@echo "🔧 Creating virtual environment and installing dependencies..."
	uv venv
	uv pip install alembic sqlalchemy psycopg2-binary faker python-dotenv
	@echo "✅ Dependencies installed!"

# Start PostgreSQL database
db-up:
	@echo "🐘 Starting PostgreSQL database..."
	docker-compose up -d postgres
	@echo "⏳ Waiting for database to be ready..."
	sleep 10
	@echo "✅ Database is ready!"

# Stop PostgreSQL database
db-down:
	@echo "🛑 Stopping PostgreSQL database..."
	docker-compose down
	@echo "✅ Database stopped!"

# Reset database completely
db-reset: db-down db-up
	@echo "🔄 Resetting database..."
	sleep 5
	make migrate
	make seed
	@echo "✅ Database reset complete!"

# Run database migrations
migrate:
	@echo "🔄 Running database migrations..."
	source .venv/bin/activate && alembic upgrade head
	@echo "✅ Migrations complete!"

# Show current migration status
migrate-status:
	@echo "📊 Current migration status:"
	source .venv/bin/activate && alembic current

# Show migration history
migrate-history:
	@echo "📜 Migration history:"
	source .venv/bin/activate && alembic history --verbose

# Downgrade to previous migration
migrate-downgrade:
	@echo "⬇️  Downgrading to previous migration..."
	source .venv/bin/activate && alembic downgrade -1
	@echo "✅ Downgrade complete!"

# Seed database with test data
seed:
	@echo "🌱 Seeding database with test data..."
	source .venv/bin/activate && python seed_data.py
	@echo "✅ Database seeded!"

# Start API server (production)
api:
	@echo "🚀 Starting search API server..."
	source .venv/bin/activate && uvicorn search_api:app --host 0.0.0.0 --port 8000
	@echo "✅ API server started!"

# Start API server (development with reload)
api-dev:
	@echo "🚀 Starting search API server (development mode)..."
	source .venv/bin/activate && uvicorn search_api:app --host 0.0.0.0 --port 8000 --reload
	@echo "✅ API server started!"

# Clean up project
clean:
	@echo "🧹 Cleaning up..."
	rm -rf .venv
	docker-compose down -v
	@echo "✅ Cleanup complete!"

# Connect to database (useful for debugging)
db-connect:
	@echo "🔌 Connecting to database..."
	docker exec -it pg_fts_db psql -U postgres -d fts_learn

# Show database status
db-status:
	@echo "📊 Database status:"
	docker-compose ps postgres