from .service import VerifyService


def run_one(service: VerifyService, operator_subject: str = "synthetic-operator") -> bool:
    """One explicit delivery, not a daemon or background thread."""
    with service.storage.lock:
        service.authorize(service.directory.current(operator_subject), "operator")
        delivery = service.jobs.receive()
        if delivery is None:
            return False
        receipt, job = delivery
        service.process(job)
        service.jobs.ack(receipt)
        return True
