"""Deterministic (no-LLM) code scanner: tree-sitter + regex.

Produces ASTSlice, BehavioralCapabilityCard and DependencyFact artifacts for a company directory.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path
from urllib.parse import urlparse

import tree_sitter_python as tspython
from tree_sitter import Language, Parser

from src.schemas.artifacts import ASTSlice, BehavioralCapabilityCard, DependencyFact, sha256_text

SKIP_DIRS = {".git", "__pycache__", ".venv", "venv", "node_modules", ".mypy_cache", ".pytest_cache", "site-packages"}

_PY = Language(tspython.language())
_PARSER = Parser(_PY)

# ----------------------------------------------------------------------------- regexes
AI_SDK_RE = re.compile(
    r"\b(openai|OpenAI|AsyncOpenAI|anthropic|Anthropic|cohere|litellm|mistralai|genai|ChatOpenAI|"
    r"langchain\w*|llama_cpp|vllm|replicate|groq)\b|\bclient\.(chat|messages|completions|responses|embeddings)\b"
)
HTTP_RE = re.compile(r"\b(requests|httpx|aiohttp|urllib\.request|http\.client)\b|\burlopen\(")
GEN_CALL_RE = re.compile(
    r"chat\.completions|completions\.create|messages\.create|\.generate\(|generate_content|"
    r"text-generation|model\.generate|responses\.create|/chat/completions|/v1/completions|/generate\b|"
    r"\bsynthesi[sz]e\w*\(|\.invoke\("
)
PII_REDACT_RE = re.compile(
    r"presidio|AnalyzerEngine|AnonymizerEngine|\b(redact\w*|mask_\w*|anonymi[sz]e\w*|scrub\w*|pseudonymi[sz]e\w*)\s*\("
    r"|re\.sub\([^)]*(@|\\d|ssn)",
    re.I,
)
HITL_RE = re.compile(
    r"human_review|requires_human|human_approval|approval_queue|review_queue|pending_review|needs_human|"
    r"\bhitl\b|human_in_the_loop|escalate_to_human|manual_review|await_human|human_signoff|clinician_approval",
    re.I,
)
MODERATION_RE = re.compile(
    r"\bmoderat(e|ion)\w*\s*\(|\.moderations\b|content_filter|safety_filter|toxicity|detoxify|"
    r"perspective_api|llama_guard|\bguardrail\w*|\brefuse\w*\s*\(|\bis_safe\s*\(|hate_speech_filter|block_unsafe",
    re.I,
)
WATERMARK_RE = re.compile(
    r"c2pa|watermark|ai_generated|x-ai-generated|ai-generated|synthid|content_credentials|machine_readable_label",
    re.I,
)
DECISION_RE = re.compile(
    r"\b(score|scoring|decision|decide|approve|approval|reject|deny|eligib\w*|underwrit\w*|credit|loan|triage|"
    r"diagnos\w*|shortlist|screen_candidate)\b",
    re.I,
)
# Route-level AI-surface heuristics (Closed-World: a generative/decision HTTP route with no visible SDK call is
# still an AI system until proven otherwise). Matched on route name + decorator path with `_ / -` split to spaces.
GEN_ROUTE_RE = re.compile(
    r"\b(chat|generat\w*|synthes\w*|clon\w*|deepfake|image|voice|audio|video|copilot|completion|assistant|"
    r"summari[sz]\w*|concierge|ideation)\b", re.I)
DECISION_ROUTE_RE = re.compile(
    r"\b(rank\w*|screen\w*|candidate|shortlist\w*|recruit\w*|hiring|resume|cv|underwrit\w*|triage|discharge|"
    r"score|scoring|decision|decide|approve|eligib\w*|credit|loan|diagnos\w*)\b", re.I)


def _route_text(name: str, decorators: list[str]) -> str:
    return re.sub(r"[_/\-]+", " ", " ".join([name, *decorators]))


PII_INDICATOR_RE = re.compile(
    r"\b(email|ssn|national_insurance|ni_number|dob|date_of_birth|address|phone|passport|patient|income|"
    r"account_number|full_name|first_name|last_name|customer|applicant|salary|nhs_number|diagnosis)\b",
    re.I,
)
LOCAL_MODEL_RE = re.compile(r"from_pretrained|AutoModel|llama_cpp|\bgguf\b|\bvllm\b|ctransformers|torch\.load")

UNFILTERED_PROMPT_RE = re.compile(
    r"uncensored|unfiltered|no\s+(content\s+)?(restrictions?|filters?|limits?|guardrails?)|"
    r"(never|do not|don't|won't|must not)\s+(refuse|decline|reject|censor|filter)|without\s+(any\s+)?(refus|filter|moderat|restrict)|"
    r"no[- ]refusals?|ignore\s+(all\s+)?(previous\s+)?(safety|content|ethical)|anything\s+the\s+user\s+(asks|wants|requests)|"
    r"regardless\s+of\s+(content|harm|offen)",
    re.I,
)
SAFE_PROMPT_RE = re.compile(
    r"(refuse|decline)\s+(to\s+)?(generate|produce|assist|help)|do not (generate|produce) (hate|harmful|abusive)|"
    r"hate\s+speech.*(refuse|never|prohibit|not)|safety\s+polic",
    re.I,
)
URL_RE = re.compile(r"https?://[^\s\"'<>)\]}\\,]+")
IGNORED_URL_HOSTS = ("w3.org", "json-schema.org", "schemas.", "example.com", "example.org", "github.com", "docs.")

DEFAULT_SDK_ENDPOINTS = {
    "openai": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com",
    "cohere": "https://api.cohere.com",
    "genai": "https://generativelanguage.googleapis.com",
    "groq": "https://api.groq.com",
    "mistralai": "https://api.mistral.ai",
}

EU_UK_TOKENS = {
    "eu", "uk", "europe", "eur", "london", "frankfurt", "dublin", "paris", "amsterdam", "ireland",
    "uksouth", "ukwest", "westeurope", "northeurope", "germany", "gb", "stockholm", "milan", "zurich",
}
US_TOKENS = {"us", "usa", "virginia", "oregon", "ohio", "iowa", "uswest", "useast", "california", "texas"}
US_HOSTS = (
    "api.openai.com", "api.anthropic.com", "generativelanguage.googleapis.com", "api.cohere.com",
    "api.groq.com", "api.together.xyz", "api-inference.huggingface.co", "api.replicate.com",
)


def classify_endpoint(url: str) -> str:
    """Return US | EU_UK | INTERNAL | UNKNOWN for an endpoint URL."""
    if url.startswith("unresolved://"):
        return "UNKNOWN"
    host = (urlparse(url).hostname or "").lower()
    if not host:
        return "UNKNOWN"
    if host in {"localhost", "127.0.0.1", "::1"} or host.endswith(".local") or host.endswith(".internal") \
            or re.match(r"^(10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.)", host):
        return "INTERNAL"
    tokens = set(re.split(r"[.\-_]", host))
    if tokens & EU_UK_TOKENS or any(t.startswith(("uk", "eu")) and t[2:].rstrip("0123456789") in {"south", "west", "north", "central"} for t in tokens):
        return "EU_UK"
    if host.endswith((".eu", ".uk")):
        return "EU_UK"
    if host in US_HOSTS or tokens & US_TOKENS or host.endswith(".us"):
        return "US"
    return "UNKNOWN"


# ----------------------------------------------------------------------------- data helpers
def _walk_files(root: Path):
    for p in sorted(root.rglob("*")):
        if p.is_file() and not (set(p.relative_to(root).parts[:-1]) & SKIP_DIRS):
            yield p


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _text(node) -> str:
    return node.text.decode("utf-8", errors="replace")


def _decode_py_string(raw: str) -> str:
    try:
        val = ast.literal_eval(raw)
        if isinstance(val, str):
            return val
    except Exception:
        pass
    return raw.strip("'\"")


def _collect_functions(node, out: list):
    for child in node.children:
        if child.type == "function_definition":
            out.append(child)
        elif child.type == "decorated_definition":
            inner = child.child_by_field_name("definition")
            if inner is not None and inner.type == "function_definition":
                out.append(child)
            else:
                _collect_functions(child, out)
        elif child.type in {"class_definition", "block", "if_statement", "try_statement", "with_statement"}:
            _collect_functions(child, out)
        elif child.type in {"module"}:
            _collect_functions(child, out)


def _imports(root) -> list[str]:
    mods: list[str] = []
    for child in root.children:
        if child.type in {"import_statement", "import_from_statement"}:
            mods.append(_text(child).strip())
    return mods


def _module_constants(root) -> tuple[dict[str, str], dict[str, str]]:
    """Return (name -> RHS source, name -> literal string value) for top-level assignments."""
    rhs_src: dict[str, str] = {}
    str_val: dict[str, str] = {}
    for child in root.children:
        if child.type != "expression_statement":
            continue
        for a in child.children:
            if a.type != "assignment":
                continue
            left, right = a.child_by_field_name("left"), a.child_by_field_name("right")
            if left is None or right is None or left.type != "identifier":
                continue
            name = _text(left)
            rhs_src[name] = _text(right)
            if right.type == "string":
                str_val[name] = _decode_py_string(_text(right))
    return rhs_src, str_val


def _urls_in(text: str) -> list[str]:
    out = []
    for u in URL_RE.findall(text):
        u = u.rstrip(".;:'\"")
        if any(h in u for h in IGNORED_URL_HOSTS):
            continue
        if u not in out:
            out.append(u)
    return out


# ----------------------------------------------------------------------------- scanning
class ScanResult:
    def __init__(self):
        self.slices: list[ASTSlice] = []
        self.cards: list[BehavioralCapabilityCard] = []
        self.dependencies: list[DependencyFact] = []
        self.py_files: list[str] = []
        self.uses_local_model: bool = False


def scan_code(company_dir: Path | str, tenant_id: str) -> ScanResult:
    root = Path(company_dir)
    result = ScanResult()
    for path in _walk_files(root):
        rel = path.relative_to(root).as_posix()
        if path.suffix == ".py":
            result.py_files.append(rel)
            src = _read(path)
            _scan_python_file(src, rel, tenant_id, result)
            if LOCAL_MODEL_RE.search(src):
                result.uses_local_model = True
        elif path.name.lower().startswith("requirements") and path.suffix in {".txt", ".in"}:
            result.dependencies.extend(parse_requirements(_read(path), rel, tenant_id))
        if path.suffix in {".md", ".txt", ".json", ".yaml", ".yml", ".toml", ".cfg", ".py"} or path.name.upper().startswith(("LICENSE", "MODEL_CARD")):
            result.dependencies.extend(_model_license_facts(_read(path), rel, tenant_id))
    return result


def _scan_python_file(src: str, rel: str, tenant_id: str, result: ScanResult) -> None:
    data = src.encode("utf-8", errors="replace")
    tree = _PARSER.parse(data)
    root = tree.root_node
    imports = _imports(root)
    imports_blob = "\n".join(imports)
    rhs_src, str_val = _module_constants(root)

    func_nodes: list = []
    _collect_functions(root, func_nodes)

    infos: dict[str, dict] = {}
    for node in func_nodes:
        defn = node.child_by_field_name("definition") if node.type == "decorated_definition" else node
        name = _text(defn.child_by_field_name("name"))
        text = _text(node)
        decorators = [_text(c) for c in node.children if c.type == "decorator"] if node.type == "decorated_definition" else []
        infos[name] = {
            "node": node, "text": text, "start": node.start_point[0] + 1, "end": node.end_point[0] + 1,
            "decorators": decorators,
        }

    local_names = set(infos)
    for name, info in infos.items():
        body = info["text"]
        info["calls"] = {n for n in local_names if n != name and re.search(rf"\b{re.escape(n)}\s*\(", body)}
        info["is_route"] = any(re.search(r"\.(get|post|put|delete|patch|route|api_route|websocket)\s*\(", d) for d in info["decorators"])
        urls = _urls_in(body)
        for cname, rhs in rhs_src.items():
            if re.search(rf"\b{re.escape(cname)}\b", body):
                for u in _urls_in(rhs):
                    if u not in urls:
                        urls.append(u)
        info["own_ai"] = bool(AI_SDK_RE.search(body)) or any(
            re.search(rf"\b{re.escape(c)}\b", body) and AI_SDK_RE.search(rhs) for c, rhs in rhs_src.items()
        )
        info["own_http"] = bool(HTTP_RE.search(body))
        info["own_urls"] = urls
        info["own_gen"] = bool(GEN_CALL_RE.search(body))
        info["flags"] = {
            "pii": bool(PII_REDACT_RE.search(body)),
            "hitl": bool(HITL_RE.search(body)),
            "mod": bool(MODERATION_RE.search(body)),
            "wm": bool(WATERMARK_RE.search(body)),
        }

    def reach(name: str) -> set[str]:
        seen, stack = set(), [name]
        while stack:
            n = stack.pop()
            if n in seen:
                continue
            seen.add(n)
            stack.extend(infos[n]["calls"] - seen)
        return seen

    called_by_local: set[str] = set()
    for info in infos.values():
        called_by_local |= info["calls"]

    # system prompts (module-level strings + inline) -> cards
    prompts = _find_system_prompts(root, str_val)

    for name, info in infos.items():
        group = reach(name)
        eff_ai = any(infos[g]["own_ai"] for g in group)
        eff_http = any(infos[g]["own_http"] for g in group)
        eff_urls: list[str] = []
        for g in group:
            for u in infos[g]["own_urls"]:
                if u not in eff_urls:
                    eff_urls.append(u)
        eff_gen = any(infos[g]["own_gen"] and (infos[g]["own_ai"] or infos[g]["own_http"] or GEN_CALL_RE.search(infos[g]["text"])) for g in group) and (eff_ai or eff_http)
        eff = {k: any(infos[g]["flags"][k] for g in group) for k in ("pii", "hitl", "mod", "wm")}
        touches = eff_ai or eff_http
        rtxt = _route_text(name, info["decorators"])
        decision_hit = bool(DECISION_RE.search(name)) or any(DECISION_RE.search(d) for d in info["decorators"]) \
            or (info["is_route"] and bool(DECISION_ROUTE_RE.search(rtxt)))
        name_gen = bool(re.match(r"(generate|summari[sz]e|synthesi[sz]e|clone)_", name))  # non-route generator (e.g. service method)
        route_gen = (info["is_route"] and bool(GEN_ROUTE_RE.search(rtxt))) or name_gen
        if not touches and not ((decision_hit and info["is_route"]) or route_gen):
            continue

        if not eff_urls and eff_ai:
            if re.search(r"base_url\s*=", src):
                eff_urls = ["unresolved://dynamic-base-url"]
            else:
                for sdk, url in DEFAULT_SDK_ENDPOINTS.items():
                    if re.search(rf"\b{sdk}\b", imports_blob + "\n" + info["text"], re.I):
                        eff_urls = [url]
                        break
        if route_gen:
            eff_gen = True
        regions = {u: classify_endpoint(u) for u in eff_urls}
        is_entry = info["is_route"] or name not in called_by_local
        sha = sha256_text(info["text"])
        sl = ASTSlice(
            slice_id=f"slice-{sha256_text(f'{tenant_id}:{rel}:{info['start']}')[:12]}",
            tenant_id=tenant_id, file_path=rel, start_line=info["start"], end_line=info["end"],
            code_snippet=info["text"], imports=imports, external_endpoints=eff_urls,
            has_pii_redaction=eff["pii"], has_hitl_gate=eff["hitl"], has_moderation_hook=eff["mod"],
            has_watermark_hook=eff["wm"], sha256_hash=sha, function_name=name, endpoint_regions=regions,
            is_route=info["is_route"], is_entrypoint=is_entry, calls_ai_sdk=eff_ai, calls_http=eff_http,
            is_generation=eff_gen, is_decision=decision_hit,
        )
        result.slices.append(sl)

        if is_entry and (eff_gen or decision_hit):
            _add_endpoint_card(sl, prompts, str_val, result, tenant_id)

    for p in prompts:
        _add_prompt_card(p, rel, tenant_id, result)


def _find_system_prompts(root, str_val: dict[str, str]) -> list[dict]:
    """Collect candidate system prompts: (name, text, start_line, end_line)."""
    found: list[dict] = []
    seen: set[tuple[int, int]] = set()

    def visit(node):
        if node.type == "assignment":
            left, right = node.child_by_field_name("left"), node.child_by_field_name("right")
            if left is not None and right is not None and right.type in {"string", "concatenated_string", "parenthesized_expression"}:
                name = _text(left)
                val = _decode_py_string(_text(right))
                if not isinstance(val, str) or val.startswith(("(", "'", '"')) and right.type != "string":
                    val = re.sub(r"\s+", " ", re.sub(r"[\"'()]", "", _text(right))).strip()
                key = (right.start_point[0], right.end_point[0])
                if len(val) > 15 and key not in seen and (
                    re.search(r"system|prompt|persona|instruction", name, re.I) or re.match(r"\s*you are\b", val, re.I)
                ):
                    seen.add(key)
                    found.append({"name": name, "text": val, "start": right.start_point[0] + 1, "end": right.end_point[0] + 1})
        elif node.type == "pair":
            k, v = node.child_by_field_name("key"), node.child_by_field_name("value")
            if k is not None and v is not None and v.type == "string":
                pass  # handled by dict scan below
        for c in node.children:
            visit(c)

    visit(root)
    # {"role": "system", "content": "..."} dicts
    def visit_dicts(node):
        if node.type == "dictionary":
            pairs = {}
            for c in node.children:
                if c.type == "pair":
                    k, v = c.child_by_field_name("key"), c.child_by_field_name("value")
                    if k is not None and v is not None and k.type == "string":
                        pairs[_decode_py_string(_text(k))] = v
            role, content = pairs.get("role"), pairs.get("content")
            if role is not None and content is not None and role.type == "string" and _decode_py_string(_text(role)) == "system":
                if content.type in {"string", "concatenated_string"}:
                    val = _decode_py_string(_text(content))
                    key = (content.start_point[0], content.end_point[0])
                    if key not in seen and val:
                        seen.add(key)
                        found.append({"name": "inline_system_message", "text": val, "start": content.start_point[0] + 1, "end": content.end_point[0] + 1})
        for c in node.children:
            visit_dicts(c)

    visit_dicts(root)
    return found


def _add_prompt_card(p: dict, rel: str, tenant_id: str, result: ScanResult) -> None:
    tags = ["system_prompt"]
    if UNFILTERED_PROMPT_RE.search(p["text"]):
        tags += ["unfiltered_prompt", "unmoderated_hate_speech_risk"]
    elif SAFE_PROMPT_RE.search(p["text"]):
        tags.append("safety_prompted")
    locator = f"{rel}:{p['start']}-{p['end']}"
    result.cards.append(BehavioralCapabilityCard(
        module_id=f"{rel}::{p['name']}", tenant_id=tenant_id, exact_locator=locator,
        system_prompt=p["text"], capability_tags=tags, sha256_hash=sha256_text(p["text"] + locator),
    ))


def _add_endpoint_card(sl: ASTSlice, prompts: list[dict], str_val: dict[str, str], result: ScanResult, tenant_id: str) -> None:
    prompt_text = ""
    for p in prompts:
        if re.search(rf"\b{re.escape(p['name'])}\b", sl.code_snippet) and p["name"] != "inline_system_message":
            prompt_text = p["text"]
            break
    if not prompt_text:
        for p in prompts:
            if p["start"] >= sl.start_line and p["end"] <= sl.end_line:
                prompt_text = p["text"]
                break
    if not prompt_text and len(prompts) == 1:
        prompt_text = prompts[0]["text"]
    tags: list[str] = []
    if sl.is_generation:
        tags.append("generation_endpoint")
        unfiltered = bool(UNFILTERED_PROMPT_RE.search(prompt_text))
        if not sl.has_moderation_hook:
            tags.append("unrestricted_text_gen")
        if unfiltered or not sl.has_moderation_hook:
            tags.append("unmoderated_hate_speech_risk")
        if unfiltered:
            tags.append("unfiltered_prompt")
        if sl.has_moderation_hook:
            tags.append("moderated")
        if sl.has_watermark_hook:
            tags.append("watermarked")
    if sl.is_decision:
        tags.append("automated_decision")
        tags.append("human_gate_present" if sl.has_hitl_gate else "no_human_gate")
    if sl.endpoint_regions and any(r == "US" for r in sl.endpoint_regions.values()):
        tags.append("us_hosted_inference")
    result.cards.append(BehavioralCapabilityCard(
        module_id=f"{sl.file_path}::{sl.function_name}", tenant_id=tenant_id, exact_locator=sl.locator,
        system_prompt=prompt_text, capability_tags=tags, sha256_hash=sha256_text(prompt_text + sl.sha256_hash),
    ))


# ----------------------------------------------------------------------------- dependencies
KNOWN_LICENSES = {
    # strong copyleft
    "pyqt5": "GPL-3.0", "pyqt6": "GPL-3.0", "mysql-connector-python": "GPL-2.0", "pymupdf": "AGPL-3.0",
    "ghostscript": "GPL-3.0", "gpl-lib": "GPL-3.0", "readline": "GPL-3.0", "pyside2-gpl": "GPL-3.0",
    # weak copyleft
    "chardet": "LGPL-2.1", "psycopg2": "LGPL-3.0", "pyinstaller": "GPL-2.0-with-exception",
    # permissive
    "fastapi": "MIT", "uvicorn": "BSD-3-Clause", "pydantic": "MIT", "requests": "Apache-2.0", "httpx": "BSD-3-Clause",
    "openai": "Apache-2.0", "anthropic": "MIT", "numpy": "BSD-3-Clause", "pandas": "BSD-3-Clause",
    "scikit-learn": "BSD-3-Clause", "presidio-analyzer": "MIT", "presidio-anonymizer": "MIT", "flask": "BSD-3-Clause",
    "sqlalchemy": "MIT", "pytest": "MIT", "python-dotenv": "BSD-3-Clause", "pyyaml": "MIT", "transformers": "Apache-2.0",
    "torch": "BSD-3-Clause", "c2pa-python": "Apache-2.0", "langchain": "MIT", "tiktoken": "MIT", "jinja2": "BSD-3-Clause",
    "detoxify": "Apache-2.0", "boto3": "Apache-2.0", "redis": "MIT", "celery": "BSD-3-Clause", "starlette": "BSD-3-Clause",
}


def classify_license(lic: str) -> str:
    l = lic.upper()
    if re.search(r"\bNC\b|-NC|NON[- ]?COMMERCIAL", l):
        return "NON_COMMERCIAL"
    if re.search(r"\bAGPL|\bGPL", l) and "LGPL" not in l:
        return "STRONG_COPYLEFT"
    if "LGPL" in l or "MPL" in l or "EPL" in l:
        return "WEAK_COPYLEFT"
    if re.search(r"MIT|BSD|APACHE|ISC|PSF|UNLICENSE|CC0|HPND", l):
        return "PERMISSIVE"
    return "UNKNOWN"


def parse_requirements(text: str, rel: str, tenant_id: str) -> list[DependencyFact]:
    facts = []
    for i, line in enumerate(text.splitlines(), 1):
        raw = line.strip()
        if not raw or raw.startswith(("#", "-")):
            continue
        spec, _, comment = raw.partition("#")
        name = re.split(r"[<>=!~\[; ]", spec.strip(), maxsplit=1)[0].lower().replace("_", "-")
        if not name:
            continue
        lic = None
        m = re.search(r"licen[cs]e\s*[:=]\s*([A-Za-z0-9.\-+ ]+)", comment, re.I)
        if m:
            lic = m.group(1).strip()
        lic = lic or KNOWN_LICENSES.get(name, "UNKNOWN")
        sha = sha256_text(raw)
        facts.append(DependencyFact(
            dep_id=f"dep-{sha256_text(f'{tenant_id}:{rel}:{i}')[:12]}", tenant_id=tenant_id, kind="package", name=name,
            license=lic, license_class=classify_license(lic), file_path=rel, line=i, snippet=raw, sha256_hash=sha,
        ))
    return facts


_MODEL_LICENSE_RE = re.compile(r"^\W*(model[_ ]?)?licen[cs]e[d]?\s*[:=]\s*[\"']?([A-Za-z0-9.\-+_ ]{3,40})", re.I)


def _model_license_facts(text: str, rel: str, tenant_id: str) -> list[DependencyFact]:
    facts = []
    for i, line in enumerate(text.splitlines(), 1):
        m = _MODEL_LICENSE_RE.match(line)
        if not m:
            continue
        lic = m.group(2).strip().strip("\"'")
        cls = classify_license(lic)
        if cls == "UNKNOWN":
            continue
        # requirements comments are handled elsewhere; only model/weights style declarations here
        if rel.lower().startswith("requirements"):
            continue
        sha = sha256_text(line.strip())
        facts.append(DependencyFact(
            dep_id=f"lic-{sha256_text(f'{tenant_id}:{rel}:{i}')[:12]}", tenant_id=tenant_id, kind="model_weights",
            name=Path(rel).stem, license=lic, license_class=cls, file_path=rel, line=i,
            snippet=line.strip(), sha256_hash=sha,
        ))
    return facts
