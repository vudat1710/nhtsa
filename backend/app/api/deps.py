"""Shared dependencies, one per process. Routes call them through this module (deps.con()), so tests can swap them."""
from functools import lru_cache

from app.ai.clients import LlmSetup, setup_from_settings
from app.config import get_settings
from app.data import queries
from app.store.results import Store


@lru_cache
def con():
    return queries.connect(get_settings().db_path)


@lru_cache
def llm() -> LlmSetup | None:
    return setup_from_settings(get_settings())


@lru_cache
def store() -> Store:
    return Store(get_settings().app_db_path)
