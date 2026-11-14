from dataclasses import dataclass


@dataclass(frozen=True)
class Notice:
    version: str
    text: str


class Notices:
    def __init__(self):
        self.history = {
            "notice-1": Notice("notice-1", "You are interacting with an AI text classifier. Results are editorial advice."),
            "notice-2": Notice("notice-2", "You are interacting with an AI text classifier. It estimates patterns in business drafts; it does not identify authors. Scores can be wrong and are not proof of AI authorship. Use independent editorial judgment; never use results to assess or sanction people."),
        }
        self.active = "notice-2"

    def current(self) -> dict:
        notice = self.history[self.active]
        return {"version": notice.version, "text": notice.text}
