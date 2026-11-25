# Knowledge-Format Compatibility — Open Knowledge Format and Neo4j's Wiki Index

**Status**: Mandatory, organization-wide
**Effective**: 25 November 2026
**Source**: the organization owner, 25 November 2026
**Scope**: Every agent and pipeline that designs, exports, indexes or serves knowledge-graph content

## The owner's words

> "important!! we shoudl ensure compatibaillity and leveraging of https://neo4j.com/blog/agentic-ai/scaling-karpathy-llm-wiki-graph/ and https://github.com/GoogleCloudPlatform/knowledge-catalog/"

The owner named `okf/SPEC.md` in the second repository.

## The rule

1. **Stay compatible, and build on them.** Knowledge-graph work stays compatible with the **Open Knowledge Format (OKF)** and with **Neo4j's wiki-index approach**, and builds on both. Where they already answer a design question (file layout, frontmatter, provenance, trust, lifecycle, structural indexing of Markdown), use their answer instead of inventing one.
2. **Read the sources before writing about them.** Pin what you read (a commit SHA, or the date for the blog post) in the pull request. Do not describe either source from memory or from someone else's summary.
3. **Exports respect the boundary** set out below.

## The sources, read 25 November 2026

| Source | What it is | Revision read |
|---|---|---|
| [Neo4j blog: "Scaling Karpathy's LLM wiki: Why your knowledge base needs a graph"](https://neo4j.com/blog/agentic-ai/scaling-karpathy-llm-wiki-graph/) | Zach Blumenfeld (Neo4j), 31 August 2026 | page as served on 25 November 2026 |
| [GoogleCloudPlatform/knowledge-catalog, `okf/SPEC.md`](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/0003e7f3ec273f5caf84849850d560b12e9527e4/okf/SPEC.md), the copy the owner named | OKF v0.2. Its README now calls it a **frozen** snapshot, no longer maintained | `0003e7f3ec273f5caf84849850d560b12e9527e4` |
| [GoogleCloudPlatform/open-knowledge-format](https://github.com/GoogleCloudPlatform/open-knowledge-format/blob/8a8ff87bfd3847c34c9ddd4fbfd9296be2aee4a3/SPEC.md) | OKF v0.2; marks itself deprecated | `8a8ff87bfd3847c34c9ddd4fbfd9296be2aee4a3` |
| [open-knowledge-format/open-knowledge-format, `SPEC.md`](https://github.com/open-knowledge-format/open-knowledge-format/blob/527e81aff55992be21507e97004286789126f88c/SPEC.md) | **The current spec**, headed "Version 0.3". The spec gives no release date; 18 November 2026 is the date of the pinned commit. Target this one. | `527e81aff55992be21507e97004286789126f88c` |
| [zach-blumenfeld/knowledge-index (`ki`)](https://github.com/zach-blumenfeld/knowledge-index/tree/808987c5daa4da150e38ecc87f5e4ed6cdfdc0c9) | The blog's open-source reference implementation, Apache-2.0 | `808987c5daa4da150e38ecc87f5e4ed6cdfdc0c9` |

All three OKF repositories are Apache-2.0.

## What the sources fix

**OKF v0.3**
- A bundle is a directory of Markdown files with YAML frontmatter. `type` is the only required key. One concept per file; the concept ID is the path without `.md`.
- Provenance is `sources` (with an `id` for per-claim footnotes). Trust is `generated` and `verified`. Lifecycle is `status`, `superseded_by` and `stale_after`. Bundle metadata (`okf_version: "0.3"`, `license`) sits in the root `index.md`.
- Trust tiers come only from *current* `verified` events. They are advisory signals, **not access control**.
- Links are plain, untyped, directed Markdown links; `[[wikilinks]]` are not OKF links. Typed relationships are deferred to a future version; until then the spec says to use links, path fields and extension keys. Name extension keys `x-<producer>-<name>`: future OKF versions will never define keys that start with `x-`.
- Consumers MUST accept unknown keys and broken links, and MUST NOT read paths that resolve outside the bundle root.

**Neo4j's wiki index (`ki`)**
- The graph is a disposable, rebuildable index over the Markdown source. It is built deterministically and idempotently from structure (folders, headings, links), with no LLM calls and no embeddings at index time. Source files are never modified.
- Data model: `Vault`, `Folder`, `Document`, `Section`. `HAS` is a single-parent containment tree pointing parent to child: every folder, document and section in a vault has exactly one incoming `HAS`. `NEXT_SECTION` threads **every** section of a document in depth-first reading order, and is rebuilt on each index. `LINKS_TO` covers every link, wikilinks included. Fulltext search. Retrieval goes outline, then search, then get, plus Cypher for backlinks and paths.

## How to apply it

- **The graph stays the store of record; OKF is an interchange boundary.** An OKF bundle is a selected-source export, not a second store.
- **Exports are OKF v0.3 bundles.** One concept per unit, and native edges as Markdown links. Identity and pins go in `x-<producer>-<name>` extension keys: snapshot key, manifest and content hashes, the stored edge key, edge type and direction, reading order, and the Lean link of [LEAN4_SPINE_POLICY.md](LEAN4_SPINE_POLICY.md). Record which rule produced the order, and carry gaps (tie, cycle, disconnected) instead of repairing them silently.
- **Map trust honestly.** A Lean kernel verdict, or another verifier run, becomes a `verified` event with a `process:` actor, which reads as machine-confirmed. Use a `human:` actor only when a person confirmed the current content. An LLM-written concept with no verifier run carries no `verified` event.
- **Index Markdown the wiki-index way.** When a Markdown corpus (notes, a wiki, an OKF bundle) is indexed into Neo4j, build the structural graph deterministically from headings and links, leave the source untouched, and keep the index rebuildable. Adopt `ki` where it fits rather than writing a parallel indexer.
- **Add no parallel label set.** If the graph already has containment and reading-order relationships, map them onto `ki`'s explicitly and record where they differ: direction (`HAS` points parent to child), the single-parent rule, and coverage (`NEXT_SECTION` threads every section, while many document graphs leave some units out of reading order). Route any new label through schema review.

## Export boundary and access

- An export is computed under a named read-only role, **never an administrator login**. It contains exactly what that role can read.
- Private content is left out, not exported as gray entries. Confidential material stays invisible. Personal-data fields that access control denies never appear.
- Only pinned, versioned sources are eligible: manifest-pinned document snapshots, and versioned reasoning chains with one unambiguous order.
- Every file carries its pins, the exporting role, the export time and the source's trust state. An unreviewed source is labelled unverified.
- No executable payloads, principals or access grants go into an export.
- A local bundle for a recipient who already holds the role needs no new approval. Publishing to Google Knowledge Catalog, or anywhere outside the organization's private network, needs the owner's **approval per batch**. The sample Knowledge Catalog connector ([limitations](https://github.com/open-knowledge-format/open-knowledge-format/blob/527e81aff55992be21507e97004286789126f88c/connectors/gcp-knowledge-catalog.md#limitations)) carries only seven frontmatter keys (`title`, `description`, `tags`, `resource`, `type`, `generated`, `sources`) plus the body. Every other key is dropped, including `verified`, `status`, `superseded_by`, `stale_after`, the attested-computation keys and every extension key, so the pins go with them. It also carries only `.md` files, stores cross-links verbatim without resolving them, turns tags into labels, orphans catalog state on a rename and leaves entries behind on a delete, has no entry-level access control (any project viewer can bulk-export the entry group), and is untested beyond a 14-file demo.
- Import back into the graph goes through the organization's reviewed write path.
