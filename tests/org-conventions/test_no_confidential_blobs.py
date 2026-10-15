"""Org gate: a PR must not ADD confidential documents or large binaries.

Measured origin (2026-09-06): a long PDF whose appendix carried other institutions' forms,
self-described as privileged/confidential, was committed to a project repo. Scoped to files
ADDED in the PR range; existing history is out of scope (that is a separate cleanup).
Escape hatch: list the path in `.confidential-allow` at the repo root — one POSIX-style path
per line, relative to the repo root (no leading `./`, no backslashes).

Run by reusable workflow .github/workflows/org-checks.yml (suite: conventions) on every PR.
To run locally:  REPO_ROOT=<repo> pytest tests/org-conventions/test_no_confidential_blobs.py -v --timeout=30
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from _orggate import repo_root, range_base, added_files

MAX_BINARY_BYTES = 1 * 1024 * 1024
CONFIDENTIAL_MARKERS = (
    r"\bconfidential\b", r"\bprivileged\b", r"\btrade secret", r"\bnot for distribution\b",
    r"\bdo not distribute\b", r"\bproprietary and confidential\b",
)
DOC_SUFFIXES = {".pdf", ".docx", ".pptx"}
# Private-key material: a PEM header anywhere in the first 8 KiB (RSA/EC/DSA/OPENSSH/ENCRYPTED/
# PGP ... BLOCK), or a binary keystore by suffix. Public certs, public keys and CSRs do not
# match — only PRIVATE KEY does. Measured origin (upstream review): an added 93-byte deploy.pem
# passed, and most consumer repos run no secret scanner.
PRIVATE_KEY_RE = re.compile(rb"-----BEGIN [A-Z0-9 ]*PRIVATE KEY( BLOCK)?-----")
KEYSTORE_SUFFIXES = {".p12", ".pfx", ".jks", ".keystore"}
ALLOW_HINT = "if this file is meant to be in the repo, list its path in .confidential-allow (POSIX path relative to the repo root)"


def allowlist(root: Path) -> set[str]:
    f = root / ".confidential-allow"
    return {l.strip() for l in f.read_text().splitlines() if l.strip() and not l.startswith("#")} if f.exists() else set()


def is_binary(p: Path) -> bool:
    return b"\0" in p.read_bytes()[:8192]


def doc_text(p: Path) -> str:
    if p.suffix.lower() == ".pdf":
        from pypdf import PdfReader  # installed by org-checks.yml
        return "\n".join((pg.extract_text() or "") for pg in PdfReader(str(p)).pages)
    if p.suffix.lower() in {".docx", ".pptx"}:
        import zipfile
        with zipfile.ZipFile(p) as z:
            return "\n".join(z.read(n).decode("utf8", "ignore") for n in z.namelist() if n.endswith(".xml"))
    return ""


def markers_in(text: str) -> list[str]:
    return [m for m in CONFIDENTIAL_MARKERS if re.search(m, text, flags=re.I)]


def is_private_key(p: Path) -> bool:
    return p.suffix.lower() in KEYSTORE_SUFFIXES or bool(PRIVATE_KEY_RE.search(p.read_bytes()[:8192]))


def check_file(p: Path, root: Path) -> str | None:
    """Return a failure reason or None. Every finding names `.confidential-allow`: the allowlist
    applies to all of them, and docs/org-gates.md promises the message says so."""
    rel = str(p.relative_to(root))
    if rel in allowlist(root):
        return None
    if is_private_key(p):
        return f"{rel}: private key material added — rotate it if it was ever real; {ALLOW_HINT}"
    if p.suffix.lower() in DOC_SUFFIXES:
        try:
            hits = markers_in(doc_text(p))
        except Exception as exc:
            # Fail CLOSED: a corrupt or password-protected document can't be scanned for
            # markers, so it can't be waved through either — report it like any other
            # finding instead of letting the exception crash the whole gate.
            return (
                f"{rel}: could not extract text ({exc.__class__.__name__}) — corrupt or encrypted; "
                f"manual review required; {ALLOW_HINT}"
            )
        if hits:
            return f"{rel}: document contains confidentiality markers {hits} — {ALLOW_HINT}"
    if is_binary(p) and p.stat().st_size > MAX_BINARY_BYTES:
        return (
            f"{rel}: binary of {p.stat().st_size} bytes added (> {MAX_BINARY_BYTES}); use a release "
            f"asset or Drive link, or {ALLOW_HINT}"
        )
    return None


def test_pr_adds_no_confidential_or_large_blob():
    root = repo_root()
    # is_file(), not exists(): a gitlink (mode 160000 submodule) is reported by
    # `git diff --name-only` as an added path and materialised by actions/checkout as an
    # EMPTY DIRECTORY, for which exists() is True. read_bytes() on it then raised
    # IsADirectoryError and killed the whole gate with a traceback instead of reporting —
    # measured on 2 of 29 replayed PRs (6.9%), each of which
    # reports 5 legitimate oversize findings once the walk survives.
    failures = [r for p in added_files(root, range_base(root)) if p.is_file() and (r := check_file(p, root))]
    assert not failures, "\n".join(failures)


# ---- positive controls -----------------------------------------------------------------
def _pdf_with_text(path: Path, text: str) -> None:
    """A minimal but structurally VALID single-page PDF with a real xref table, so pypdf
    reads it cleanly (no warnings) and extract_text() returns exactly `text`."""
    content = f"BT /F1 12 Tf 10 100 Td ({text}) Tj ET".encode()
    objs = [
        b"<</Type/Catalog/Pages 2 0 R>>",
        b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
        b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>",
        b"<</Length " + str(len(content)).encode() + b">>stream\n" + content + b"\nendstream",
        b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
    ]
    body = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, o in enumerate(objs, start=1):
        offsets.append(len(body))
        body += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    xref_offset = len(body)
    n = len(objs) + 1
    xref = bytearray(f"xref\n0 {n}\n".encode())
    xref += b"0000000000 65535 f \n"
    for off in offsets:
        xref += f"{off:010d} 00000 n \n".encode()
    trailer = f"trailer\n<</Size {n}/Root 1 0 R>>\nstartxref\n{xref_offset}\n%%EOF\n".encode()
    path.write_bytes(bytes(body) + bytes(xref) + trailer)


def test_gate_bites_on_a_confidential_pdf(tmp_path: Path):
    p = tmp_path / "forms.pdf"; _pdf_with_text(p, "This response may contain trade secrets and is CONFIDENTIAL")
    assert check_file(p, tmp_path) and "confidentiality markers" in check_file(p, tmp_path)


def test_gate_bites_on_a_large_binary(tmp_path: Path):
    import os
    p = tmp_path / "model.bin"; p.write_bytes(b"\0" + os.urandom(MAX_BINARY_BYTES + 1))
    assert check_file(p, tmp_path) and "binary of" in check_file(p, tmp_path)


def test_gate_passes_a_plain_pdf_and_respects_allowlist(tmp_path: Path):
    p = tmp_path / "paper.pdf"; _pdf_with_text(p, "Distributed quantum sensing with GKP states")
    assert check_file(p, tmp_path) is None
    q = tmp_path / "forms.pdf"; _pdf_with_text(q, "CONFIDENTIAL")
    (tmp_path / ".confidential-allow").write_text("forms.pdf\n")
    assert check_file(q, tmp_path) is None


def test_gate_reports_a_truncated_pdf_as_a_finding_not_a_crash(tmp_path: Path):
    p = tmp_path / "broken.pdf"
    p.write_bytes(b"%PDF-1.4\n1 0 obj<<garbage")
    result = check_file(p, tmp_path)
    assert result and "could not extract text" in result and "corrupt or encrypted" in result


def test_gate_reports_an_encrypted_pdf_as_a_finding_not_a_crash(tmp_path: Path):
    from pypdf import PdfReader, PdfWriter
    plain = tmp_path / "plain.pdf"; _pdf_with_text(plain, "not confidential at all")
    w = PdfWriter(); w.append(PdfReader(str(plain)))
    # RC4-128 needs no extra dependency (unlike AES, which pypdf implements only via the
    # optional `cryptography` package) — it still exercises the identical fail-closed path:
    # PdfReader succeeds, extract_text() raises FileNotDecryptedError with no password given.
    w.encrypt(user_password="s3cret", owner_password="0wner", algorithm="RC4-128")
    p = tmp_path / "encrypted.pdf"
    with open(p, "wb") as f:
        w.write(f)
    result = check_file(p, tmp_path)
    assert result and "could not extract text" in result and "corrupt or encrypted" in result


def test_a_submodule_directory_does_not_crash_the_walk(tmp_path: Path):
    """The measured gate bug: an added gitlink path is a DIRECTORY on disk.

    check_file() must never be reached for it — `p.is_file()` in the sweep is what stops
    `read_bytes()` from raising IsADirectoryError and taking every other finding down with
    it. This asserts the filter directly, plus that the crash is real without it.
    """
    gitlink = tmp_path / "projects" / "some-submodule"
    gitlink.mkdir(parents=True)
    big = tmp_path / "big.npz"
    big.write_bytes(b"\0" + b"x" * (MAX_BINARY_BYTES + 1))

    assert gitlink.exists() and not gitlink.is_file()   # exists() is why the old sweep died
    with pytest.raises(IsADirectoryError):
        check_file(gitlink, tmp_path)

    survivors = [r for p in (gitlink, big) if p.is_file() and (r := check_file(p, tmp_path))]
    assert len(survivors) == 1 and "big.npz" in survivors[0]


# ---- private-key material (upstream review, "should fix before active") --------------------
FAKE_PEM = "-----BEGIN RSA PRIVATE KEY-----\nNOTAREALKEY\n-----END RSA PRIVATE KEY-----\n"
FAKE_CERT = (
    "-----BEGIN CERTIFICATE-----\nMIIBszCCAVwCCQDNOTAREALCERT\n-----END CERTIFICATE-----\n"
)


@pytest.mark.parametrize("name", ["deploy.pem", "id_rsa", "keys/service.key", "notes.txt"])
def test_gate_bites_on_added_private_key_material_whatever_the_suffix(tmp_path: Path, name: str):
    # The review measured a 93-byte deploy.pem passing: check_file only knew document
    # markers and oversize binaries, and most consumer repos run no secret scanner.
    p = tmp_path / name; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(FAKE_PEM)
    r = check_file(p, tmp_path)
    assert r and "private key material added" in r and ".confidential-allow" in r, r


@pytest.mark.parametrize("header", [
    "-----BEGIN PRIVATE KEY-----", "-----BEGIN EC PRIVATE KEY-----", "-----BEGIN OPENSSH PRIVATE KEY-----",
    "-----BEGIN ENCRYPTED PRIVATE KEY-----", "-----BEGIN DSA PRIVATE KEY-----", "-----BEGIN PGP PRIVATE KEY BLOCK-----",
])
def test_private_key_rule_covers_the_common_pem_labels(tmp_path: Path, header: str):
    p = tmp_path / "k.pem"; p.write_text(f"{header}\nNOTAREALKEY\n")
    assert check_file(p, tmp_path) and "private key material" in check_file(p, tmp_path)


def test_private_key_header_late_in_the_first_8_kib_is_still_caught(tmp_path: Path):
    p = tmp_path / "bundle.pem"; p.write_text("x" * 8000 + "\n" + FAKE_PEM)
    assert check_file(p, tmp_path) and "private key material" in check_file(p, tmp_path)


@pytest.mark.parametrize("suffix", [".p12", ".pfx", ".jks", ".keystore", ".PFX"])
def test_gate_bites_on_binary_keystore_suffixes(tmp_path: Path, suffix: str):
    p = tmp_path / f"trust{suffix}"; p.write_bytes(b"\x30\x82\x01\x00" + b"\0" * 64)
    r = check_file(p, tmp_path)
    assert r and "private key material added" in r and ".confidential-allow" in r, r


def test_a_public_certificate_pem_passes(tmp_path: Path):
    p = tmp_path / "ca-bundle.pem"; p.write_text(FAKE_CERT)
    assert check_file(p, tmp_path) is None


def test_a_public_key_and_a_certificate_request_pass(tmp_path: Path):
    for name, header in (("id_rsa.pub", "ssh-rsa AAAAB3NOTAREALKEY"), ("req.csr", "-----BEGIN CERTIFICATE REQUEST-----"),
                         ("pub.pem", "-----BEGIN PUBLIC KEY-----")):
        p = tmp_path / name; p.write_text(header + "\nNOTAREALKEY\n")
        assert check_file(p, tmp_path) is None, name


def test_private_key_rule_respects_the_allowlist(tmp_path: Path):
    p = tmp_path / "fixtures" / "test.pem"; p.parent.mkdir(); p.write_text(FAKE_PEM)
    (tmp_path / ".confidential-allow").write_text("fixtures/test.pem\n")
    assert check_file(p, tmp_path) is None


# ---- every finding names the escape hatch (docs/org-gates.md promises it) -------------
def test_size_and_corrupt_findings_name_the_allowlist_file(tmp_path: Path):
    import os
    big = tmp_path / "model.bin"; big.write_bytes(b"\0" + os.urandom(MAX_BINARY_BYTES + 1))
    assert ".confidential-allow" in check_file(big, tmp_path)
    broken = tmp_path / "broken.pdf"; broken.write_bytes(b"%PDF-1.4\n1 0 obj<<garbage")
    assert ".confidential-allow" in check_file(broken, tmp_path)
