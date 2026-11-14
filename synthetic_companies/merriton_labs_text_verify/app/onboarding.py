from .domain import Principal
from .errors import ProductError

MATERIAL_VERSIONS = {"editor": "editors-2", "admin": "admins-2", "operator": "operators-2"}


class Onboarding:
    """Voluntary access gate using explicitly synthetic participation records."""

    def __init__(self, records: list[dict]):
        self.records = records

    def require(self, principal: Principal) -> None:
        if not any(r["subject"] == principal.subject and r["tenant"] == principal.tenant
                   and r["role"] == principal.role and r["synthetic"] is True
                   and r["material_version"] == MATERIAL_VERSIONS.get(principal.role)
                   for r in self.records):
            raise ProductError("forbidden", 403)
