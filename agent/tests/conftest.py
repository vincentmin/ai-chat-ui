from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel

os.environ.setdefault('OPENAI_API_KEY', 'test-key')

from chatbot.chat_router import create_chat_router
from chatbot.db.runtime import DatabaseRuntime


@pytest.fixture
def db_runtime(tmp_path: Path):
    db_path = tmp_path / 'chatbot-test.db'
    runtime = DatabaseRuntime(f'sqlite:///{db_path}')
    runtime.startup()
    try:
        yield runtime
    finally:
        runtime.shutdown()


@pytest.fixture
def client(db_runtime: DatabaseRuntime):
    app = FastAPI()
    app.state.db_runtime = db_runtime

    test_model = TestModel()
    agent = Agent(model=test_model, instructions='Test agent')

    app.include_router(
        create_chat_router(
            agent=agent,
            models={'Default': test_model},
            agent_key='sql',
        ),
        prefix='/api',
    )

    with TestClient(app) as test_client:
        yield test_client
