#!/usr/bin/env sh
# AILANG Parse — local CLI installer.
#
# Installs `docparse` without a git clone, by fetching the published registry
# package (~400KB) rather than the repo archive (~24MB).
#
#   curl -fsSL https://ailang.sunholo.com/docparse/install.sh | sh
#
# The CLI is a wrapper around the `ailang` runtime, so both are installed. Only
# deterministic formats work out of the box; PDF needs poppler, and the local
# OCR backends need uv. Neither is installed for you — they are reported at the
# end with the exact command to fix each.

set -eu

REGISTRY="${AILANG_REGISTRY:-https://storage.googleapis.com/ailang-registry}"
PACKAGE="sunholo/ailang_parse"
DEFAULT_PREFIX="${HOME}/.local/share/ailang-parse"
DEFAULT_BINDIR="${HOME}/.local/bin"
AILANG_INSTALLER="https://ailang.sunholo.com/install.sh"

PREFIX="$DEFAULT_PREFIX"
BINDIR="$DEFAULT_BINDIR"
VERSION=""
TARBALL=""
UNINSTALL=0

die() { printf 'docparse-install: %s\n' "$*" >&2; exit 1; }
info() { printf '  %s\n' "$*"; }
step() { printf '\n==> %s\n' "$*"; }

usage() {
  cat <<EOF
Usage: install.sh [options]

  --version X.Y.Z   Install a specific version (default: latest)
  --prefix DIR      Install root (default: $DEFAULT_PREFIX)
  --bindir DIR      Where to link the executable (default: $DEFAULT_BINDIR)
  --tarball PATH    Install from a local package tarball instead of the
                    registry. Used by CI and for testing an unpublished build.
  --uninstall       Remove the install prefix and the symlink
  -h, --help        This message
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --version) VERSION="${2:-}"; [ -n "$VERSION" ] || die "--version needs a value"; shift 2 ;;
    --prefix)  PREFIX="${2:-}";  [ -n "$PREFIX" ]  || die "--prefix needs a value";  shift 2 ;;
    --bindir)  BINDIR="${2:-}";  [ -n "$BINDIR" ]  || die "--bindir needs a value";  shift 2 ;;
    --tarball) TARBALL="${2:-}"; [ -n "$TARBALL" ] || die "--tarball needs a value"; shift 2 ;;
    --uninstall) UNINSTALL=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; die "unknown option: $1" ;;
  esac
done

# ---------------------------------------------------------------- uninstall
if [ "$UNINSTALL" -eq 1 ]; then
  step "Uninstalling"
  if [ -L "$BINDIR/docparse" ]; then rm -f "$BINDIR/docparse"; info "removed $BINDIR/docparse"; fi
  if [ -d "$PREFIX" ]; then rm -rf "$PREFIX"; info "removed $PREFIX"; fi
  printf '\nDone. The ailang runtime was left alone.\n'
  exit 0
fi

need() { command -v "$1" >/dev/null 2>&1; }
for tool in curl tar; do need "$tool" || die "$tool is required but not on PATH"; done

# ------------------------------------------------------------- ailang runtime
step "Checking the AILANG runtime"
if need ailang; then
  info "ailang found: $(command -v ailang)"
else
  info "not found — installing from $AILANG_INSTALLER"
  curl -fsSL "$AILANG_INSTALLER" | bash || die "the AILANG installer failed"
  # A fresh install commonly lands in ~/.local/bin, which may not be on PATH yet.
  PATH="$HOME/.local/bin:$PATH"; export PATH
  need ailang || die "ailang still not on PATH after install — see $AILANG_INSTALLER"
  info "ailang installed: $(command -v ailang)"
fi

# ------------------------------------------------------------------- version
if [ -n "$TARBALL" ]; then
  [ -f "$TARBALL" ] || die "no such tarball: $TARBALL"
  [ -n "$VERSION" ] || VERSION="local"
  step "Installing from local tarball ($VERSION)"
  info "$TARBALL"
else
  step "Resolving version"
  if [ -z "$VERSION" ]; then
    # Pull `latest` for our package out of the registry index without needing jq.
    VERSION=$(curl -fsSL "$REGISTRY/index.json" \
      | tr ',' '\n' | grep -A2 "\"name\": *\"$PACKAGE\"" | grep '"latest"' \
      | head -1 | sed 's/.*"latest": *"\([^"]*\)".*/\1/')
    [ -n "$VERSION" ] || die "could not resolve the latest version from $REGISTRY/index.json"
    info "latest is $VERSION"
  else
    info "requested $VERSION"
  fi
fi

DEST="$PREFIX/$VERSION"

# --------------------------------------------------------------- fetch/verify
TMP=$(mktemp -d)
# shellcheck disable=SC2064
trap "rm -rf '$TMP'" EXIT INT TERM

if [ -n "$TARBALL" ]; then
  cp "$TARBALL" "$TMP/package.tar.gz"
else
  step "Downloading"
  BASE="$REGISTRY/packages/$PACKAGE/$VERSION"
  curl -fsSL "$BASE/package.tar.gz" -o "$TMP/package.tar.gz" \
    || die "download failed: $BASE/package.tar.gz"
  info "$(wc -c < "$TMP/package.tar.gz" | tr -d ' ') bytes"

  # Verify against the registry's own metadata. A checksum tool missing is a
  # warning, not a failure — but a MISMATCH always aborts.
  SUMTOOL=""
  if need sha256sum; then SUMTOOL="sha256sum"; elif need shasum; then SUMTOOL="shasum -a 256"; fi
  if [ -n "$SUMTOOL" ]; then
    EXPECTED=$(curl -fsSL "$BASE/metadata.json" 2>/dev/null \
      | tr ',' '\n' | grep -i 'sha256' | head -1 \
      | sed 's/.*[":]\([0-9a-f]\{64\}\).*/\1/' | grep -E '^[0-9a-f]{64}$' || true)
    ACTUAL=$($SUMTOOL "$TMP/package.tar.gz" | cut -d' ' -f1)
    if [ -n "$EXPECTED" ]; then
      [ "$EXPECTED" = "$ACTUAL" ] || die "sha256 mismatch: expected $EXPECTED, got $ACTUAL"
      info "sha256 verified"
    else
      info "no sha256 in metadata.json — skipping verification"
    fi
  else
    info "no sha256sum/shasum available — skipping verification"
  fi
fi

# ------------------------------------------------------------------- unpack
step "Installing to $DEST"
[ -d "$DEST" ] && rm -rf "$DEST"
mkdir -p "$DEST"
tar xzf "$TMP/package.tar.gz" -C "$DEST"
[ -f "$DEST/docparse/main.ail" ] || die "package is missing docparse/main.ail — wrong tarball?"

# Materialise the runtime layout from assets/. The package ships these under
# assets/ because that is the only path CreateTarball bundles verbatim; the
# wrapper and adapter have to end up where the code expects them.
[ -f "$DEST/assets/bin/docparse" ] \
  || die "package is missing assets/bin/docparse — published before v0.40.0?"
mkdir -p "$DEST/bin" "$DEST/docparse/services/pdf_backends"
cp "$DEST/assets/bin/docparse" "$DEST/bin/docparse"
# tar entries are written with mode 0644 by the publisher, so restore the bit.
chmod +x "$DEST/bin/docparse"
if [ -d "$DEST/assets/pdf_backends" ]; then
  cp "$DEST/assets/pdf_backends/"* "$DEST/docparse/services/pdf_backends/" 2>/dev/null || true
fi
[ -f "$DEST/assets/backends-pyproject.toml" ] \
  && cp "$DEST/assets/backends-pyproject.toml" "$DEST/pyproject.toml"
info "unpacked"

# --------------------------------------------------------------------- lock
step "Resolving dependencies"
info "ailang lock (needs network; the package declares 5 transitive deps)"
( cd "$DEST" && ailang lock >/dev/null 2>&1 ) \
  || die "ailang lock failed in $DEST — this step needs network access"
info "locked"

# ------------------------------------------------------------------- symlink
step "Linking"
mkdir -p "$BINDIR"
ln -sf "$DEST/bin/docparse" "$BINDIR/docparse"
info "$BINDIR/docparse -> $DEST/bin/docparse"

case ":$PATH:" in
  *":$BINDIR:"*) ;;
  *) info "NOTE: $BINDIR is not on your PATH. Add it:"
     info "    export PATH=\"$BINDIR:\$PATH\"" ;;
esac

# ------------------------------------------------------------------ preflight
step "Optional dependencies"
MISSING=0
if need pdftotext; then
  info "pdftotext   ok   (PDF, default backend)"
else
  MISSING=1
  info "pdftotext   MISSING — PDFs will not parse"
  if [ "$(uname -s)" = "Darwin" ]; then
    info "            fix: brew install poppler"
  else
    info "            fix: sudo apt-get install poppler-utils"
  fi
fi
if need uv; then
  info "uv          ok   (local OCR backends)"
  info "            run: docparse --install-backends"
else
  MISSING=1
  info "uv          MISSING — docling/liteparse unavailable, and a SCANNED PDF"
  info "            fails even on the default backend, because pdftotext"
  info "            escalates to docling when there is no text layer."
  info "            fix: curl -LsSf https://astral.sh/uv/install.sh | sh"
  info "            then: docparse --install-backends"
fi
info "AI backends authenticate with Google ADC, not an API key:"
info "            gcloud auth application-default login"

printf '\n'
if [ "$MISSING" -eq 1 ]; then
  printf 'Installed, with optional dependencies missing (see above).\n'
else
  printf 'Installed.\n'
fi
printf 'Try:  docparse --help\n'
printf '      docparse yourfile.docx --output-dir .\n'
