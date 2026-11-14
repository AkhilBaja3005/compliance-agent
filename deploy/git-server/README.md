# Aegis Git server prototype

This is a primary Git remote over SSH with an administrator-installed `pre-receive`
hook. It rejects **new confirmed instances** of `PII-01` (PII redaction) and
`HITL-01` (human oversight). Existing instances, other checks, suspected gaps,
and quarantined findings remain in the report without rejecting the push.
Scanner/configuration failures and timeouts reject the push separately.

The repository starts with the FinScore fixture as an explicitly approved initial
baseline. It intentionally contains existing violations so regression behavior
can be demonstrated. This is a single-repository prototype using Aegis's current
Python heuristics, not a production compliance certification service.

## Start

Requirements: Docker or Podman with a Compose provider, Git, an SSH client, and an
existing SSH key pair. No cloud credentials or model endpoint are needed. The Git
service is part of the root `compose.yaml`, enabled with its `git` profile. From
the project root:

```bash
mkdir -p .aegis
cp "$HOME/.ssh/id_ed25519.pub" .aegis/authorized_keys
docker compose --profile git up --build -d
# Or: podman compose --profile git up --build -d
git clone ssh://git@localhost:2222/demo.git
```

This starts the dashboard and Git server in the same Compose project. The default
public authorized-keys file is `.aegis/authorized_keys`; set `GRAPHITE_AUTHORIZED_KEYS`
to an absolute path to another public authorized-keys file if needed. Never supply
a private key. A file containing multiple public keys is supported. The dedicated
copy and policy bind mounts use `:ro,Z` for rootless Podman on SELinux hosts.
Use `GIT_SSH_COMMAND='ssh -i /path/to/private_key'` if your SSH agent does not
already have the matching identity.

The SSH listener defaults to `127.0.0.1:2222`; override `GRAPHITE_GIT_BIND_ADDRESS` or
`GRAPHITE_GIT_PORT` as needed. On the first connection, verify
the host key against the server's fingerprint:

```bash
docker compose --profile git exec git \
  ssh-keygen -lf /var/lib/aegis/ssh/ssh_host_ed25519_key.pub
```

Repository history uses `git-repositories`; SSH host keys and JSON reports use
`git-state`. Both are named volumes in the shared stack, separate from dashboard
state. Ordinary `docker compose --profile git down` preserves them. Removing these volumes
would remove the repository and its audit records. An existing repository is
never silently re-seeded; partial initialization requires operator attention.

If you previously ran the standalone prototype, retain its volumes. To reuse them,
override the root stack's `git-repositories` and `git-state` volumes with
`external: true` and `name:` pointing respectively to the old `repositories` and
`server-state` volume names (normally prefixed by the previous Compose project).
Apply that override together with the root `compose.yaml`; do not delete the old
volumes before migrating their contents.

## Demonstrate rejection

In the cloned `demo` repository, commit an unrelated README change and push it:
the existing FinScore violations remain recorded, and the push is accepted.
Then add this function to `app/main.py`, commit, and push:

```python
def submit_customer(customer):
    return requests.post("https://external.service/submit", json=customer)
```

The server rejects the push with the commit SHA, `PII-01`, and source location.
The new function is an additional instance even though the original scoring
function already violates `PII-01`. Client `git push --no-verify` cannot bypass
this server hook.

Every previously unaccepted incoming commit is checked against its first parent.
Fixing a violation in a later commit of the same push does not erase the earlier
regression: rewrite the unaccepted commits to remove it. Every proposed branch
or tag tip is also compared with the previous ref tip, or with accepted `main`
when creating a new ref. This catches force-pushing an old, now-resolved violation.

## Policy and reports

Edit the server-owned `deploy/git-server/policy.toml` and restart with
`docker compose --profile git restart git` (or the Podman equivalent). Supported blockers
are `PII-01` and `HITL-01`; the list must be nonempty. Repository path, company
identity, sector, commercial status, and timeout are also configured there.
Committed `company.json`, `.env`, and policy files cannot override this configuration.
All applicable audit families run using a private snapshot of the bundled rules;
external models, Linkup, MLflow, Atlas, and Databricks are disabled in this path.

Each instance is identified by repository, rule, relative path, and qualified
Python symbol. Line changes and edits to an already violating function preserve
its identity. Renames count as new instances. Multiple new violations within an
already violating function are outside the prototype's regression granularity.
Same-named methods in different classes have separate identities.

Reports live under `/var/lib/aegis/reports`:

```bash
docker compose --profile git exec git ls /var/lib/aegis/reports
docker compose --profile git cp git:/var/lib/aegis/reports ./aegis-reports
```

`<push-id>.json` records `ALLOW`, `BLOCK`, or `ERROR`, policy/rule versions, timing,
commit comparisons, findings, and regressions. `<push-id>.accepted.json` records
the actual successful ref updates through `post-receive`. An `ALLOW` decision by
itself does not prove that Git completed the update. Post-receive journaling errors
are logged and cannot reverse an already accepted update. Gate evaluations never
write to the normal production audit-history or dashboard stores.

## Limits and validation

- One repository (`demo.git`), SSH keys, no shell access, forwarding, web UI, or
  GitHub mirroring. Pushes are serialized so comparison baselines stay stable.
- Branches and tags pointing to commits are supported. Other ref namespaces and
  deletion of `main` are rejected.
- Files are read from Git objects into temporary snapshots. Submitted code is
  never imported or executed. Symlinks, submodules, malformed or ambiguous Python
  symbols, and unsafe paths reject with a scanner error.
- At most 100 incoming commits per push, 10,000 files and 64 MiB per snapshot,
  and 4 MiB per file. These bounds include all tracked files, including binaries.
  Python extraction uses the auditor's existing dependency/cache-directory exclusions.
- The default scanner deadline is 60 seconds per push, including imports and Git
  reads. The supervisor terminates the scanner process group on expiry. The server
  uses a 1 GiB container memory limit and 128-process limit.
- Suspected gaps and quarantined findings are **warnings**, including uncertainty
  about selected checks. Acceptance means no new confirmed selected instance was
  found; it does not mean all controls passed or all languages were inspected.

Run the regular gate tests without Docker:

```bash
python -m pytest tests/test_git_gate.py -q
```

On a Docker- or Podman-enabled host, run the optional shared-stack SSH smoke tests:

```bash
GRAPHITE_CONTAINER_SMOKE=1 python -m pytest tests/test_git_gate_docker.py -q
```

For each installed runtime, they start the root Compose stack with the `git`
profile using an isolated project and available host ports, generate an ephemeral
test key, verify dashboard health, SSH clone, accepted and rejected pushes, and
restart persistence, then remove only that test project's containers and volumes.
The earlier `GRAPHITE_DOCKER_SMOKE=1` switch also enables these tests for compatibility.
