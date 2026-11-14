"""Multi-language code scanner (tree-sitter) emitting the same ASTSlice / BehavioralCapabilityCard facts as the Python scanner.

tree-sitter enumerates functions/methods/handlers with exact line ranges and names; capability facts (AI SDK calls, outbound
HTTP, redaction, human gates, moderation, watermarking, routes, generation, decisions) come from shared regexes applied to
each function's own text plus its same-file call graph. Code is only parsed, never executed.
"""
from __future__ import annotations

import re
from pathlib import Path

from src.schemas.artifacts import ASTSlice, BehavioralCapabilityCard, sha256_text

from . import code_scanner as cs

# --------------------------------------------------------------------------- language table
# ext -> (tree-sitter language, node types that are callable units)
LANGS: dict[str, tuple[str, set[str]]] = {
    ".ts": ("typescript", {"function_declaration", "method_definition", "arrow_function", "function_expression", "function"}),
    ".tsx": ("tsx", {"function_declaration", "method_definition", "arrow_function", "function_expression", "function"}),
    ".js": ("javascript", {"function_declaration", "method_definition", "arrow_function", "function_expression", "function"}),
    ".jsx": ("javascript", {"function_declaration", "method_definition", "arrow_function", "function_expression", "function"}),
    ".mjs": ("javascript", {"function_declaration", "method_definition", "arrow_function", "function_expression", "function"}),
    ".cjs": ("javascript", {"function_declaration", "method_definition", "arrow_function", "function_expression", "function"}),
    ".java": ("java", {"method_declaration", "constructor_declaration"}),
    ".kt": ("kotlin", {"function_declaration"}),
    ".go": ("go", {"function_declaration", "method_declaration"}),
    ".cs": ("csharp", {"method_declaration", "local_function_statement"}),
    ".rs": ("rust", {"function_item"}),
    ".rb": ("ruby", {"method", "singleton_method"}),
    ".php": ("php", {"function_definition", "method_declaration"}),
    ".swift": ("swift", {"function_declaration"}),
    ".sh": ("bash", {"function_definition"}),
    ".bash": ("bash", {"function_definition"}),
}
# Source-like extensions we recognise but cannot parse: reported as a coverage gap, never silently skipped.
UNSCANNED_EXT = {".scala", ".lua", ".r", ".m", ".mm", ".c", ".h", ".cc", ".cpp", ".hpp", ".dart", ".pl", ".ex", ".exs",
                 ".clj", ".hs", ".erl", ".ml", ".jl", ".groovy", ".vb", ".f90", ".sol", ".zig", ".nim", ".ps1", ".vue", ".svelte"}

_PARSERS: dict[str, object] = {}


def _parser(lang: str):
    if lang not in _PARSERS:
        try:
            from tree_sitter_language_pack import get_parser

            _PARSERS[lang] = get_parser(lang)
        except Exception:  # pragma: no cover - parser unavailable -> regex fallback
            _PARSERS[lang] = None
    return _PARSERS[lang]


# --------------------------------------------------------------------------- shared language-agnostic regexes
HTTP_ANY_RE = re.compile(
    r"\bnode-fetch\b|\bhttp\.(Get|Post|NewRequest|Client)\b|\bnet/http\b|\bHttpClient\b|\bRestTemplate\b|"
    r"\bWebClient\b|\bOkHttp\w*\b|\bHttpURLConnection\b|\breqwest\b|\bureq\b|\bFaraday\b|\bNet::HTTP\b|\bcurl_(init|exec)\b|"
    r"\bGuzzle\w*\b|\bURLSession\b|\bAlamofire\b|\bhttp\.request\b|\bhttps?\.get\b|\bcurl\s+-|\bwget\s+|\bInvoke-WebRequest\b", re.I)
AI_ANY_RE = re.compile(
    r"\b(openai|OpenAI|anthropic|Anthropic|cohere|litellm|mistral\w*|genai|GoogleGenerativeAI|bedrock\w*|BedrockRuntime|"
    r"langchain\w*|llama_?cpp|vllm|replicate|groq|ollama|huggingface|azure_?openai|vertexai|SageMaker\w*|ChatCompletion\w*|"
    r"langchain4j|spring-?ai|OpenAiService|ChatClient)\b|api\.openai\.com|api\.anthropic\.com|\bclient\.(chat|messages|completions|responses)\b")
# fetch/axios/got are also how browser code calls its own backend with relative URLs; they only count as an outbound call
# when the function text carries an absolute URL (otherwise it is not an external data flow).
HTTP_WEAK_RE = re.compile(r"\bfetch\s*\(|\baxios\b|\bgot\s*\(", re.I)
ROUTE_DECOR_RE = re.compile(
    r"@(Get|Post|Put|Patch|Delete|Request)Mapping|@(Get|Post|Put|Patch|Delete|Controller|RestController|Route|Path|GET|POST|PUT|DELETE)\b|"
    r"\[Http(Get|Post|Put|Patch|Delete)\b|\[Route\b|#\[(get|post|put|delete|patch)\b|@(app|router|bp|blueprint)\.(get|post|put|patch|delete|route)", re.I)
ROUTE_REG_RE = re.compile(
    r"\.(get|post|put|patch|delete|all|handle|handlefunc|route|use|GET|POST|PUT|PATCH|DELETE|Get|Post|Put|Patch|Delete|HandleFunc|Handle)\s*"
    r"\(\s*[\"'`]([^\"'`]*)[\"'`]\s*,\s*(?:async\s*)?(?:\(.*?\)\s*=>|function\b[^{]*\{|([A-Za-z_][\w.]*))")
SHELL_REDACT_RE = re.compile(r"(^|[\s=(|;])(redact|mask|anonymi[sz]e|scrub|pseudonymi[sz]e)\w*\s+[\"$'\w-]", re.I | re.M)
STRING_LIT_RE = re.compile(r"\"((?:[^\"\\\n]|\\.){25,})\"|'((?:[^'\\\n]|\\.){25,})'|`((?:[^`\\]|\\.){25,})`")


def _snake(t: str) -> str:
    """camelCase / PascalCase -> snake_case so the shared (snake_case) regexes also match Java/Go/Swift/C# identifiers."""
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", t)


def _text(node) -> str:
    return node.text.decode("utf-8", errors="replace") if node is not None else ""


def _units(root, types: set[str]):
    out, stack = [], [root]
    while stack:
        n = stack.pop()
        if n.type in types:
            out.append(n)
        stack.extend(reversed(n.children))
    return out


def _name_of(node, src_lines: list[str]) -> str:
    nm = node.child_by_field_name("name")
    if nm is not None:
        return _text(nm)
    for c in node.children:  # Kotlin/Swift/PHP style grammars: identifier child without a field name
        if c.type in {"simple_identifier", "identifier", "name", "field_identifier", "property_identifier"}:
            return _text(c)
    p = node.parent
    # const handler = async (req,res) => {}   |   x.handler = function () {}
    while p is not None and p.type in {"parenthesized_expression", "await_expression", "as_expression"}:
        p = p.parent
    if p is not None:
        if p.type in {"variable_declarator", "public_field_definition", "pair", "property_signature"}:
            n = p.child_by_field_name("name") or p.child_by_field_name("key")
            if n is not None:
                return _text(n)
        if p.type == "assignment_expression":
            l = p.child_by_field_name("left")
            if l is not None:
                return _text(l).split(".")[-1]
        if p.type == "arguments" and p.parent is not None and p.parent.type == "call_expression":
            call = p.parent
            fn = _text(call.child_by_field_name("function"))
            first = next((c for c in p.children if c.type in {"string", "template_string"}), None)
            verb = fn.split(".")[-1].upper()
            route = _text(first).strip("\"'`") if first is not None else ""
            return f"{verb} {route}".strip() if route else f"{verb}_handler_L{node.start_point[0] + 1}"
    return f"anonymous_L{node.start_point[0] + 1}"


def _prev_lines(src_lines: list[str], start: int, n: int = 4) -> str:
    return "\n".join(src_lines[max(0, start - n): start])


def scan_language_file(src: str, rel: str, ext: str, tenant_id: str, result) -> bool:
    """Scan one non-Python source file. Returns True when it was parsed and facts were produced."""
    lang, types = LANGS[ext]
    p = _parser(lang)
    if p is None:
        return False
    data = src.encode("utf-8", errors="replace")
    root = p.parse(data).root_node
    lines = src.splitlines()
    imports_blob = "\n".join(l for l in lines if re.match(r"\s*(import|using|require|use|from|#include|package|const .*require\()", l))
    nodes = _units(root, types)
    route_handlers = {m.group(3) for m in ROUTE_REG_RE.finditer(src) if m.group(3)}

    infos: dict[str, dict] = {}
    for n in nodes:
        name = _name_of(n, lines)
        text = _text(n)
        # nested units belong to the outer one for facts but stay addressable when they are registered routes
        key = name if name not in infos else f"{name}@{n.start_point[0] + 1}"
        before = _prev_lines(lines, n.start_point[0])
        is_route = bool(ROUTE_DECOR_RE.search(before + "\n" + text.splitlines()[0] if text else before)) or \
            name.split(".")[-1] in route_handlers or bool(re.match(r"(GET|POST|PUT|PATCH|DELETE|ALL|HANDLE\w*|USE|ROUTE)\b", name))
        nt = _snake(text)
        infos[key] = {"node": n, "name": name, "text": text, "start": n.start_point[0] + 1, "end": n.end_point[0] + 1,
                      "own_ai": bool(AI_ANY_RE.search(text)),
                      "own_http": bool(HTTP_ANY_RE.search(text)) or (bool(HTTP_WEAK_RE.search(text)) and bool(re.search(r"https?://", text))),
                      "own_gen": bool(cs.GEN_CALL_RE.search(text)), "own_urls": cs._urls_in(text), "is_route": is_route,
                      "flags": {"pii": bool(cs.PII_REDACT_RE.search(nt) or SHELL_REDACT_RE.search(nt)), "hitl": bool(cs.HITL_RE.search(nt)),
                                "mod": bool(cs.MODERATION_RE.search(nt)), "wm": bool(cs.WATERMARK_RE.search(nt)),
                                "disc": bool(cs.DISCLOSURE_RE.search(nt)) and not bool(cs.DISCLOSURE_DENIED_RE.search(text)),
                                "disc_denied": bool(cs.DISCLOSURE_DENIED_RE.search(text))}}
    if not infos:
        return False
    names = {v["name"].split(" ")[-1].split(".")[-1] for v in infos.values()}
    for k, v in infos.items():
        body = v["text"]
        v["calls"] = {o for o in names if o != v["name"] and re.search(rf"\b{re.escape(o)}\s*\(", body)}
    by_short = {}
    for k, v in infos.items():
        by_short.setdefault(v["name"].split(" ")[-1].split(".")[-1], k)
    called = set()
    for v in infos.values():
        called |= {by_short.get(c) for c in v["calls"] if by_short.get(c)}

    def reach(k0):
        seen, stack = set(), [k0]
        while stack:
            k = stack.pop()
            if k in seen:
                continue
            seen.add(k)
            stack.extend(x for x in (by_short.get(c) for c in infos[k]["calls"]) if x and x not in seen)
        return seen

    produced = False
    for k, v in infos.items():
        group = reach(k)
        eff_ai = any(infos[g]["own_ai"] for g in group)
        eff_http = any(infos[g]["own_http"] for g in group)
        eff_urls: list[str] = []
        for g in group:
            for u in infos[g]["own_urls"]:
                if u not in eff_urls:
                    eff_urls.append(u)
        eff_gen = any(infos[g]["own_gen"] for g in group) and (eff_ai or eff_http)
        eff = {f: any(infos[g]["flags"][f] for g in group) for f in ("pii", "hitl", "mod", "wm", "disc")}
        eff["disc_denied"] = bool(v["flags"]["disc_denied"])
        rtxt = cs._route_text(v["name"], [v["text"].splitlines()[0] if v["text"] else ""])
        nname = re.sub(r"[_\-.]+", " ", _snake(v["name"]))
        decision_hit = bool(cs.DECISION_RE.search(nname)) or (v["is_route"] and bool(cs.DECISION_ROUTE_RE.search(rtxt)))
        name_gen = bool(re.match(r"(generate|summari[sz]e|synthesi[sz]e|clone)[_A-Z]", v["name"].split(".")[-1], re.I))
        route_gen = (v["is_route"] and bool(cs.GEN_ROUTE_RE.search(rtxt))) or name_gen
        touches = eff_ai or eff_http
        if not touches and not ((decision_hit and v["is_route"]) or route_gen):
            continue
        if not eff_urls and eff_ai:
            for sdk, url in cs.DEFAULT_SDK_ENDPOINTS.items():
                if re.search(rf"\b{sdk}\b", imports_blob + "\n" + v["text"], re.I):
                    eff_urls = [url]
                    break
        if route_gen:
            eff_gen = True
        sha = sha256_text(v["text"])
        sl = ASTSlice(
            slice_id="slice-" + sha256_text(":".join([tenant_id, rel, str(v["start"]), str(v["end"]), v["name"]]))[:12], tenant_id=tenant_id, file_path=rel,
            start_line=v["start"], end_line=v["end"], code_snippet=v["text"], imports=imports_blob.splitlines()[:30],
            external_endpoints=eff_urls, has_pii_redaction=eff["pii"], has_hitl_gate=eff["hitl"], has_moderation_hook=eff["mod"],
            has_watermark_hook=eff["wm"], has_ai_disclosure=eff["disc"], disclosure_denied=eff["disc_denied"], sha256_hash=sha, function_name=v["name"], endpoint_regions={u: cs.classify_endpoint(u) for u in eff_urls},
            is_route=v["is_route"], is_entrypoint=v["is_route"] or k not in called, calls_ai_sdk=eff_ai, calls_http=eff_http,
            is_generation=eff_gen, is_decision=decision_hit)
        result.slices.append(sl)
        produced = True
    # system prompts: long string literals mentioning system/persona or "you are"
    prompts = []
    for m in STRING_LIT_RE.finditer(src):
        val = next(g for g in m.groups() if g)
        ctx = src[max(0, m.start() - 60): m.start()]
        if re.match(r"\s*you are\b", val, re.I) or re.search(r"system|prompt|persona|instruction", ctx, re.I):
            ln = src.count("\n", 0, m.start()) + 1
            prompts.append({"name": "system_prompt", "text": val, "start": ln, "end": ln + val.count("\\n")})
    for pr in prompts:
        cs._add_prompt_card(pr, rel, tenant_id, result)
    for sl in [s for s in result.slices if s.file_path == rel]:
        cs._add_endpoint_card(sl, prompts, {}, result, tenant_id)
    return produced
