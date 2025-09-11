"""
Database configuration and management for GitPhish.

This module provides database setup, session management, and utilities
for working with the GitPhish database.
"""

import os
import logging
from typing import Optional
from contextlib import contextmanager
from sqlalchemy import create_engine, event, inspect
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool
from gitphish.models.base import Base

logger = logging.getLogger(__name__)


class DatabaseManager:
    """Manages database connections and sessions for GitPhish."""

    def __init__(self, database_url: Optional[str] = None, echo: bool = False):
        """
        Initialize the database manager.

        Args:
            database_url: Database URL. If None, uses SQLite in data directory
            echo: Whether to echo SQL statements (for debugging)
        """
        if database_url is None:
            # Default to SQLite in the data directory
            data_dir = os.path.join(os.getcwd(), "data")
            os.makedirs(data_dir, exist_ok=True)
            database_url = f"sqlite:///{os.path.join(data_dir, 'gitphish.db')}"

        self.database_url = database_url
        self.echo = echo

        # Create engine with appropriate settings
        if database_url.startswith("sqlite"):
            # SQLite-specific configuration
            self.engine = create_engine(
                database_url,
                echo=echo,
                poolclass=StaticPool,
                connect_args={"check_same_thread": False, "timeout": 30},
            )

            # Enable foreign key constraints for SQLite
            @event.listens_for(self.engine, "connect")
            def set_sqlite_pragma(dbapi_connection, connection_record):
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.close()

        else:
            # For other databases (PostgreSQL, MySQL, etc.)
            self.engine = create_engine(database_url, echo=echo)

        # Create session factory
        self.SessionLocal = sessionmaker(
            autocommit=False, autoflush=False, bind=self.engine
        )

        logger.debug(f"Database manager initialized with URL: {database_url}")
        # Only create tables if they don't exist
        self.create_tables()

    def create_tables(self):
        """Create database tables if they don't already exist."""
        try:
            # Import all models to ensure they're registered with Base
            from gitphish.models.github_pages.deployment import (
                GitHubDeployment,  # noqa: F401
            )
            from gitphish.models.github.github_account import (
                DeployerGitHubAccount,  # noqa: F401
            )
            from gitphish.models.github.compromised_account import (
                CompromisedGitHubAccount,  # noqa: F401
            )
            from gitphish.models.sms.campaign import (
                SMSCampaign,  # noqa: F401
            )

            # Check if tables already exist by inspecting one of them
            inspector = inspect(self.engine)
            existing_tables = inspector.get_table_names()
            if "github_deployments" in existing_tables:
                logger.debug("Database tables already exist, skipping creation")
                return False  # Tables already exist
            # Create all tables
            Base.metadata.create_all(bind=self.engine)
            logger.debug("Database tables created successfully")
            return True  # Tables were created
        except Exception as e:
            logger.error(f"Failed to create database tables: {str(e)}")
            raise

    def get_session(self) -> Session:
        """Get a new database session."""
        return self.SessionLocal()

    @contextmanager
    def session_scope(self):
        """
        Provide a transactional scope around a series of operations.

        Usage:
            with db_manager.session_scope() as session:
                # Do database operations
                session.add(some_object)
                # Automatically commits on success, rolls back on exception
        """
        session = self.get_session()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def health_check(self) -> bool:
        """
        Check if the database is accessible.

        Returns:
            True if database is accessible, False otherwise
        """
        try:
            from sqlalchemy import text

            with self.session_scope() as session:
                session.execute(text("SELECT 1"))
            return True
        except Exception as e:
            logger.error(f"Database health check failed: {str(e)}")
            return False

    def reset_database(self) -> bool:
        """
        Reset the database by dropping and recreating all tables.

        WARNING: This will delete all data!

        Returns:
            True if reset successful, False otherwise
        """
        try:
            logger.warning("Resetting database - ALL DATA WILL BE LOST!")

            # Drop all tables
            Base.metadata.drop_all(bind=self.engine)
            logger.debug("Dropped all database tables")

            # Recreate tables
            self.create_tables()
            logger.debug("Recreated database tables")

            return True

        except Exception as e:
            logger.error(f"Failed to reset database: {str(e)}")
            return False


# Global database manager instance
_db_manager: Optional[DatabaseManager] = None


def initialize_database(
    database_url: Optional[str] = None, echo: bool = False
) -> DatabaseManager:
    """
    Initialize the global database manager.

    Args:
        database_url: Database URL. If None, uses default SQLite
        echo: Whether to echo SQL statements

    Returns:
        DatabaseManager instance
    """
    global _db_manager
    _db_manager = DatabaseManager(database_url=database_url, echo=echo)
    return _db_manager


def get_database_manager() -> DatabaseManager:
    """
    Get the global database manager instance.

    Returns:
        DatabaseManager instance

    Raises:
        RuntimeError: If database has not been initialized
    """
    global _db_manager
    if _db_manager is None:
        # Auto-initialize with defaults if not already done
        _db_manager = initialize_database()
    return _db_manager


def get_db_session() -> Session:
    """
    Get a new database session from the global manager.

    Returns:
        SQLAlchemy Session instance
    """
    return get_database_manager().get_session()


@contextmanager
def db_session_scope():
    """
    Provide a transactional scope around a series of operations using the global manager.

    Usage:
        with db_session_scope() as session:
            # Do database operations
            session.add(some_object)
            # Automatically commits on success, rolls back on exception
    """
    db_manager = get_database_manager()
    with db_manager.session_scope() as session:
        yield session
