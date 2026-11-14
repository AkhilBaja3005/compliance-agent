from dataclasses import dataclass
from .errors import ProductError


@dataclass(frozen=True)
class Model:
    version: str
    domains: tuple[str, ...]
    languages: tuple[str, ...]
    limitations: tuple[str, ...]
    evaluation_id: str


@dataclass(frozen=True)
class Approval:
    model_version: str
    evaluation_id: str
    approved_at: str
    owner: str
    synthetic: bool = True


class Registry:
    def __init__(self):
        common = ("A score is not proof of AI authorship or evidence about a person.",
                  "False positives and false negatives occur; edited and translated text may mislead.")
        self.models = {
            "dtv-1.0": Model("dtv-1.0", ("marketing",), ("en",),
                             common + ("English marketing drafts only; short or formulaic prose is unreliable.",), "eval-1"),
            "dtv-1.1": Model("dtv-1.1", ("marketing", "business_article"), ("en",),
                             common + ("English business prose only; quotations and mixed authorship are unreliable.",), "eval-2"),
        }
        self.approvals = {v: Approval(v, m.evaluation_id, "2026-08-25T09:00:00Z" if v == "dtv-1.0"
                                     else "2026-11-10T09:00:00Z", "synthetic-release-owner")
                          for v, m in self.models.items()}
        self.withdrawn: set[str] = set()

    def require(self, version: str, domain: str) -> Model:
        model = self.models.get(version)
        approval = self.approvals.get(version)
        if (not model or domain not in model.domains or version in self.withdrawn
                or not approval or approval.model_version != version
                or approval.evaluation_id != model.evaluation_id):
            raise ProductError("model_unavailable", 409)
        return model
