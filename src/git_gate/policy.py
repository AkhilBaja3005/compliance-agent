"""Administrator-owned configuration; independent of audit imports."""
from __future__ import annotations

import hashlib
import json
import re
import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path

SUPPORTED_CHECKS = frozenset({"PII-01", "HITL-01"})


@dataclass(frozen=True)
class Policy:
    repository: str
    tenant_id: str
    company_name: str
    sector: str
    blocking_checks: tuple[str, ...] = ("PII-01", "HITL-01")
    commercial: bool = True
    timeout_seconds: int = 60

    @classmethod
    def load(cls, path: Path) -> "Policy":
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
        required = {"repository", "tenant_id", "company_name", "sector"}
        allowed = set(cls.__dataclass_fields__)
        if not required <= raw.keys() or raw.keys() - allowed:
            raise ValueError("Policy has missing or unknown fields")
        for key in required:
            if not isinstance(raw[key], str) or not raw[key].strip():
                raise ValueError(f"Policy {key} must be a nonempty string")
        if not Path(raw["repository"]).is_absolute():
            raise ValueError("Policy repository must be an absolute path")
        if not re.fullmatch(r"[a-zA-Z0-9_-]+", raw["tenant_id"]):
            raise ValueError("Invalid policy tenant_id")
        checks = raw.get("blocking_checks", sorted(SUPPORTED_CHECKS))
        if not isinstance(checks, list) or not checks or any(not isinstance(c, str) or c not in SUPPORTED_CHECKS for c in checks):
            raise ValueError("blocking_checks must select PII-01 and/or HITL-01")
        timeout = raw.get("timeout_seconds", 60)
        if type(timeout) is not int or not 1 <= timeout <= 600:
            raise ValueError("timeout_seconds must be an integer between 1 and 600")
        if type(raw.get("commercial", True)) is not bool:
            raise ValueError("commercial must be boolean")
        raw["blocking_checks"] = tuple(sorted(set(checks)))
        return cls(**raw)

    @property
    def checksum(self) -> str:
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True).encode()).hexdigest()
