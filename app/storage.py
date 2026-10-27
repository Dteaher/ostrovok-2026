"""Transactional persistence with compare-and-swap revisions.

SQLite is for direct local use and tests; Docker supplies PostgreSQL. The SQL
contract is the same, including atomic revision updates and unique orders.
"""

import logging
from pathlib import Path

from sqlalchemy import (
    JSON,
    Column,
    Integer,
    MetaData,
    String,
    Table,
    create_engine,
    insert,
    select,
    text,
    update,
)
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)
metadata = MetaData()
sessions = Table(
    "travel_sessions",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("revision", Integer, nullable=False),
    Column("payload", JSON, nullable=False),
)
orders = Table(
    "demo_orders",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("session_id", String(64), unique=True, nullable=False),
    Column("payload", JSON, nullable=False),
)


class StaleRevision(Exception):
    pass


class Database:
    def __init__(self, url: str):
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql+psycopg://", 1)
        elif url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+psycopg://", 1)
        if url.startswith("sqlite:///"):
            filename = url[len("sqlite:///") :]
            if filename != ":memory:":
                Path(filename).parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(
            url,
            pool_pre_ping=True,
            connect_args={"check_same_thread": False, "timeout": 15}
            if url.startswith("sqlite")
            else {},
        )

    def initialize(self) -> None:
        metadata.create_all(self.engine)
        logger.info("Database schema ready; catalog seeded from versioned application data")

    def health(self) -> bool:
        try:
            with self.engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            return True
        except SQLAlchemyError:
            logger.warning("Database readiness check failed")
            return False

    def create(self, state: dict) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                insert(sessions).values(id=state["id"], revision=state["revision"], payload=state)
            )

    def load(self, session_id: str) -> dict | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                select(sessions.c.payload).where(sessions.c.id == session_id)
            ).first()
            return row[0] if row else None

    def save(self, state: dict, expected: int, order: dict | None = None) -> None:
        with self.engine.begin() as connection:
            changed = connection.execute(
                update(sessions)
                .where(sessions.c.id == state["id"], sessions.c.revision == expected)
                .values(revision=state["revision"], payload=state)
            )
            if changed.rowcount != 1:
                raise StaleRevision
            if order:
                connection.execute(
                    insert(orders).values(id=order["id"], session_id=state["id"], payload=order)
                )

    def close(self) -> None:
        self.engine.dispose()
