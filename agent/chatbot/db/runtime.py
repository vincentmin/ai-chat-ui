from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine


class DatabaseRuntime:
    """Owns SQLModel engine/session lifecycle for API runtime."""

    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self.engine: Engine | None = None

    def startup(self) -> None:
        # Ensure model classes are imported before metadata.create_all().
        from .models import AgentRunSnapshot  # noqa: F401

        if self.database_url.startswith('sqlite:///'):
            db_path = self.database_url.removeprefix('sqlite:///')
            if db_path and db_path != ':memory:':
                Path(db_path).parent.mkdir(parents=True, exist_ok=True)

        connect_args = (
            {'check_same_thread': False}
            if self.database_url.startswith('sqlite')
            else {}
        )
        self.engine = create_engine(self.database_url, connect_args=connect_args)
        SQLModel.metadata.create_all(self.engine)

    def shutdown(self) -> None:
        if self.engine is not None:
            self.engine.dispose()
            self.engine = None

    @contextmanager
    def session(self) -> Iterator[Session]:
        if self.engine is None:
            raise RuntimeError('DatabaseRuntime is not started')

        with Session(self.engine) as session:
            yield session
