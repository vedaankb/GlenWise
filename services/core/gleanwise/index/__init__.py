# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Ved Buddaraju

from gleanwise.config import Settings
from gleanwise.index.base import Store
from gleanwise.index.sqlite import SQLiteStore


def open_store(settings: Settings) -> Store:
    """Pick the backend from configuration: Postgres when ``GLEANWISE_DATABASE_URL`` is set."""
    if settings.database_url:
        from gleanwise.index.postgres import PostgresStore

        return PostgresStore(settings.database_url)
    return SQLiteStore(settings.sqlite_path())


__all__ = ["SQLiteStore", "Store", "open_store"]
