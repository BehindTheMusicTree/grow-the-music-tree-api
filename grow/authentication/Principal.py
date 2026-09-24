from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class Principal:
    role: Literal["admin", "viewer", "pipeline"]
    email: str | None
    sub: str | None
