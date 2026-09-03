#!/usr/bin/env python3
"""Build a package tarball using ailang publish's exact include rules.

`ailang publish --dry-run` reports a tarball's size and hash but does not write
it anywhere, and the real one only exists after a release. CI needs the artifact
a *user* would download in order to test installing from it, so this mirrors
CreateTarball (ailang/internal/pkg/tarball.go):

    include  ailang.toml, *.ail, AGENT.md, assets/**
    skip     directories named .git, tests, test
    mode     0644 on every entry (which is why install.sh chmod +x's the wrapper)
    order    sorted, mtime zeroed — deterministic

If those rules ever drift upstream, this file is what to update; the install
smoke workflow is what will notice.
"""
import io
import os
import sys
import tarfile

INCLUDE_EXACT = {"ailang.toml", "AGENT.md"}
SKIP_DIRS = {".git", "tests", "test"}
ASSETS = "assets/"


def collect(root="."):
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            rel = os.path.relpath(os.path.join(dirpath, name), root).replace(os.sep, "/")
            if rel in INCLUDE_EXACT or rel.endswith(".ail") or rel.startswith(ASSETS):
                found.append(rel)
    return sorted(found)


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else "package.tar.gz"
    files = collect()
    if not any(f.startswith(ASSETS) for f in files):
        sys.exit("refusing to build: no assets/ files — the CLI would not ship")
    with tarfile.open(out, "w:gz") as tf:
        for rel in files:
            with open(rel, "rb") as fh:
                data = fh.read()
            info = tarfile.TarInfo(rel)
            info.size = len(data)
            info.mode = 0o644
            info.mtime = 0
            tf.addfile(info, io.BytesIO(data))
    print(f"{out}: {os.path.getsize(out)} bytes, {len(files)} entries")


if __name__ == "__main__":
    main()
