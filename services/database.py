"""
PostgreSQL Database Layer for LatterPay
========================================
Handles database connections with automatic fallback to SQLite.
Supports both PostgreSQL (production) and SQLite (development).

Author: Nyasha Mapetere
Version: 1.0.0
"""

import os
import logging
from typing import Optional, Any, List, Tuple
from contextlib import contextmanager
import threading

logger = logging.getLogger(__name__)

# Check for PostgreSQL availability
DATABASE_URL = os.getenv("DATABASE_URL")
USE_POSTGRES = bool(DATABASE_URL)

if USE_POSTGRES:
    try:
        import psycopg2
        from psycopg2 import pool
        from psycopg2.extras import RealDictCursor
        POSTGRES_AVAILABLE = True
        logger.info("PostgreSQL driver loaded successfully")
    except ImportError:
        POSTGRES_AVAILABLE = False
        USE_POSTGRES = False
        logger.warning("psycopg2 not installed, falling back to SQLite")
else:
    POSTGRES_AVAILABLE = False
    logger.info("DATABASE_URL not set, using SQLite")

import sqlite3


class DatabaseConnection:
    """
    Unified database connection that works with both PostgreSQL and SQLite.
    Automatically uses PostgreSQL if DATABASE_URL is set.
    """
    
    _pool = None
    _pool_lock = threading.Lock()
    
    def __init__(self, db_path: str = "botdata.db"):
        self.db_path = db_path
        self.use_postgres = USE_POSTGRES and POSTGRES_AVAILABLE
        
        if self.use_postgres:
            self._init_postgres_pool()
    
    def _init_postgres_pool(self):
        """Initialize PostgreSQL connection pool."""
        with self._pool_lock:
            if DatabaseConnection._pool is None:
                try:
                    # Convert Railway's postgres:// to postgresql://
                    db_url = DATABASE_URL
                    if db_url.startswith("postgres://"):
                        db_url = db_url.replace("postgres://", "postgresql://", 1)
                    
                    DatabaseConnection._pool = psycopg2.pool.ThreadedConnectionPool(
                        minconn=2,
                        maxconn=10,
                        dsn=db_url
                    )
                    logger.info("PostgreSQL connection pool initialized")
                except Exception as e:
                    logger.error(f"Failed to create PostgreSQL pool: {e}")
                    self.use_postgres = False
    
    @contextmanager
    def get_connection(self):
        """Get a database connection (context manager)."""
        if self.use_postgres and DatabaseConnection._pool:
            conn = None
            try:
                conn = DatabaseConnection._pool.getconn()
                yield conn
            finally:
                if conn:
                    DatabaseConnection._pool.putconn(conn)
        else:
            # SQLite fallback
            conn = sqlite3.connect(self.db_path, timeout=30)
            conn.row_factory = sqlite3.Row
            try:
                yield conn
            finally:
                conn.close()
    
    def execute(self, query: str, params: tuple = (), commit: bool = False) -> List[Any]:
        """Execute a query and return results."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Convert ? placeholders to %s for PostgreSQL
            if self.use_postgres:
                query = query.replace("?", "%s")
            
            cursor.execute(query, params)
            
            if commit:
                conn.commit()
                return []
            
            try:
                results = cursor.fetchall()
                return results
            except:
                return []
    
    def execute_one(self, query: str, params: tuple = ()) -> Optional[Any]:
        """Execute a query and return first result."""
        results = self.execute(query, params)
        return results[0] if results else None
    
    def execute_write(self, query: str, params: tuple = ()) -> bool:
        """Execute a write query (INSERT, UPDATE, DELETE)."""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                # Convert ? placeholders to %s for PostgreSQL
                if self.use_postgres:
                    query = query.replace("?", "%s")
                
                cursor.execute(query, params)
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"Database write error: {e}")
            return False
    
    def table_exists(self, table_name: str) -> bool:
        """Check if a table exists."""
        if self.use_postgres:
            query = """
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = %s
                )
            """
            result = self.execute_one(query, (table_name,))
            return result[0] if result else False
        else:
            query = "SELECT name FROM sqlite_master WHERE type='table' AND name=?"
            result = self.execute_one(query, (table_name,))
            return result is not None


# =============================================================================
# MIGRATION HELPER
# =============================================================================

def migrate_sqlite_to_postgres(sqlite_path: str = "botdata.db"):
    """
    Migrate data from SQLite to PostgreSQL.
    Call this once when switching databases.
    """
    if not USE_POSTGRES or not POSTGRES_AVAILABLE:
        logger.warning("PostgreSQL not available, cannot migrate")
        return False
    
    try:
        # Connect to SQLite
        sqlite_conn = sqlite3.connect(sqlite_path)
        sqlite_conn.row_factory = sqlite3.Row
        sqlite_cursor = sqlite_conn.cursor()
        
        # Connect to PostgreSQL
        db_url = DATABASE_URL
        if db_url.startswith("postgres://"):
            db_url = db_url.replace("postgres://", "postgresql://", 1)
        
        pg_conn = psycopg2.connect(db_url)
        pg_cursor = pg_conn.cursor()
        
        # Migrate user_profiles
        logger.info("Migrating user_profiles...")
        sqlite_cursor.execute("SELECT * FROM user_profiles")
        profiles = sqlite_cursor.fetchall()
        
        for profile in profiles:
            try:
                pg_cursor.execute("""
                    INSERT INTO user_profiles 
                    (phone, name, congregation, email, preferred_currency, 
                     preferred_payment_method, total_usd, total_zwg, donation_count,
                     last_donation_date, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (phone) DO NOTHING
                """, tuple(profile))
            except Exception as e:
                logger.warning(f"Failed to migrate profile: {e}")
        
        # Migrate sessions
        logger.info("Migrating sessions...")
        try:
            sqlite_cursor.execute("SELECT * FROM sessions")
            sessions = sqlite_cursor.fetchall()
            for session in sessions:
                try:
                    pg_cursor.execute("""
                        INSERT INTO sessions (phone, step, data, created_at, updated_at)
                        VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT (phone) DO NOTHING
                    """, tuple(session))
                except:
                    pass
        except:
            logger.info("No sessions table to migrate")
        
        pg_conn.commit()
        pg_conn.close()
        sqlite_conn.close()
        
        logger.info("Migration completed successfully!")
        return True
        
    except Exception as e:
        logger.error(f"Migration failed: {e}")
        return False


# =============================================================================
# SINGLETON INSTANCE
# =============================================================================

# Global database instance
db = DatabaseConnection()

# Export info about current database
def get_database_info() -> dict:
    """Get information about current database configuration."""
    return {
        "type": "PostgreSQL" if db.use_postgres else "SQLite",
        "postgres_available": POSTGRES_AVAILABLE,
        "database_url_set": bool(DATABASE_URL),
        "pool_active": DatabaseConnection._pool is not None
    }
