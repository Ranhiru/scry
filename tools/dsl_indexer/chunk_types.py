from dataclasses import dataclass, asdict
from typing import Any, Dict


@dataclass
class Chunk:
    chunk_id: str
    repo: str
    repo_type: str
    path: str
    section: str
    line_start: int
    line_end: int
    content: str
    tokens_est: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

