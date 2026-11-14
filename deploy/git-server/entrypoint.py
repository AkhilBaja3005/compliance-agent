"""Provision the demo once; restart without changing accepted history."""
import os
from pathlib import Path
import pwd
import shutil
import subprocess
import tempfile


def git(*args, cwd=None):
    subprocess.run(["git", *args], cwd=cwd, check=True)


def initialize_repository(repo: Path, seed: Path, hooks: Path) -> None:
    marker = repo / "aegis-initialized"
    if not repo.exists():
        git("init", "--bare", "--initial-branch=main", str(repo))
        with tempfile.TemporaryDirectory(prefix="aegis_seed_") as tmp:
            work = Path(tmp) / "seed"
            shutil.copytree(seed, work, ignore=shutil.ignore_patterns(".git", "__pycache__"))
            git("init", "--initial-branch=main", cwd=work)
            git("add", ".", cwd=work)
            git("-c", "user.name=Aegis", "-c", "user.email=aegis@localhost", "commit", "-m",
                "Administrator-approved initial baseline", cwd=work)
            git("push", str(repo), "main", cwd=work)
        marker.write_text("Initial fixture import is approved existing debt.\n")
    elif not marker.is_file():
        raise RuntimeError("Existing repository lacks initialization marker; refusing to overwrite it")
    prefix = ("-c", f"safe.directory={repo}", "--git-dir", str(repo))
    git(*prefix, "config", "core.hooksPath", str(hooks))
    git(*prefix, "config", "receive.fsckObjects", "true")
    git(*prefix, "symbolic-ref", "HEAD", "refs/heads/main")


def main():
    from src.git_gate.policy import Policy

    policy = Policy.load(Path("/etc/aegis/policy.toml"))
    if Path(policy.repository) != Path("/srv/git/demo.git"):
        raise RuntimeError("The prototype serves only /srv/git/demo.git")
    keys = Path("/keys/authorized_keys")
    if not keys.is_file() or not keys.read_text().strip():
        raise RuntimeError("Mount a nonempty public authorized_keys file at /keys/authorized_keys")
    ssh = Path("/home/git/.ssh")
    ssh.mkdir(mode=0o755, exist_ok=True)
    shutil.copyfile(keys, ssh / "authorized_keys")
    os.chmod(ssh / "authorized_keys", 0o644)
    host = Path("/var/lib/aegis/ssh/ssh_host_ed25519_key")
    host.parent.mkdir(parents=True, exist_ok=True)
    if not host.exists():
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(host)], check=True)
    repo = Path("/srv/git/demo.git")
    initialize_repository(repo, Path("/opt/aegis/seed"), Path("/opt/aegis/hooks"))
    user = pwd.getpwnam("git")
    for directory in (Path("/srv/git"), Path("/var/lib/aegis/reports")):
        directory.mkdir(parents=True, exist_ok=True)
        os.chown(directory, user.pw_uid, user.pw_gid)
        for root, dirs, files in os.walk(directory):
            for name in dirs + files:
                os.chown(Path(root) / name, user.pw_uid, user.pw_gid, follow_symlinks=False)
    os.execv("/usr/sbin/sshd", ["sshd", "-D", "-e", "-f", "/etc/ssh/aegis_sshd_config"])


if __name__ == "__main__":
    main()
