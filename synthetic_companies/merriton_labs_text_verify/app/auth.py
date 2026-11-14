import secrets
from .domain import Principal
from .errors import ProductError


class Directory:
    """Trusted session resolver. Never derives identity or tenant from request payloads."""

    def __init__(self, principals: list[Principal]):
        self.people = {p.subject: p for p in principals}
        self.sessions: dict[str, str] = {}

    def issue_local(self, subject: str) -> str:
        if subject not in self.people:
            raise ProductError("unauthorized", 401)
        token = secrets.token_urlsafe(32)
        self.sessions[token] = subject
        return token

    def resolve(self, token: str | None) -> Principal:
        subject = self.sessions.get(token or "")
        if subject not in self.people:
            raise ProductError("unauthorized", 401)
        return self.people[subject]

    def current(self, subject: str) -> Principal:
        if subject not in self.people:
            raise ProductError("forbidden", 403)
        return self.people[subject]


def require_role(principal: Principal, *roles: str) -> None:
    if principal.role not in roles:
        raise ProductError("forbidden", 403)
