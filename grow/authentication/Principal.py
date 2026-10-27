from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class Principal:
    role: Literal["admin", "viewer", "pipeline", "curator"]
    email: str | None
    sub: str | None
