from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

from .db.runtime import DatabaseRuntime
from .settings import get_settings
from .tasks.broker import broker as taskiq_broker

settings = get_settings()


def get_db_runtime(request: Request) -> DatabaseRuntime:
    return request.app.state.db_runtime


@asynccontextmanager
async def lifespan(app: FastAPI):
    db_runtime = DatabaseRuntime(settings.resolved_database_url)
    db_runtime.startup()
    await taskiq_broker.startup()
    app.state.db_runtime = db_runtime
    try:
        yield
    finally:
        await taskiq_broker.shutdown()
        db_runtime.shutdown()
