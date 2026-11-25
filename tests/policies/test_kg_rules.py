"""The two knowledge-graph rules of 25 November 2026 exist, carry the owner's words, and leak nothing.

This repo is public. The private organization keeps fuller copies of these rules, with host
names, project names and measured baselines; none of that belongs here. The leak test below is
the reason this file exists, as much as the content checks.

The private names are listed only as SHA-256 digests of lower-cased tokens, so that this file
does not publish the very names it guards against. To add one, append
`hashlib.sha256(token.lower().encode()).hexdigest()`. A token is matched as a whole word, as a
dot-separated suffix (so a subdomain of a listed domain is caught), and as any run of its
hyphen- or underscore-separated parts (so a longer name built on a listed one is caught). Names
glued to other letters with no separator are not caught.

The synthetic values in the positive control are assembled at run time, so that this file can
scan itself without tripping on them.

Run locally: pytest tests/policies/test_kg_rules.py -v --timeout=30
"""
from pathlib import Path
import hashlib
import re

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPINE = ROOT / "LEAN4_SPINE_POLICY.md"
COMPAT = ROOT / "KNOWLEDGE_FORMAT_COMPATIBILITY_POLICY.md"
README = ROOT / "README.md"
THIS_FILE = Path(__file__).resolve()

# The upstream revisions the compatibility policy says were read. Pinned exactly.
PINNED_REVISIONS = (
    "0003e7f3ec273f5caf84849850d560b12e9527e4",  # GoogleCloudPlatform/knowledge-catalog okf/ (frozen v0.2)
    "8a8ff87bfd3847c34c9ddd4fbfd9296be2aee4a3",  # GoogleCloudPlatform/open-knowledge-format (deprecated)
    "527e81aff55992be21507e97004286789126f88c",  # open-knowledge-format/open-knowledge-format (v0.3)
    "808987c5daa4da150e38ecc87f5e4ed6cdfdc0c9",  # zach-blumenfeld/knowledge-index
)

# Private host, project, schema and person names (23 digests), then two harmless canaries that
# the positive control uses: a name and a domain.
PRIVATE_TOKEN_DIGESTS = frozenset({
    "66335200c714f0f9e82c981e30cadb3515185f4ce42a860c966eeb9feed43f89",
    "2d69120f4a37384f5b712c447e7bd630eda348a5ad96ce3356900d6410935b56",
    "12a1120ca7f8c9d79d2e1a74ab9a4d7b99a2d12d055180d50ccb5b6d3cf52729",
    "f7e1cf4d9d4735669c30ab02f7b07834624d0f282a1e7097aa7e56ad50f5ba52",
    "35ea83073936d91ac673510782c94df9d4707dbd5921e51a2026874a77f76773",
    "3be68ebc1d8166f03a4550a62ec88c7800857bf5cb5965b61a9d5e5bd789f8a8",
    "5d3e88e88dd144aea37f55a7557215408cac826fb01ef94270e7ef7446277d08",
    "d93328eed7290f8d18512b795501dbcaa1cfe4c01618b595073d0f51898b733a",
    "5e83f5d4e4c9026b56b45ddc8acfe43eb15638c0237e25f64184f8ed985aa740",
    "18732e3599777f5a82c78ea7d44f6feff62e21c69e2fe4bc5f42abbebc8a0c35",
    "728200129eccb567a9b6483bd99adde616f72aaa3a38ed0d68829b4d199e2907",
    "e21331ee56ae0718765b3bed7532bab712ab9cda82eca8a16d9eedb8adeb411b",
    "0a0a80b74c33b9707b29e2d3e843ea0bdc28b9b2177791086fcc2e44d6063225",
    "aefa2523dbd273d7f0b0345b915723939e8cd7aa84209ccbefde79a910cbaabf",
    "27279e1d41148ec1d9330dac341cd319a94783c32fe8e2906a7ff4a645139ffb",
    "81e4206f159d715c585bea6c5e56c4c619a75f4dd8a0e7e8104b0d3a84cffa10",
    "1cf6db73088a24c0fb75e79d41b322d2ebf1e315051453be8a53a31572383f70",
    "5f290f77490acf0844fa2d07bca0b3d982e6bd37e0de3bd59aca6668dc8457a6",
    "c4627fb4b965e8d55b0c2838c6944ff7c903c2fac2ddb6597a46aa0089102f27",
    "094d65f0d50d2ba98a19aeaaf2fbd116a3bc824a5d4ad2f85a506d07828a1b5e",
    "d7f133ed575d75d25430302ee79deefc2f741822421becc0f09d3a10e56450d0",
    "c93c10ad8e3136d139c956e8519049addafabadd9fe74ca7c1685014aee7925f",
    "bc132cc70bf7a89380167b1fede1995c0c97fe90e0313590677ad7958f40398d",
    "64d6b927ba135c0b5e7fa9cf85e35e072e77e477573b49b2c35bb3328a2f10d0",
})
DIGEST_LINE = re.compile(r'^\s*"[0-9a-f]{64}",\s*$')

# Generic shapes that identify private infrastructure or private measurements.
PRIVATE_SHAPES = (
    r"\b100\.\d{1,3}\.\d{1,3}\.\d{1,3}\b",          # CGNAT-range (100.x) addresses
    r"\b\d{1,3}(?:,\d{3})+\b",                       # counts with thousands separators
    r"\b(?!(?:19|20)\d\d\b)\d{4,}\b",                # counts without separators (years exempt)
    r"github\.com/(?!open-knowledge-format/|GoogleCloudPlatform/|zach-blumenfeld/)[\w.-]+/",
)


def _candidates(text: str) -> set[str]:
    """Each token, its dot-separated suffixes and parts, and every run of its -/_ separated parts."""
    out = set()
    for tok in re.findall(r"[a-z0-9][a-z0-9._-]*", text.lower()):
        tok = tok.strip("._-")
        dotted = [p for p in tok.split(".") if p]
        pieces = {tok} | set(dotted) | {".".join(dotted[i:]) for i in range(len(dotted))}
        for piece in list(pieces):
            parts = [p for p in re.split(r"[-_]", piece) if p]
            pieces |= {"-".join(parts[i:j]) for i in range(len(parts)) for j in range(i + 1, len(parts) + 1)}
        out |= pieces
    return out - {""}


def leaks(text: str) -> list[str]:
    named = {t for t in _candidates(text) if hashlib.sha256(t.encode()).hexdigest() in PRIVATE_TOKEN_DIGESTS}
    shaped = {m.group(0) for pat in PRIVATE_SHAPES for m in re.finditer(pat, text, re.I)}
    return sorted(named | shaped)


@pytest.mark.parametrize("path", [SPINE, COMPAT], ids=lambda p: p.name)
def test_policy_file_exists(path: Path):
    assert path.is_file(), f"{path.name} is missing"


def test_spine_quotes_the_owner_and_states_the_rule():
    text = SPINE.read_text()
    low = text.lower()
    assert "25 November 2026" in text
    for words in (
        "be linked to the axioms-derived graphs (mathlib4 and physics axioms)",
        "LEAN4 MUST be the central backbone / spine to all organization",
        "lean4-based verification of edges (this can use lean's FFI)",
        "PERSIST THAT STUFF in all relevant levels of the software chain",
    ):
        assert words in text, f"owner's words missing: {words!r}"
    assert "never a property" in low and "project@revision" in text
    for axiom in ("propext", "Classical.choice", "Quot.sound", "sorryAx"):
        assert axiom in text
    # The grounding definition is a proposal, not the owner's words; say so.
    assert "proposed definition, pending the owner's confirmation" in text
    assert "lean kernel" in low and "never asserted by an llm" in low
    assert "ratchet" in low and "100%" in text and "formalization obligation" in low


def test_compat_quotes_the_owner_and_links_the_sources():
    text = COMPAT.read_text()
    assert "25 November 2026" in text
    assert "important!! we shoudl ensure compatibaillity and leveraging of" in text
    for url in (
        "https://neo4j.com/blog/agentic-ai/scaling-karpathy-llm-wiki-graph/",
        "https://github.com/GoogleCloudPlatform/knowledge-catalog",
        "https://github.com/open-knowledge-format/open-knowledge-format",
        "https://github.com/zach-blumenfeld/knowledge-index",
    ):
        assert url in text, f"missing source link {url}"
    assert "frozen" in text.lower() and "Version 0.3" in text
    missing = [sha for sha in PINNED_REVISIONS if sha not in text]
    assert not missing, f"pinned revisions missing from the policy: {missing}"


def test_readme_points_at_both_policies():
    text = README.read_text()
    assert SPINE.name in text and COMPAT.name in text


@pytest.mark.parametrize("path", [SPINE, COMPAT, README], ids=lambda p: p.name)
def test_public_copy_leaks_no_private_names(path: Path):
    found = leaks(path.read_text())
    assert not found, f"{path.name} names private infrastructure or measurements: {found}"


def test_this_file_leaks_nothing_outside_its_digest_list():
    body = "\n".join(line for line in THIS_FILE.read_text().splitlines() if not DIGEST_LINE.match(line))
    found = leaks(body)
    assert not found, f"{THIS_FILE.name} names private infrastructure or measurements: {found}"


def test_leak_detector_bites():
    """Positive control: every matching rule fires on synthetic input, and ordinary text stays clean."""
    name = "-".join(["canary", "private", "token", "7f3a"])
    domain = ".".join(["canary-domain-7f3a", "test"])
    count_sep = ",".join(["12", "345", "678"])
    count_plain = "9" * 6
    address = ".".join(["100", "64", "0", "99"])
    org_prefix = "github.com/" + "some-private-org" + "/"
    probes = {
        "exact name": (f"token {name.upper()}.", name),
        "underscored name": (f"token {name.replace('-', '_')}", name),
        "longer name": (f"host {name}-local", name),
        "exact domain": (f"see {domain}", domain),
        "subdomain": (f"see https://bus.{domain}/x", domain),
        "separated count": (f"0 of {count_sep}", count_sep),
        "plain count": (f"0 of {count_plain}", count_plain),
        "address": (f"host {address}", address),
        "private org link": (f"https://{org_prefix}x", org_prefix),
    }
    for label, (text, expected) in probes.items():
        assert expected in leaks(text), f"leak detector missed the {label} probe: {text!r}"
    assert not leaks(
        "propext, Classical.choice and Quot.sound; OKF Version 0.3, read 2026-11-25; "
        "https://github.com/open-knowledge-format/open-knowledge-format; 100% coverage."
    )
