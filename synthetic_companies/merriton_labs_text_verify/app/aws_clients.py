from dataclasses import dataclass, field
import boto3
from botocore.config import Config


@dataclass(frozen=True)
class ExplicitCredentials:
    access_key: str = field(repr=False)
    secret_key: str = field(repr=False)
    session_token: str = field(repr=False)


def make_aws_clients(region: str, credentials: ExplicitCredentials) -> tuple:
    """Explicit opt-in only. No credential-chain lookup, endpoint override or provisioning."""
    if region not in {"eu-west-1", "eu-central-1"}:
        raise ValueError("An explicitly reviewed EU region is required")
    if not all((credentials.access_key, credentials.secret_key, credentials.session_token)):
        raise ValueError("Explicit temporary credentials are required")
    session = boto3.Session(aws_access_key_id=credentials.access_key,
                            aws_secret_access_key=credentials.secret_key,
                            aws_session_token=credentials.session_token, region_name=region)
    config = Config(connect_timeout=2, read_timeout=8,
                    retries={"mode": "standard", "total_max_attempts": 1},
                    proxies={}, parameter_validation=True)
    return (session.client("sagemaker-runtime", config=config),
            session.client("sqs", config=config))
