"""Dependency manifests for many ecosystems and infrastructure/config facts (hosting region, egress, model providers).

Parse only; nothing is executed or installed. Every fact carries file, line and sha256 like all other artifacts.
"""
from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

from src.schemas.artifacts import BehavioralCapabilityCard, DependencyFact, sha256_text

from . import code_scanner as cs

# --------------------------------------------------------------------------- licences for common non-Python packages
KNOWN_LICENSES_EXT = {
    # strong copyleft / AGPL / restricted
    "itext": "AGPL-3.0", "itextpdf": "AGPL-3.0", "mysql-connector-java": "GPL-2.0", "mysql-connector-j": "GPL-2.0",
    "ffmpeg-static": "GPL-3.0", "audiocraft": "GPL-3.0", "audiocraft-gpl": "GPL-3.0", "ghostscript4js": "AGPL-3.0",
    "gnu-readline": "GPL-3.0", "libpostal": "GPL-3.0", "x264": "GPL-2.0", "wkhtmltopdf": "LGPL-3.0", "highcharts": "CC-BY-NC-4.0",
    "mongodb-server": "SSPL-1.0", "redis-server": "RSALv2", "elasticsearch": "SSPL-1.0",
    # permissive (common)
    "express": "MIT", "react": "MIT", "next": "MIT", "fastify": "MIT", "axios": "MIT", "openai": "Apache-2.0", "typescript": "Apache-2.0",
    "lodash": "MIT", "zod": "MIT", "jest": "MIT", "vitest": "MIT", "spring-boot-starter-web": "Apache-2.0", "jackson-databind": "Apache-2.0",
    "gin": "MIT", "gorilla/mux": "BSD-3-Clause", "serde": "MIT OR Apache-2.0", "tokio": "MIT", "reqwest": "MIT OR Apache-2.0",
    "rails": "MIT", "sinatra": "MIT", "faraday": "MIT", "guzzlehttp/guzzle": "MIT", "laravel/framework": "MIT",
    "newtonsoft.json": "MIT", "alamofire": "MIT", "aws-sdk": "Apache-2.0", "@aws-sdk/client-s3": "Apache-2.0",
}


def _lic(name: str, declared: str | None = None) -> str:
    return declared or cs.KNOWN_LICENSES.get(name.lower()) or KNOWN_LICENSES_EXT.get(name.lower()) or "UNKNOWN"


def _fact(tenant: str, rel: str, line: int, name: str, raw: str, declared: str | None = None) -> DependencyFact:
    lic = _lic(name, declared)
    sha = sha256_text(raw)
    return DependencyFact(dep_id=f"dep-{sha256_text(f'{tenant}:{rel}:{line}:{name}')[:12]}", tenant_id=tenant, kind="package", name=name,
                          license=lic, license_class=cs.classify_license(lic), file_path=rel, line=line, snippet=raw.strip()[:200], sha256_hash=sha)


def _line_of(text: str, needle: str) -> int:
    i = text.find(needle)
    return text.count("\n", 0, i) + 1 if i >= 0 else 1


# --------------------------------------------------------------------------- manifest parsers
def parse_manifest(path: Path, rel: str, text: str, tenant: str) -> list[DependencyFact] | None:
    """Return dependency facts for a recognised manifest, or None when the file is not a manifest."""
    n = path.name.lower()
    out: list[DependencyFact] = []
    try:
        if n == "package.json":
            d = json.loads(text)
            for sec in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
                for name, ver in (d.get(sec) or {}).items():
                    out.append(_fact(tenant, rel, _line_of(text, f'"{name}"'), name, f'"{name}": "{ver}"'))
        elif n in {"package-lock.json", "npm-shrinkwrap.json"}:
            d = json.loads(text)
            for key, meta in (d.get("packages") or {}).items():
                if not key or not isinstance(meta, dict):
                    continue
                name = key.split("node_modules/")[-1]
                out.append(_fact(tenant, rel, _line_of(text, f'"{key}"'), name, f'{name}@{meta.get("version", "")}', meta.get("license")))
        elif n == "pyproject.toml":
            d = tomllib.loads(text)
            deps = list((d.get("project") or {}).get("dependencies") or [])
            for sec in ((d.get("project") or {}).get("optional-dependencies") or {}).values():
                deps += list(sec)
            tool = (d.get("tool") or {}).get("poetry") or {}
            for name in (tool.get("dependencies") or {}):
                if name.lower() != "python":
                    deps.append(name)
            for spec in deps:
                name = re.split(r"[<>=!~\[; ]", str(spec).strip(), maxsplit=1)[0].lower().replace("_", "-")
                if name:
                    out.append(_fact(tenant, rel, _line_of(text, str(spec).split("=")[0].split("<")[0].split(">")[0].strip()), name, str(spec)))
        elif n == "go.mod":
            for i, line in enumerate(text.splitlines(), 1):
                m = re.match(r"\s*(?:require\s+)?([\w.\-]+\.[\w.\-]+/[\w./\-]+)\s+v[\w.\-+]+", line)
                if m:
                    out.append(_fact(tenant, rel, i, m.group(1).split("/", 1)[-1] if "github.com" in m.group(1) else m.group(1), line))
        elif n == "cargo.toml":
            d = tomllib.loads(text)
            for sec in ("dependencies", "dev-dependencies", "build-dependencies"):
                for name in (d.get(sec) or {}):
                    out.append(_fact(tenant, rel, _line_of(text, name), name, f"{name} (cargo {sec})"))
        elif n == "gemfile":
            for i, line in enumerate(text.splitlines(), 1):
                m = re.match(r"\s*gem\s+['\"]([\w\-.]+)['\"]", line)
                if m:
                    out.append(_fact(tenant, rel, i, m.group(1), line))
        elif n == "composer.json":
            d = json.loads(text)
            for sec in ("require", "require-dev"):
                for name in (d.get(sec) or {}):
                    if name != "php" and not name.startswith("ext-"):
                        out.append(_fact(tenant, rel, _line_of(text, f'"{name}"'), name, f'"{name}"'))
        elif n == "pom.xml":
            for m in re.finditer(r"<dependency>(.*?)</dependency>", text, re.S):
                a = re.search(r"<artifactId>([^<]+)</artifactId>", m.group(1))
                if a:
                    out.append(_fact(tenant, rel, text.count("\n", 0, m.start()) + 1, a.group(1).strip(), " ".join(m.group(1).split())[:160]))
        elif n in {"build.gradle", "build.gradle.kts"}:
            for i, line in enumerate(text.splitlines(), 1):
                m = re.search(r"(?:implementation|api|compileOnly|runtimeOnly|testImplementation|compile)\s*\(?\s*[\"']([\w.\-]+):([\w.\-]+)(?::[\w.\-]+)?[\"']", line)
                if m:
                    out.append(_fact(tenant, rel, i, m.group(2), line))
        elif n.endswith(".csproj"):
            for i, line in enumerate(text.splitlines(), 1):
                m = re.search(r'<PackageReference\s+Include="([^"]+)"', line)
                if m:
                    out.append(_fact(tenant, rel, i, m.group(1), line))
        elif n == "package.swift":
            for i, line in enumerate(text.splitlines(), 1):
                m = re.search(r'\.package\(\s*url:\s*"[^"]*/([\w\-.]+?)(?:\.git)?"', line)
                if m:
                    out.append(_fact(tenant, rel, i, m.group(1), line))
        else:
            return None
    except (ValueError, tomllib.TOMLDecodeError):
        return []  # manifest present but unparsable: coverage reports the file, never a silent pass
    return out


# --------------------------------------------------------------------------- infrastructure / config facts
_US_REGION = re.compile(r"^(us|usa|northamerica|ca)[-_]|^(us|ca)(east|west|central|south|north)|^(east|west|central|southcentral|northcentral)us\d?$|^us-gov|^canada", re.I)
_EU_REGION = re.compile(r"^(eu|europe|uk)[-_]|^(eu|uk)(west|east|central|north|south)\d?$|^(west|north)europe$|^(uk)(south|west)$|"
                        r"^(france|germany|sweden|norway|switzerland|italy|poland|spain|finland)(central|north|west|south|east|westcentral)?$|^eu$|^europe$", re.I)
REGION_KEY_RE = re.compile(r"(?:^|[\s\"'.\-_/])(?:aws[_-]?)?(?:default[_-]?)?(region|location|zone|availability[_-]?zone|datacenter)\b\s*[:=]\s*[\"']?([A-Za-z0-9\-_]+)", re.I)
REGION_ENV_RE = re.compile(r"\b(AWS_(?:DEFAULT_)?REGION|AZURE_LOCATION|GOOGLE_CLOUD_REGION|GCP_REGION|REGION|DATA_REGION|DEPLOY_REGION)\b\s*[:=]\s*[\"']?([A-Za-z0-9\-_]+)", re.I)
K8S_REGION_RE = re.compile(r"topology\.kubernetes\.io/region[\"']?\s*[:=]\s*[\"']?([A-Za-z0-9\-_]+)")
PROVIDER_RE = re.compile(r"(api\.openai\.com|api\.anthropic\.com|generativelanguage\.googleapis\.com|api\.cohere\.(?:ai|com)|api\.mistral\.ai|"
                         r"[\w.-]*openai\.azure\.com|bedrock-runtime\.[\w-]+\.amazonaws\.com|[\w-]+\.cloud\.databricks\.com|api\.groq\.com)", re.I)
SECRET_RE = re.compile(r"(?i)\b([A-Z0-9_]*(?:API[_-]?KEY|SECRET|TOKEN|PASSWORD|PRIVATE[_-]?KEY)[A-Z0-9_]*)\s*[:=]\s*[\"']?(?!\$|<|\{|your|changeme|xxx|\s|$)([^\s\"']{12,})")


def classify_region(value: str) -> str:
    v = value.strip().strip("\"'").lower()
    if _US_REGION.search(v):
        return "US"
    if _EU_REGION.search(v):
        return "EU_UK"
    return "UNKNOWN"


def is_infra_file(rel: str, name: str, text: str) -> bool:
    n = name.lower()
    low = rel.lower()
    if n.startswith("dockerfile") or n in {"docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml", "serverless.yml",
                                           "serverless.yaml", ".env.example", ".env.sample", ".env.template", "template.yaml", "template.yml"}:
        return True
    if n.endswith((".tf", ".tfvars", ".hcl", ".bicep")):
        return True
    if ".github/workflows/" in low and n.endswith((".yml", ".yaml")):
        return True
    if n.endswith((".yaml", ".yml", ".json")) and ("AWSTemplateFormatVersion" in text[:4000] or re.search(r"^apiVersion:\s*\S+", text[:2000], re.M)
                                                    or "azurerm" in text[:4000]):
        return True
    return False


def scan_infra_file(text: str, rel: str, tenant: str, result) -> None:
    for i, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith(("#", "//")):
            continue
        facts = []
        for rx in (REGION_ENV_RE, REGION_KEY_RE):
            for m in rx.finditer(line):
                val = m.group(2)
                if val and not val.startswith("$") and len(val) >= 2:
                    facts.append(("region", val, classify_region(val)))
        for m in K8S_REGION_RE.finditer(line):
            facts.append(("region", m.group(1), classify_region(m.group(1))))
        for m in PROVIDER_RE.finditer(line):
            host = m.group(1).lower()
            facts.append(("model_provider", host, cs.classify_endpoint("https://" + host)))
        for kind, val, region in facts:
            result.infra_facts.append({"file": rel, "line": i, "kind": kind, "value": val, "region": region})
            if region in {"US", "EU_UK"} or kind == "model_provider":
                tags = ["infra_" + kind] + (["infra_region_us"] if region == "US" else ["infra_region_eu"] if region == "EU_UK" else [])
                result.cards.append(BehavioralCapabilityCard(
                    module_id=f"{rel}::infra:{kind}:{i}", tenant_id=tenant, exact_locator=f"{rel}:{i}-{i}",
                    system_prompt=line.strip()[:200], capability_tags=tags, sha256_hash=sha256_text(line.strip() + rel)))
        m = SECRET_RE.search(line)
        if m:  # name + file only; the secret value is never stored
            result.cards.append(BehavioralCapabilityCard(
                module_id=f"{rel}::infra:secret:{i}", tenant_id=tenant, exact_locator=f"{rel}:{i}-{i}",
                system_prompt=f"hardcoded credential-like value for {m.group(1)} (value withheld)", capability_tags=["infra_hardcoded_secret"],
                sha256_hash=sha256_text(f"{rel}:{i}:{m.group(1)}")))
