"""Data scanning: schemas, manifests and live-store metadata -> DataAsset facts. Privacy rule: raw values are never kept.

What is retained per asset: name, kind, column names/types, row count, null rates, distinct-count buckets, PII / special-category /
protected-attribute classification with confidence, and sha256 of the schema. Values are inspected in memory on a small bounded
sample only to classify a column (e.g. "looks like an email"), then discarded. Nothing is written to logs, MongoDB, Delta, the LLM
prompt or the report beyond column names and aggregate counts.
"""
from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from src.schemas.artifacts import sha256_text

from .code_scanner import SKIP_DIRS

SAMPLE_ROWS = 200

# --------------------------------------------------------------------------- column classification
NAME_RULES: list[tuple[str, str, re.Pattern]] = [  # (class, tag, regex on normalised column name)
    ("pii", "direct_identifier", re.compile(r"\b(name|full name|first name|last name|surname|email|e mail|phone|mobile|address|postcode|zip|dob|date of birth|birth|ssn|national insurance|ni number|nhs number|passport|driver licen[cs]e|iban|account number|ip address|customer id|user id|patient id)\b")),
    ("special_category", "health", re.compile(r"\b(diagnos\w*|icd|medication|condition|disease|disabilit\w*|patient|clinical|health|blood|allerg\w*|treatment)\b")),
    ("special_category", "biometric", re.compile(r"\b(face|facial|faceprint|fingerprint|iris|voiceprint|biometric\w*|gait|face embedding)\b")),
    ("special_category", "ethnicity", re.compile(r"\b(ethnic\w*|race|racial|nationality origin)\b")),
    ("special_category", "religion_politics", re.compile(r"\b(religio\w*|belief|political\w*|trade union|union member\w*)\b")),
    ("special_category", "sexuality_genetic", re.compile(r"\b(sexual orientation|sex life|genetic\w*|dna)\b")),
    ("pii", "location", re.compile(r"\b(latitude|longitude|gps|geo ?location|location history)\b")),
    ("protected_attribute", "sex_gender", re.compile(r"\b(sex|gender)\b")),
    ("protected_attribute", "age", re.compile(r"\b(age|age band|age group|birth year)\b")),
    ("protected_attribute", "disability", re.compile(r"\b(disabled|disability)\b")),
]
VALUE_RULES: list[tuple[str, str, re.Pattern]] = [
    ("pii", "email_value", re.compile(r"^[\w.+-]+@[\w-]+\.[\w.-]+$")),
    ("pii", "phone_value", re.compile(r"^\+?[\d\s().-]{9,16}$")),
    ("pii", "iban_value", re.compile(r"^[A-Z]{2}\d{2}[A-Z0-9]{10,30}$")),
    ("pii", "uk_ni_value", re.compile(r"^[A-CEGHJ-PR-TW-Z]{2}\d{6}[A-D]$")),
    ("pii", "us_ssn_value", re.compile(r"^\d{3}-\d{2}-\d{4}$")),
]


def _norm(name: str) -> str:
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", name)
    return re.sub(r"[_\-./]+", " ", s).lower().strip()


def _luhn(digits: str) -> bool:
    ds = [int(c) for c in digits][::-1]
    return len(ds) >= 13 and sum(d if i % 2 == 0 else (d * 2 - 9 if d * 2 > 9 else d * 2) for i, d in enumerate(ds)) % 10 == 0


@dataclass
class ColumnFact:
    name: str
    dtype: str = ""
    classes: list[str] = field(default_factory=list)  # pii | special_category | protected_attribute
    tags: list[str] = field(default_factory=list)
    confidence: float = 0.0
    null_rate: float | None = None
    distinct_bucket: str | None = None  # "1", "2-10", "11-100", ">100": never the values themselves
    needs_review: bool = False


@dataclass
class DataAsset:
    asset_id: str
    tenant_id: str
    kind: str  # csv | parquet | jsonl | ddl | json_schema | avro | protobuf | dbt | mongo | sql_table | uc_table | data_card | dvc
    path: str
    columns: list[ColumnFact] = field(default_factory=list)
    rows: int | None = None
    region: str | None = None
    license: str | None = None
    meta: dict = field(default_factory=dict)  # provenance keys only: source, collection, consent, retention, lineage, opt_out
    sha256_hash: str = ""

    @property
    def locator(self) -> str:
        return f"{self.path}:1-1"

    def has(self, cls: str) -> list[ColumnFact]:
        return [c for c in self.columns if cls in c.classes]


def classify_column(name: str, values: list | None = None) -> ColumnFact:
    col = ColumnFact(name=name)
    n = _norm(name)
    for cls, tag, rx in NAME_RULES:
        if rx.search(n):
            col.classes.append(cls)
            col.tags.append(tag)
            col.confidence = max(col.confidence, 0.85)
    if values:
        vs = [str(v).strip() for v in values if v not in (None, "")]
        if vs:
            for cls, tag, rx in VALUE_RULES:
                hit = sum(1 for v in vs if rx.match(v)) / len(vs)
                if hit >= 0.6:
                    col.classes.append(cls)
                    col.tags.append(tag)
                    col.confidence = max(col.confidence, round(0.6 + 0.4 * hit, 2))
            if sum(1 for v in vs if re.fullmatch(r"[\d -]{13,19}", v) and _luhn(re.sub(r"\D", "", v))) / len(vs) >= 0.6:
                col.classes.append("pii")
                col.tags.append("card_number_value")
                col.confidence = max(col.confidence, 0.95)
            d = len(set(vs))
            col.distinct_bucket = "1" if d == 1 else "2-10" if d <= 10 else "11-100" if d <= 100 else ">100"
            col.null_rate = round(1 - len(vs) / max(1, len(values)), 3)
    col.classes = sorted(set(col.classes))
    col.tags = sorted(set(col.tags))
    # value-only evidence (name looked innocent) is weaker: route to human review
    col.needs_review = bool(col.classes) and col.confidence < 0.7
    return col


def _asset(tenant: str, kind: str, rel: str, cols: list[ColumnFact], rows: int | None = None, **kw) -> DataAsset:
    sig = rel + "|" + ",".join(f"{c.name}:{c.dtype}" for c in cols)
    return DataAsset(asset_id=f"data-{sha256_text(f'{tenant}:{rel}')[:12]}", tenant_id=tenant, kind=kind, path=rel, columns=cols, rows=rows,
                     sha256_hash=sha256_text(sig), **kw)


# --------------------------------------------------------------------------- file readers
def _csv_asset(path: Path, rel: str, tenant: str) -> DataAsset | None:
    delim = "\t" if path.suffix.lower() == ".tsv" else ","
    with path.open("r", encoding="utf-8", errors="replace", newline="") as fh:
        rd = csv.reader(fh, delimiter=delim)
        header = next(rd, None)
        if not header:
            return None
        sample, n = [], 0
        for row in rd:
            n += 1
            if len(sample) < SAMPLE_ROWS:
                sample.append(row)
    cols = [classify_column(h, [r[i] if i < len(r) else None for r in sample]) for i, h in enumerate(header)]
    del sample  # values discarded
    return _asset(tenant, "csv", rel, cols, n)


def _parquet_asset(path: Path, rel: str, tenant: str) -> DataAsset | None:
    import pyarrow.parquet as pq

    pf = pq.ParquetFile(str(path))
    names = pf.schema_arrow.names
    sample = {}
    if pf.num_row_groups:
        tbl = pf.read_row_group(0, columns=names).slice(0, SAMPLE_ROWS)
        sample = {c: tbl.column(c).to_pylist() for c in names}
    cols = []
    for f in pf.schema_arrow:
        c = classify_column(f.name, sample.get(f.name))
        c.dtype = str(f.type)
        cols.append(c)
    return _asset(tenant, "parquet", rel, cols, pf.metadata.num_rows)


def _jsonl_asset(path: Path, rel: str, tenant: str) -> DataAsset | None:
    keys: dict[str, list] = {}
    n = 0
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            n += 1
            if n <= SAMPLE_ROWS:
                try:
                    obj = json.loads(line)
                except ValueError:
                    continue
                if isinstance(obj, dict):
                    for k, v in obj.items():
                        keys.setdefault(k, []).append(v if not isinstance(v, (dict, list)) else None)
    if not keys:
        return None
    return _asset(tenant, "jsonl", rel, [classify_column(k, v) for k, v in keys.items()], n)


_DDL_TABLE = re.compile(r"create\s+table\s+(?:if\s+not\s+exists\s+)?([\w.\"`\[\]]+)\s*\((.*?)\)\s*;", re.I | re.S)
_DDL_COL = re.compile(r"^\s*[\"`\[]?(\w+)[\"`\]]?\s+([A-Za-z]+(?:\([^)]*\))?)", re.M)


def _ddl_assets(text: str, rel: str, tenant: str) -> list[DataAsset]:
    out = []
    for m in _DDL_TABLE.finditer(text):
        cols = []
        depth, buf, parts = 0, "", []
        for ch in m.group(2):  # split on top-level commas only (types like DECIMAL(10,2) keep theirs)
            depth += ch == "("
            depth -= ch == ")"
            if ch == "," and depth == 0:
                parts.append(buf)
                buf = ""
            else:
                buf += ch
        parts.append(buf)
        for part in parts:
            cm = _DDL_COL.match(part.strip())
            if not cm or cm.group(1).lower() in {"primary", "foreign", "constraint", "unique", "key", "index", "check"}:
                continue
            c = classify_column(cm.group(1))
            c.dtype = cm.group(2)
            cols.append(c)
        out.append(_asset(tenant, "ddl", f"{rel}#{m.group(1).strip(chr(34) + '`[]')}", cols))
    return out


def _json_schema_asset(obj: dict, rel: str, tenant: str) -> DataAsset | None:
    props = obj.get("properties") or {}
    if not props and obj.get("type") == "record":  # Avro
        props = {f["name"]: {"type": f.get("type")} for f in obj.get("fields", []) if isinstance(f, dict)}
        kind = "avro"
    else:
        kind = "json_schema"
    if not props:
        return None
    cols = []
    for k, v in props.items():
        c = classify_column(k)
        c.dtype = str(v.get("type", "")) if isinstance(v, dict) else ""
        cols.append(c)
    return _asset(tenant, kind, rel, cols)


_PROTO_MSG = re.compile(r"message\s+(\w+)\s*\{(.*?)\}", re.S)
_PROTO_FIELD = re.compile(r"^\s*(?:repeated\s+|optional\s+)?([\w.]+)\s+(\w+)\s*=\s*\d+", re.M)


def _proto_assets(text: str, rel: str, tenant: str) -> list[DataAsset]:
    out = []
    for m in _PROTO_MSG.finditer(text):
        cols = []
        for fm in _PROTO_FIELD.finditer(m.group(2)):
            c = classify_column(fm.group(2))
            c.dtype = fm.group(1)
            cols.append(c)
        if cols:
            out.append(_asset(tenant, "protobuf", f"{rel}#{m.group(1)}", cols))
    return out


def _dbt_assets(text: str, rel: str, tenant: str) -> list[DataAsset]:
    import yaml

    out = []
    try:
        doc = yaml.safe_load(text) or {}
    except yaml.YAMLError:
        return out
    for model in (doc.get("models") or doc.get("sources") or []) if isinstance(doc, dict) else []:
        if not isinstance(model, dict):
            continue
        for tbl in ([model] if "columns" in model else model.get("tables", [])):
            cols = [classify_column(c["name"]) for c in tbl.get("columns", []) if isinstance(c, dict) and "name" in c]
            if cols:
                a = _asset(tenant, "dbt", f"{rel}#{tbl.get('name', model.get('name', ''))}", cols)
                a.meta = {k: str(v) for k, v in (tbl.get("meta") or {}).items() if isinstance(v, (str, int, float))}
                out.append(a)
    return out


# --------------------------------------------------------------------------- data cards / manifests (provenance)
_CARD_KEYS = {
    "license": re.compile(r"^\W*licen[cs]e[sd]?\s*[:=]\s*[\"']?([A-Za-z0-9.\-+_ ]{2,40})", re.I | re.M),
    "region": re.compile(r"^\W*(?:data\s+)?(?:region|location|residency)\s*[:=]\s*[\"']?([A-Za-z0-9\-_ ]{2,30})", re.I | re.M),
    "retention": re.compile(r"^\W*retention[^:\n]*[:=]\s*(.+)$", re.I | re.M),
    "source": re.compile(r"^\W*(?:data\s+)?source[s]?\s*[:=]\s*(.+)$", re.I | re.M),
    "collection": re.compile(r"^\W*(?:collection|acquisition)(?:\s+method)?\s*[:=]\s*(.+)$", re.I | re.M),
    "consent": re.compile(r"^\W*(?:consent|lawful basis)[^:\n]*[:=]\s*(.+)$", re.I | re.M),
    "lineage": re.compile(r"^\W*(?:lineage|derived[_ ]from|upstream)\s*[:=]\s*(.+)$", re.I | re.M),
    "opt_out": re.compile(r"^\W*(?:tdm\s+)?opt[- ]?out[^:\n]*[:=]\s*(.+)$", re.I | re.M),
}
_CARD_FILE = re.compile(r"(data[_-]?card|datasheet|dataset[_-]?card|data[_-]?manifest|dataset)", re.I)


def _card_asset(text: str, rel: str, tenant: str) -> DataAsset | None:
    front = text
    m = re.match(r"---\n(.*?)\n---", text, re.S)
    if m:
        front = m.group(1) + "\n" + text[m.end():]
    meta, lic, region = {}, None, None
    for k, rx in _CARD_KEYS.items():
        mm = rx.search(front)
        if mm:
            v = mm.group(1).strip()[:160]
            if k == "license":
                lic = v
            elif k == "region":
                region = v
            else:
                meta[k] = v
    scraped = bool(re.search(r"\b(scrap\w+|crawl\w+|untargeted|bulk (public|web)|harvest\w*)\b", text, re.I))
    if scraped:
        meta["scraped"] = "true"
    if not (meta or lic or region):
        return None
    a = _asset(tenant, "data_card", rel, [], None, license=lic, region=region)
    a.meta = meta
    return a


def _dvc_asset(text: str, rel: str, tenant: str) -> DataAsset | None:
    import yaml

    try:
        d = yaml.safe_load(text) or {}
    except yaml.YAMLError:
        return None
    outs = d.get("outs") if isinstance(d, dict) else None
    if not outs:
        return None
    a = _asset(tenant, "dvc", rel, [], None)
    a.meta = {"lineage": ", ".join(str(o.get("path", "")) for o in outs if isinstance(o, dict))[:160], **{k: str(v) for k, v in (d.get("meta") or {}).items()}}
    return a


# --------------------------------------------------------------------------- directory scan
DATA_SUFFIXES = {".csv", ".tsv", ".parquet", ".jsonl", ".ndjson", ".sql", ".avsc", ".proto", ".dvc"}
_SKIP_PARTS = {"tests", "test", "__tests__", "reviewer", "node_modules"}
_MANIFEST_NAMES = {"package.json", "package-lock.json", "tsconfig.json", "composer.json", "pyproject.toml", "catalog.json"}


def scan_data(root: Path | str, tenant_id: str, max_bytes: int = 2_000_000_000) -> list[DataAsset]:
    root = Path(root)
    assets: list[DataAsset] = []
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        parts = set(p.relative_to(root).parts[:-1])
        if parts & (SKIP_DIRS | _SKIP_PARTS):
            continue
        rel = p.relative_to(root).as_posix()
        suffix, name = p.suffix.lower(), p.name.lower()
        try:
            if p.stat().st_size > max_bytes:
                continue
            if suffix in {".csv", ".tsv"}:
                a = _csv_asset(p, rel, tenant_id)
                assets += [a] if a else []
            elif suffix == ".parquet":
                a = _parquet_asset(p, rel, tenant_id)
                assets += [a] if a else []
            elif suffix in {".jsonl", ".ndjson"}:
                a = _jsonl_asset(p, rel, tenant_id)
                assets += [a] if a else []
            elif suffix == ".sql":
                assets += _ddl_assets(p.read_text(encoding="utf-8", errors="replace"), rel, tenant_id)
            elif suffix == ".proto":
                assets += _proto_assets(p.read_text(encoding="utf-8", errors="replace"), rel, tenant_id)
            elif suffix == ".dvc" or name == "dvc.yaml":
                a = _dvc_asset(p.read_text(encoding="utf-8", errors="replace"), rel, tenant_id)
                assets += [a] if a else []
            elif suffix == ".avsc" or name.endswith(".schema.json") or "schema" in name and suffix == ".json":
                a = _json_schema_asset(json.loads(p.read_text(encoding="utf-8", errors="replace")), rel, tenant_id)
                assets += [a] if a else []
            elif suffix in {".yml", ".yaml"} and name in {"schema.yml", "schema.yaml", "sources.yml", "models.yml"}:
                assets += _dbt_assets(p.read_text(encoding="utf-8", errors="replace"), rel, tenant_id)
            elif suffix in {".md", ".yaml", ".yml", ".txt"} and _CARD_FILE.search(name):
                a = _card_asset(p.read_text(encoding="utf-8", errors="replace"), rel, tenant_id)
                assets += [a] if a else []
            elif name in {"readme.md"} and re.search(r"^---\n.*?(task_categories|dataset_info|license)\b", p.read_text(encoding="utf-8", errors="replace")[:1500], re.S):
                a = _card_asset(p.read_text(encoding="utf-8", errors="replace"), rel, tenant_id)  # Hugging Face dataset card
                assets += [a] if a else []
        except Exception:
            continue  # an unreadable data file is skipped here; coverage reports counts, never values
    return assets


# --------------------------------------------------------------------------- live metadata sources (injected clients; read-only)
class SqlInformationSchemaSource:
    """Postgres / Snowflake / BigQuery-style `information_schema.columns` through an injected DB-API connection (read-only account)."""

    name = "sql"

    def __init__(self, connect, schema: str = "public", tenant_id: str = "tenant", region: str | None = None):
        self.connect, self.schema, self.tenant, self.region = connect, schema, tenant_id, region

    def describe(self) -> list[DataAsset]:
        conn = self.connect()
        try:
            cur = conn.cursor()
            cur.execute("SELECT table_name, column_name, data_type FROM information_schema.columns WHERE table_schema = %s ORDER BY table_name, ordinal_position", (self.schema,))
            tables: dict[str, list[ColumnFact]] = {}
            for t, c, dt in cur.fetchall():
                col = classify_column(c)
                col.dtype = dt
                tables.setdefault(t, []).append(col)
        finally:
            conn.close()
        return [_asset(self.tenant, "sql_table", f"sql://{self.schema}/{t}", cols, region=self.region) for t, cols in tables.items()]


class UnityCatalogSource:
    """Delta/Unity Catalog table metadata through databricks-sdk (`w.tables.list`)."""

    name = "unity_catalog"

    def __init__(self, workspace_client, catalog: str, schema: str, tenant_id: str = "tenant"):
        self.w, self.catalog, self.schema, self.tenant = workspace_client, catalog, schema, tenant_id

    def describe(self) -> list[DataAsset]:
        out = []
        for t in self.w.tables.list(catalog_name=self.catalog, schema_name=self.schema):
            cols = []
            for c in (t.columns or []):
                col = classify_column(c.name)
                col.dtype = str(getattr(c, "type_text", "") or "")
                cols.append(col)
            a = _asset(self.tenant, "uc_table", f"uc://{self.catalog}.{self.schema}.{t.name}", cols)
            props = getattr(t, "properties", None) or {}
            a.region = props.get("region") or props.get("location")
            a.meta = {k: str(v) for k, v in props.items() if k in {"retention", "source", "lineage", "consent", "license"}}
            out.append(a)
        return out


class MongoSchemaSource:
    """MongoDB collection schema inferred from a bounded sample; values are classified in memory and discarded."""

    name = "mongo"

    def __init__(self, db, collections: list[str] | None = None, tenant_id: str = "tenant", sample: int = 50):
        self.db, self.collections, self.tenant, self.sample = db, collections, tenant_id, sample

    def describe(self) -> list[DataAsset]:
        out = []
        for name in self.collections or self.db.list_collection_names():
            keys: dict[str, list] = {}
            for doc in self.db[name].find({}, limit=self.sample):
                for k, v in doc.items():
                    if k != "_id":
                        keys.setdefault(k, []).append(v if not isinstance(v, (dict, list)) else None)
            out.append(_asset(self.tenant, "mongo", f"mongo://{name}", [classify_column(k, v) for k, v in keys.items()]))
        return out


# --------------------------------------------------------------------------- fairness from labelled outcomes
OUTCOME_COLS = re.compile(r"^(outcome|decision|selected|shortlisted|approved|hired|accepted|result|label)$", re.I)
POSITIVE = re.compile(r"^(1|true|yes|y|approved|accepted|selected|shortlisted|hired|pass(ed)?|positive)$", re.I)
GROUP_COLS = {"sex": re.compile(r"^(sex|gender)$", re.I), "age": re.compile(r"^(age[_ ]?(band|group|bracket)|age)$", re.I),
              "ethnicity": re.compile(r"^(ethnic\w*|race)$", re.I), "disability": re.compile(r"^(disab\w*)$", re.I)}


def _age_group(v: str) -> str:
    try:
        a = int(float(v))
        return "under 30" if a < 30 else "30-49" if a < 50 else "50+"
    except ValueError:
        return v


def compute_fairness(root: Path | str, min_group: int = 30) -> dict | None:
    """Selection-rate ratios per protected group from a labelled outcomes CSV (columns: outcome + protected attributes).

    Returns aggregates only (group label, n, rate, ratio vs the highest-rate group). Groups with n < min_group report no rate.
    The 0.80 line is a screening indicator, not a legal test. Returns None when no outcomes file exists (never invents numbers).
    """
    root = Path(root)
    for p in sorted(root.rglob("*.csv")):
        if set(p.relative_to(root).parts[:-1]) & (SKIP_DIRS | _SKIP_PARTS):
            continue
        with p.open("r", encoding="utf-8", errors="replace", newline="") as fh:
            rd = csv.DictReader(fh)
            fields = rd.fieldnames or []
            out_col = next((f for f in fields if OUTCOME_COLS.match(f.strip())), None)
            grp = {k: next((f for f in fields if rx.match(f.strip())), None) for k, rx in GROUP_COLS.items()}
            grp = {k: v for k, v in grp.items() if v}
            if not out_col or not grp:
                continue
            counts: dict[str, dict[str, list[int]]] = {k: {} for k in grp}
            for row in rd:
                pos = 1 if POSITIVE.match(str(row.get(out_col, "")).strip()) else 0
                for k, col in grp.items():
                    g = str(row.get(col, "")).strip()
                    g = _age_group(g) if k == "age" else g
                    if g:
                        c = counts[k].setdefault(g, [0, 0])
                        c[0] += 1
                        c[1] += pos
        metrics = []
        for k, groups in counts.items():
            rated = {g: c[1] / c[0] for g, c in groups.items() if c[0] >= min_group}
            top = max(rated.values()) if rated else 0
            for g, (n, pos) in sorted(groups.items()):
                if g in rated and top > 0:
                    ratio = round(rated[g] / top, 2)
                    metrics.append({"attribute": k, "group": g, "n": n, "selection_rate": round(rated[g], 3), "ratio_vs_top": ratio, "flag": ratio < 0.8})
                else:
                    metrics.append({"attribute": k, "group": g, "n": n, "selection_rate": None, "ratio_vs_top": None, "flag": False, "note": f"n < {min_group}"})
        return {"source": p.relative_to(root).as_posix(), "metrics": metrics, "caveat": "0.80 is a screening indicator, not a legal test under equality law."}
    return None
