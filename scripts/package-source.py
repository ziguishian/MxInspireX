"""Archive relocatable source and shipped resources, never a user workspace."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import zipfile

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {
    "node_modules", "dist", ".venv", "venv", ".git", ".tmp", ".local",
    "workspace-data", "__pycache__", ".pytest_cache", ".vite", ".cache",
    "coverage", "output", "outputs", "logs", "backups",
}
SKIP_TREES = ("docs/examples/", "docs/user-references/", "docs/previews/")
SKIP_EXT = {
    ".pyc", ".pyo", ".log", ".sqlite", ".sqlite3", ".db", ".db3",
    ".pem", ".key", ".p12", ".pfx", ".zip", ".tar", ".gz", ".7z",
    ".dmg", ".pkg", ".exe", ".tsbuildinfo",
}
ROOT_FILES = [
    ".gitignore", ".gitattributes", "AGENTS.md", "README.md", "RUN_IN_CODEX.md",
    "README.en.md", "README.ja.md", "README.ko.md", "README.es.md", "LICENSE",
    "package.json", "package-lock.json", "vitest.config.ts",
]
SECRET_PATTERNS = [
    rb"\bsk-(?:proj-|or-v1-)?[A-Za-z0-9_-]{24,}",
    rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
    rb"\b(?:ghp_|github_pat_)[A-Za-z0-9_]{30,}",
    rb"\bAKIA[0-9A-Z]{16}\b",
]


def source_files():
    selected = list(ROOT_FILES)
    for top in ("apps", "packages", "services", "scripts", "docs"):
        for base, dirs, files in os.walk(ROOT / top, followlinks=False):
            dirs[:] = sorted(
                d for d in dirs
                if d not in SKIP_DIRS and not d.startswith(".")
                and not (str((Path(base) / d).relative_to(ROOT)) + "/").replace("\\", "/").startswith(SKIP_TREES)
            )
            for name in dirs + files:
                if (Path(base) / name).is_symlink():
                    raise ValueError(f"Refusing symlink: {Path(base) / name}")
            for name in files:
                p = Path(base) / name
                rel = p.relative_to(ROOT).as_posix()
                if name.startswith(".") or p.suffix.lower() in SKIP_EXT:
                    continue
                if re.search(r"\.(sqlite3?|db)(?:-wal|-shm|-journal)$", name):
                    continue
                if rel.startswith("scripts/showcase-assets/") and name not in {"manifest.json", "README.md"}:
                    continue
                selected.append(rel)
    return sorted(selected)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=ROOT / "outputs/source-packages")
    args = parser.parse_args()
    now = datetime.now(timezone(timedelta(hours=8)))
    version = json.loads((ROOT / "package.json").read_text())["version"]
    name = f"MxinspireX-{version}-source-{now:%Y%m%d-%H%M%S}"
    output = args.output_dir.resolve() / name
    output.mkdir(parents=True, exist_ok=False)
    archive = output / f"{name}.zip"
    records = []
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for rel in source_files():
            p = ROOT / rel
            data = p.read_bytes()
            if data.startswith(b"SQLite format 3\0"):
                raise ValueError(f"Database detected: {rel}")
            # Only inspect UTF-8 text; never print matched secret values.
            try:
                data.decode("utf-8")
            except UnicodeDecodeError:
                pass
            else:
                if any(re.search(pattern, data) for pattern in SECRET_PATTERNS):
                    raise ValueError(f"Potential credential requires review: {rel}")
            records.append({"path": rel, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
            info = zipfile.ZipInfo.from_file(p, arcname=f"{name}/{rel}")
            z.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=6)
        manifest = {
            "schemaVersion": 1, "version": version, "createdAt": now.isoformat(),
            "sourceFileCount": len(records), "files": records,
            "exclusions": {
                "directories": sorted(SKIP_DIRS), "trees": SKIP_TREES,
                "suffixes": sorted(SKIP_EXT),
                "showcaseAssets": "Only manifest.json and README.md retained; raw media omitted",
            },
        }
        z.writestr(f"{name}/SOURCE_MANIFEST.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None
        entries = z.namelist()
        assert len(entries) == len(set(entries)) == len(records) + 1
        for entry in entries:
            parts = PurePosixPath(entry).parts
            assert parts[0] == name and ".." not in parts
            assert not set(parts[1:]) & SKIP_DIRS
        for record in records:
            data = z.read(f"{name}/{record['path']}")
            assert len(data) == record["bytes"]
            assert hashlib.sha256(data).hexdigest() == record["sha256"]
            assert hashlib.sha256((ROOT / record["path"]).read_bytes()).hexdigest() == record["sha256"]
        skills = json.loads(z.read(f"{name}/services/api/app/builtin_skills/manifest.json"))
        for skill in skills["skills"]:
            for rel, digest in skill["files"].items():
                data = z.read(f"{name}/services/api/app/builtin_skills/{skill['name']}/{rel}")
                assert hashlib.sha256(data).hexdigest() == digest
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (output / "SHA256SUMS.txt").write_text(f"{digest}  {archive.name}\n")
    report = {
        "archive": str(archive), "archiveBytes": archive.stat().st_size, "sha256": digest,
        "sourceFileCount": len(records), "createdAt": now.isoformat(),
        "zipCrc": "passed", "fileHashesAndCurrentSourceMatch": "passed",
        "excludedRuntimeData": "passed", "credentialPatternScan": "passed",
        "builtinSkillManifest": "passed",
        "runtimeVerification": "Run npm run setup:portable and npm run verify:portable in a fresh extracted copy; record actual results separately.",
    }
    (output / "archive-verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
