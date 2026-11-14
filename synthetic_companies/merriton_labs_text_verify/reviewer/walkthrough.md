# External reviewer walkthrough

This file contains reviewer answers; it is not product middleware or a compliance scanner. Nothing returns a blanket compliance verdict. The machine-readable entry is [control-evidence.json](control-evidence.json). Its source statuses mean authored implementation, not executed proof. Tests below are written but unexecuted.

Start with [legal-baseline.json](../compliance/legal-baseline.json) and [applicability](../compliance/applicability.md). Confirm the 2026-07-27 consolidation incorporating 2026/1744 and 2026-11-14 assessment; do not replace it with original-law dates or wording. The official EUR-Lex retrieval limit is disclosed. Product purpose, not the “advisory” label, drives the high-risk/GPAI/generation assessment. No source-level legal certification is asserted.

Inspect the following paths as text. An independently authorized reviewer can later exercise the authored tests and browser flows, but that was not done during generation.

| Scenarios | Trace through source | Focused authored tests | Expected evidence |
| --- | --- | --- | --- |
| S01, S09 | `create_app.editor` → `editor.html` → `showNotice` / `renderResult`; `result_envelope` → `export_advice` | `test_notice_before_submission_and_direct_navigation`, `test_updated_notice_and_limitations_on_every_delivery` | Notice precedes enabled input; direct navigation, API, repeats, cached results, review/retry and export retain current notice and limitations. |
| S02 | `VerifyService.process` → language gate / `FakeClassifier.classify` → `normalize_output` | `test_abstention_has_no_score` | No score for low confidence or unsupported language; the latter does not call inference. |
| S03 | `VerifyService.submit` → `validate_use` before storing/sending any batch item | `test_purposes_rejected_before_any_side_effect`, `test_batch_validates_all_items_first` | All unsupported uses return 422, without inference or queued payloads. |
| S04, S06 | `Directory.resolve` → `VerifyService.authorize` / `checked_record`; `MemoryStorage.get`; policy checks precede cache | `test_tenant_isolation_across_delivery_and_mutation`, `test_cache_is_tenant_and_model_scoped`, `test_cache_does_not_bypass_current_policy` | Foreign ids fail 404, foreign jobs do nothing, caches differ by tenant/model, revocation is respected. |
| S05 | `Registry.require` at submission, worker and delivery | `test_model_compatibility_and_withdrawal`, `test_version_change_recomputes_and_response_mismatch_fails` | Domain mismatch/withdrawal returns 409, queued work fails without inference, changed versions recompute, wrong provider version fails. |
| S07 | `SageMakerClassifier.classify` → typed error → `VerifyService.fail`; `safe_error` | `test_provider_timeout_is_not_an_answer`, `test_sagemaker_contract_and_timeout_mapping` | Timeout yields failed state and null analysis; no fabricated result or raw exception leakage. |
| S08 | `VerifyService.delete` → `MemoryStorage.purge` / queue `cancel`; late job → `process` tombstone check | `test_deleted_work_cannot_be_recreated`, `test_deletion_erases_cache_features_and_fingerprint` | Raw/derived data removed, old id/retry/key is blocked, late duplicate cannot invoke inference. |
| S10 | `Onboarding.require` → `VerifyService.authorize` and `run_one` | `test_role_specific_onboarding_records_and_gate` | Materials/records match editor/admin/operator versions; missing acknowledgment blocks work as company policy. |

[scenarios.json](../fixtures/scenarios.json) gives every scenario's inputs, expected outputs, side effects, functions, classifications and test names. Fragment identifiers in evidence JSON (`#S01`, `#eval-1`) are logical keys in these JSON documents, not separate files or browser anchors. The supplied text examples, participation records, release approvals and evaluation counts are synthetic. Arithmetic is explicit: eval-1 has 20 scored plus 4 abstentions, with 8 TP/2 FP/8 TN/2 FN; eval-2 has 22 scored plus 2 abstentions, with 9 TP/2 FP/9 TN/2 FN. Denominators for precision/recall exclude abstentions; no universal accuracy is inferred.

Read [SDK assumptions](../docs/sdk-contract.md) beside `aws_clients.py`, `sagemaker.py` and `sqs.py`. Clients are constructed only by explicit factory invocation with provided credentials; no resources are created. SQS bodies are reference-only. Unseen remote references cannot be physically recalled, so tombstones invalidate them. The current store is intentionally process-local; remote adapters are not a complete distributed deployment. Real provider retention/deletion, queue settings and integration behavior need external verification.

Accessibility evidence is limited to source structure, labels, native controls, text states and preserved notices. No browser, keyboard or assistive-technology test was run. Literacy evidence is authored guidance and version-bound synthetic records, not attendance, comprehension or individual attainment proof. Other legislation, operational controls and legal advice remain outside this scoped source assessment.

No project code, tests, compilation, installations, services, or infrastructure provisioning were executed.
