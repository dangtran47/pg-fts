from sqlalchemy import Column, Integer, String, Text, ForeignKey, DateTime, func
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()


class Owner(Base):
    __tablename__ = 'owners'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    email = Column(String(255), nullable=False, unique=True)
    created_at = Column(DateTime, server_default=func.now())
    
    tables = relationship("Table", back_populates="owner")


class Schema(Base):
    __tablename__ = 'schemas'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    created_at = Column(DateTime, server_default=func.now())
    
    tables = relationship("Table", back_populates="schema")


class Table(Base):
    __tablename__ = 'tables'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    schema_id = Column(Integer, ForeignKey('schemas.id'), nullable=False)
    owner_id = Column(Integer, ForeignKey('owners.id'), nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    
    schema = relationship("Schema", back_populates="tables")
    owner = relationship("Owner", back_populates="tables")
    columns = relationship("Column", back_populates="table")


class Column(Base):
    __tablename__ = 'columns'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    table_id = Column(Integer, ForeignKey('tables.id'), nullable=False)
    created_at = Column(DateTime, server_default=func.now())
    
    table = relationship("Table", back_populates="columns")