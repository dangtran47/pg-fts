-- Create database schema with owners, schemas, tables, and columns

-- Create owners table
CREATE TABLE owners (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL
);

-- Create schemas table
CREATE TABLE schemas (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    description TEXT
);

-- Create tables table
CREATE TABLE tables (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    schema_id INTEGER NOT NULL REFERENCES schemas(id),
    owner_id INTEGER REFERENCES owners(id)
);

-- Create columns table
CREATE TABLE columns (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    table_id INTEGER NOT NULL REFERENCES tables(id)
);

-- Insert seed data

-- Seed owners
INSERT INTO owners (name, email) VALUES
('Alice Johnson', 'alice.johnson@company.com'),
('Bob Smith', 'bob.smith@company.com'),
('Carol Davis', 'carol.davis@company.com'),
('David Wilson', 'david.wilson@company.com');

-- Seed schemas
INSERT INTO schemas (name, description) VALUES
('public', 'Default public schema for general tables'),
('analytics', 'Schema for analytical data and reports'),
('auth', 'Schema for authentication and user management'),
('inventory', 'Schema for inventory and product management');

-- Seed tables
INSERT INTO tables (name, description, schema_id, owner_id) VALUES
('users', 'User account information', 3, 1),
('products', 'Product catalog data', 4, 2),
('orders', 'Customer order records', 1, 3),
('categories', 'Product categories', 4, 2),
('user_sessions', 'Active user session tracking', 3, 1),
('sales_metrics', 'Daily sales performance data', 2, 4),
('inventory_logs', 'Inventory movement history', 4, NULL);

-- Seed columns
INSERT INTO columns (name, description, table_id) VALUES
-- users table columns (id=1)
('user_id', 'Primary key for users', 1),
('username', 'Unique username for login', 1),
('email', 'User email address', 1),
('created_at', 'Account creation timestamp', 1),
('last_login', 'Last login timestamp', 1),

-- products table columns (id=2)
('product_id', 'Primary key for products', 2),
('name', 'Product name', 2),
('price', 'Product price in cents', 2),
('category_id', 'Foreign key to categories', 2),
('stock_quantity', 'Available inventory count', 2),

-- orders table columns (id=3)
('order_id', 'Primary key for orders', 3),
('user_id', 'Foreign key to users', 3),
('total_amount', 'Order total in cents', 3),
('order_date', 'Date order was placed', 3),
('status', 'Current order status', 3),

-- categories table columns (id=4)
('category_id', 'Primary key for categories', 4),
('name', 'Category name', 4),
('description', 'Category description', 4),

-- user_sessions table columns (id=5)
('session_id', 'Primary key for sessions', 5),
('user_id', 'Foreign key to users', 5),
('session_token', 'Unique session identifier', 5),
('expires_at', 'Session expiration time', 5),

-- sales_metrics table columns (id=6)
('metric_id', 'Primary key for metrics', 6),
('date', 'Date of the metric', 6),
('total_sales', 'Total sales amount for the day', 6),
('order_count', 'Number of orders placed', 6),

-- inventory_logs table columns (id=7)
('log_id', 'Primary key for logs', 7),
('product_id', 'Foreign key to products', 7),
('change_quantity', 'Quantity change (positive or negative)', 7),
('change_type', 'Type of inventory change', 7),
('timestamp', 'When the change occurred', 7);