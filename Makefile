.PHONY: help setup db-up db-down db-reset migrate seed clean install

# Default target
help:
	@echo "Available commands:"
	@echo "  setup      - Set up the project (create venv, install deps)"
	@echo "  install    - Install Python dependencies using uv"
	@echo "  db-up      - Start PostgreSQL database with Docker"
	@echo "  db-down    - Stop PostgreSQL database"
	@echo "  db-reset   - Reset database (down, up, migrate, seed)"
	@echo "  migrate    - Run Alembic migrations"
	@echo "  seed       - Seed database with test data"
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

# Seed database with test data
seed:
	@echo "🌱 Seeding database with test data..."
	source .venv/bin/activate && python seed_data.py
	@echo "✅ Database seeded!"

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