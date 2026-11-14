"""Data scanning: classification without retaining values, DATA-01..05 checks, fairness from outcomes, live metadata sources."""
from __future__ import annotations

import csv
from pathlib import Path

from src.edge_extractors.data_scanner import (MongoSchemaSource, SqlInformationSchemaSource, UnityCatalogSource, classify_column,
                                              compute_fairness, scan_data)

DATA = Path(__file__).parent / "fixtures" / "data"


def test_classification_by_name_and_value_without_keeping_values():
    c = classify_column("contact", ["a@b.com", "c@d.org", "e@f.net"])
    assert "pii" in c.classes and "email_value" in c.tags and c.distinct_bucket == "2-10"
    assert "a@b.com" not in repr(c)
    assert "special_category" in classify_column("diagnosis_code").classes
    assert "biometric" in classify_column("face_embedding").tags
    assert not classify_column("amount").classes


def test_scan_data_retains_no_raw_values():
    assets = scan_data(DATA / "bad", "t")
    blob = repr(assets)
    assert "user1@example.com" not in blob and "asthma" not in blob
    csv_asset = next(a for a in assets if a.kind == "csv")
    assert csv_asset.rows == 200 and {c.name for c in csv_asset.columns if c.classes} == {"email", "diagnosis", "gender", "age"}


def test_parquet_and_jsonl_and_dbt_and_proto(tmp_path):
    import pyarrow as pa
    import pyarrow.parquet as pq
    pq.write_table(pa.table({"full_name": ["Ann", "Bob"], "score": [1, 2]}), tmp_path / "t.parquet")
    (tmp_path / "e.jsonl").write_text('{"email": "x@y.com", "n": 1}\n{"email": "z@y.com", "n": 2}\n')
    (tmp_path / "schema.yml").write_text("models:\n  - name: patients\n    columns:\n      - name: nhs_number\n      - name: visit_date\n")
    (tmp_path / "m.proto").write_text("message Face { bytes face_embedding = 1; string label = 2; }")
    kinds = {a.kind: a for a in scan_data(tmp_path, "t")}
    assert kinds["parquet"].rows == 2 and "pii" in kinds["parquet"].columns[0].classes
    assert "email_value" in kinds["jsonl"].columns[0].tags
    assert "pii" in kinds["dbt"].columns[0].classes
    assert "biometric" in kinds["protobuf"].columns[0].tags


def _checks(path, monkeypatch):
    from src.agents import run_audit
    monkeypatch.setenv("GRAPHITE_FRAMEWORKS", "EU_AI_ACT")
    rep = run_audit(path, "d")
    return {f.check_id: f for f in rep.all_findings()}, rep


def test_data_checks_bad_dataset(monkeypatch):
    f, rep = _checks(DATA / "bad", monkeypatch)
    assert f["DATA-02"].status == "SUSPECTED_GAP" and f["DATA-01"].status == "SUSPECTED_GAP"
    assert f["DATA-03"].status == "CONFIRMED_VIOLATION"  # CC-BY-NC data card
    assert f["DATA-05"].status == "CONFIRMED_VIOLATION" and f["DATA-05"].severity == "Critical"  # scraped faces
    assert any(e.source_type == "data_asset" for e in f["DATA-05"].evidence)
    assert rep.fairness_metrics["status"] == "FLAGGED"
    assert {m["group"] for m in rep.fairness_metrics["metrics"] if m.get("flag")} == {"F", "50+"}


def test_data_checks_clean_dataset(monkeypatch):
    f, rep = _checks(DATA / "clean", monkeypatch)
    assert f["DATA-03"].status == "PASS" and f["DATA-05"].status == "PASS" and f["DATA-04"].status == "PASS"
    assert rep.fairness_metrics.get("metrics") in (None, [])


def test_checks_not_applicable_without_data(monkeypatch):
    from src.agents import run_audit
    rep = run_audit(Path(__file__).parent / "fixtures" / "langs" / "go" / "clean", "g")
    assert not any((f.check_id or "").startswith("DATA-") for f in rep.all_findings())


def test_fairness_small_groups_are_not_rated_and_no_file_means_none(tmp_path):
    assert compute_fairness(tmp_path) is None  # never invents numbers
    with (tmp_path / "decisions.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["gender", "outcome"])
        w.writerows([["F", "yes"]] * 5 + [["M", "yes"]] * 40)
    m = {x["group"]: x for x in compute_fairness(tmp_path)["metrics"]}
    assert m["F"]["selection_rate"] is None and m["F"]["note"] == "n < 30" and m["M"]["ratio_vs_top"] == 1.0


def test_live_metadata_sources_with_fakes():
    class Cur:
        def execute(self, *a): pass
        def fetchall(self): return [("patients", "nhs_number", "text"), ("patients", "visit", "date")]
    class Conn:
        def cursor(self): return Cur()
        def close(self): pass
    a = SqlInformationSchemaSource(lambda: Conn(), region="us-east-1").describe()
    assert a[0].path == "sql://public/patients" and a[0].region == "us-east-1" and a[0].columns[0].classes == ["pii"]

    class Col:
        def __init__(self, n): self.name, self.type_text = n, "string"
    class Tbl:
        name, columns, properties = "faces", [Col("face_embedding")], {"region": "eu-west-1", "retention": "30d"}
    class W:
        class tables:
            @staticmethod
            def list(**kw): return [Tbl()]
    u = UnityCatalogSource(W(), "cat", "sch").describe()
    assert u[0].path == "uc://cat.sch.faces" and u[0].meta["retention"] == "30d"

    class Coll:
        def find(self, q, limit=0): return [{"_id": 1, "email": "a@b.com", "n": 1}]
    class Db:
        def __getitem__(self, k): return Coll()
        def list_collection_names(self): return ["users"]
    m = MongoSchemaSource(Db()).describe()
    assert "pii" in [c for c in m[0].columns if c.name == "email"][0].classes and "a@b.com" not in repr(m)
