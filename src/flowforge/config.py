"""Application settings."""

import os
from dataclasses import dataclass

DEFAULT_DATABASE_URL = "postgresql://flowforge:flowforge_dev_password@localhost:5432/flowforge"


@dataclass(frozen=True, slots=True)
class Settings:
    database_url: str = DEFAULT_DATABASE_URL

    @classmethod
    def from_environment(cls) -> "Settings":
        return cls(database_url=os.getenv("FLOWFORGE_DATABASE_URL", DEFAULT_DATABASE_URL))
