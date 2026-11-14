# Managed adapters and unverified integration assumptions

Official documentation consulted read-only on 2026-11-14:

- [boto3 SageMaker Runtime invoke_endpoint](https://docs.aws.amazon.com/boto3/latest/reference/services/sagemaker-runtime/client/invoke_endpoint.html): request body and content negotiation, streaming response, endpoint-specific routing.
- [boto3 SQS send_message](https://docs.aws.amazon.com/boto3/latest/reference/services/sqs/client/send_message.html), [receive_message](https://docs.aws.amazon.com/boto3/latest/reference/services/sqs/client/receive_message.html), [delete_message](https://docs.aws.amazon.com/boto3/latest/reference/services/sqs/client/delete_message.html): reference transport, receipt handles and acknowledgement.
- [botocore Config](https://docs.aws.amazon.com/botocore/latest/reference/config.html): socket timeouts and total attempt limits.

`make_aws_clients` is an explicit factory requiring nonempty temporary credential fields and a reviewed EU region. It does not read credentials from the environment or use an implicit discovery chain. Credentials are excluded from dataclass repr. Clients have a 2-second connection timeout, 8-second socket read timeout and `total_max_attempts=1` (one initial attempt). These are socket limits, not a promised overall wall-clock deadline. No clients are constructed on import. No calls were made. Dependency bounds are not a tested compatibility matrix or security audit.

The hypothetical endpoint must already exist and serve an immutable version of a specialised classifier. An explicit model-version-to-endpoint map supplies `EndpointName`; no weighted routing or generic LLM is assumed. The request uses JSON bytes with `contract_version`, `text`, `language`, `domain` and `model_version`. The endpoint must return `ContentType: application/json` and at most 8,192 response bytes, with this contract:

```json
{"model_version":"dtv-1.1","state":"scored","score":0.68,"confidence":0.76,"reason":"classified"}
```

An abstention has `state: abstained`, `score: null`, `reason: low_confidence` or `unsupported_language`, the matching version and a numeric confidence. Scores and confidence must be finite numbers in [0,1]. Extra fields are rejected. A scored response needs a score and `classified` reason. A low confidence scored response is converted to an abstention under company policy. Invalid JSON, invalid shape, version mismatch and wrong MIME type are contract failures. Timeout exceptions map to `provider_timeout`; SDK/transport failures map to `provider_unavailable`. Streaming bodies are closed. No successful result is fabricated and no fake is substituted after live failure.

The SQS adapter accepts an injected client and existing HTTPS queue URL. `send_message` contains only a tenant/id/attempt reference. `receive_message` requests one message with zero long-poll wait and a 30-second visibility timeout. `ack` uses its receipt handle. Poison references are acknowledged without logging their bodies. Standard queues can duplicate deliveries; repository state/attempt checks make processing idempotent. SQS cannot remove unseen messages by submission id; invalidation is logical through tombstones, followed by physical provider expiry. Queue errors are typed `queue_unavailable` failures. The queue is not a second payload store.

To exercise adapters later, a separately authorized integrator would construct explicit clients, inject `SageMakerClassifier` and `SqsQueue` into `build_service`, supply reviewed directory/onboarding inputs and create the app with `local_sessions=False`. The same process must consume jobs against its injected store; no distributed storage implementation is provided. Local account selection and local work HTTP endpoints are absent when that flag is false. No environment toggle activates live behavior.

Unverified assumptions: endpoint existence, actual model immutability, claimed confidence semantics, representative performance, response contract support, SDK installation/resolution, IAM permission scope, EU data location, endpoint capture/logging disabled, provider retention/deletion arrangements, HTTPS deployment, queue access policy, queue retention and visibility adequate for measured latency, and durable storage before any production use. SDK data-plane mapping is authored source, not a verified integration. There are no create/deploy/provision methods in these adapters.
