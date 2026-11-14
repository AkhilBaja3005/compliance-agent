import json
from typing import Protocol, Any
from uuid import UUID
from botocore.exceptions import BotoCoreError, ClientError
from .domain import Job
from .errors import ProductError


class QueueClient(Protocol):
    def send_message(self, **kwargs: Any) -> dict: ...
    def receive_message(self, **kwargs: Any) -> dict: ...
    def delete_message(self, **kwargs: Any) -> dict: ...


class SqsQueue:
    """Existing standard queue. Bodies contain references only, never submitted text."""
    def __init__(self, client: QueueClient, queue_url: str):
        if not queue_url.startswith("https://sqs."):
            raise ValueError("An existing HTTPS SQS queue URL is required")
        self.client = client
        self.queue_url = queue_url

    def send(self, job: Job) -> None:
        try:
            self.client.send_message(QueueUrl=self.queue_url, MessageBody=json.dumps({
                "tenant": job.tenant, "submission_id": job.submission_id, "attempt": job.attempt}))
        except (BotoCoreError, ClientError):
            raise ProductError("queue_unavailable", 503) from None

    def receive(self) -> tuple[str, Job] | None:
        try:
            response = self.client.receive_message(QueueUrl=self.queue_url, MaxNumberOfMessages=1,
                                                   WaitTimeSeconds=0, VisibilityTimeout=30)
            messages = response.get("Messages", [])
            if not messages:
                return None
            message = messages[0]
            try:
                data = json.loads(message["Body"])
                if set(data) != {"tenant", "submission_id", "attempt"}:
                    raise ValueError("Invalid reference")
                if data["tenant"] not in {"atlas", "birch"} or type(data["attempt"]) is not int:
                    raise ValueError("Invalid reference")
                if not 1 <= data["attempt"] <= 3:
                    raise ValueError("Invalid attempt")
                UUID(data["submission_id"])
                return message["ReceiptHandle"], Job(**data)
            except (ValueError, KeyError, TypeError, AttributeError):
                self.ack(message["ReceiptHandle"])  # Poison reference; never log its body.
                return None
        except (BotoCoreError, ClientError):
            raise ProductError("queue_unavailable", 503) from None

    def ack(self, receipt: str) -> None:
        try:
            self.client.delete_message(QueueUrl=self.queue_url, ReceiptHandle=receipt)
        except (BotoCoreError, ClientError):
            raise ProductError("queue_unavailable", 503) from None

    def cancel(self, tenant: str, submission_id: str) -> None:
        # SQS cannot delete unseen messages by content. They hold only opaque references.
        # The repository tombstone makes every leased/unseen/duplicate reference non-executable.
        # Physical reference expiry is an external queue-retention configuration assumption.
        return None
