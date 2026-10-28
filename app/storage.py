"""Transactional persistence with compare-and-swap revisions.

SQLite is for direct local use and tests; Docker supplies PostgreSQL. The SQL
contract is the same, including atomic revision updates and unique orders.
"""

import logging
import time
from contextlib import contextmanager
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

    @contextmanager
    def transaction(self, deadline=None):
        """Bound lock/statement waits and roll back work completed too late."""
        def check():
            if deadline is not None and time.monotonic() >= deadline:
                raise TimeoutError("Storage deadline reached")
        def set_wait_limit(connection):
            milliseconds = max(1, int((deadline - time.monotonic()) * 1000)) if deadline else 15000
            if connection.dialect.name == "sqlite":
                # SQLite's busy-handler sleeps can overshoot wall time on
                # Windows. Bounded HTTP writes fail immediately on contention;
                # they must never commit a detached update after the deadline.
                connection.exec_driver_sql(f"PRAGMA busy_timeout={0 if deadline else milliseconds}")
            elif deadline is not None and connection.dialect.name == "postgresql":
                connection.execute(text("SELECT set_config('statement_timeout', :value, true)"),
                                   {"value": str(milliseconds)})
        check()
        try:
            with self.engine.connect() as connection, connection.begin() as transaction:
                check()
                set_wait_limit(connection)
                yield connection
                check()
                # COMMIT can itself wait for SQLite readers. Recompute its
                # timeout after UPDATE/JSON work instead of reusing old slack.
                set_wait_limit(connection)
                try:
                    transaction.commit()
                except SQLAlchemyError:
                    # A failed DBAPI COMMIT can leave a native transaction open
                    # after SQLAlchemy marks its transaction inactive. Discard
                    # the connection so a later read cannot commit that write.
                    connection.invalidate()
                    raise
        except SQLAlchemyError as exc:
            locked = self.engine.dialect.name == "sqlite" and "locked" in str(exc.orig if hasattr(exc, "orig") else exc).lower()
            if deadline is not None and (locked or time.monotonic() >= deadline - .01):
                raise TimeoutError("Storage deadline reached") from exc
            raise

    def create(self, state: dict, *, deadline=None) -> None:
        with self.transaction(deadline) as connection:
            connection.execute(
                insert(sessions).values(id=state["id"], revision=state["revision"], payload=state)
            )

    def load(self, session_id: str, *, deadline=None) -> dict | None:
        with self.transaction(deadline) as connection:
            row = connection.execute(
                select(sessions.c.payload).where(sessions.c.id == session_id)
            ).first()
            return row[0] if row else None

    def save(self, state: dict, expected: int, order: dict | None = None, *, deadline=None) -> None:
        with self.transaction(deadline) as connection:
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
