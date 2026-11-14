#!/usr/local/bin/python
"""Restrict SSH to Git transport and serialize writes while baselines are evaluated."""
import fcntl
import os
import shlex
import subprocess
import sys
import uuid


def command(original: str) -> list[str]:
    args = shlex.split(original)
    if (len(args) != 2 or args[0] not in {"git-upload-pack", "git-receive-pack"}
            or args[1] not in {"demo.git", "/demo.git", "/srv/git/demo.git"}):
        raise ValueError("Only clone/fetch/push for demo.git is allowed")
    return [args[0], "/srv/git/demo.git"]


def main() -> int:
    try:
        args = command(os.environ.get("SSH_ORIGINAL_COMMAND", ""))
    except ValueError:
        print("AEGIS: SSH is restricted to Git operations on demo.git", file=sys.stderr)
        return 1
    env = {"PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8",
           "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null", "AEGIS_PUSH_ID": uuid.uuid4().hex}
    if args[0] == "git-receive-pack":
        with open("/srv/git/.push.lock", "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            return subprocess.call(args, env=env)
    return subprocess.call(args, env=env)


if __name__ == "__main__":
    raise SystemExit(main())
