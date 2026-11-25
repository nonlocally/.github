# Lean 4 Is the Spine — Every Math Unit Links to an Axiom-Grounded Declaration

**Status**: Mandatory, organization-wide
**Effective**: 25 November 2026
**Source**: the organization owner, 25 November 2026
**Scope**: Every agent, pipeline, service and CI job that writes, maintains, serves or checks mathematical, physics or engineering content in a knowledge graph

## The owner's words

> "it MUST be ENSURED THAT ALL content related to math objects (definitions in math, physics, engineering, etc..) **MUST** be linked to the axioms-derived graphs (mathlib4 and physics axioms)"
>
> "PERSIST THAT THROUGHOUT the neo4j maintenance and usage. LEAN4 MUST be the central backbone / spine to all organization, with lean4-based verification of edges (this can use lean's FFI)"
>
> "PERSIST THAT STUFF in all relevant levels of the software chain ... including as part of the ci runners, ci-cd with [fleet operations]"

## The rule

1. **Link by edge, never a property.** Every math, physics or engineering unit in the knowledge graph links by a relationship (an edge) to a Lean 4 declaration pinned by `project@revision`: the Lean project and the full commit hash of the checkout that was checked. This covers math-object nodes, document-graph equations and definitions, and any new kind of math content. A Lean name stored in a property is not a link and never counts toward coverage; migrate it to an edge. Use the relationship type your graph's schema defines; do not invent a parallel one.

2. **Grounding.** A link grounds its unit only if the declaration's kernel-computed, transitive axiom closure (`#print axioms`) is non-empty and inside the allowed set:
   - Lean core and the Mathlib4 trusted core: `propext`, `Classical.choice`, `Quot.sound`;
   - the physics-axiom namespaces that the organization has explicitly named and reviewed.

   `sorryAx`, `Lean.ofReduceBool` (from `native_decide`) and every other axiom, ad-hoc, project-local or imported, are not grounding. A link to an ungrounded declaration may be stored, but it is reported as ungrounded and does not count toward coverage.

3. **Verified by the Lean kernel, never asserted by an LLM.** A link is verified only by a compiled check that the Lean kernel runs. Lean's FFI and a `lake` executable both qualify. An LLM, an embedding match or a name match may *propose* a link; only the kernel check verifies it. Each verification records:
   - the toolchain (the `lean-toolchain` string);
   - `project@revision` and the declaration name;
   - the type hash and the value hash of the checked constant;
   - the axiom closure;
   - the verdict and the time.

   When the revision, the type hash or the value hash changes, the link is re-verified before it counts again.

4. **Coverage is a ratchet.** Grounded-link coverage is the share of math units with at least one verified, grounded link, reported per kind. It may never go down, and the target is 100%. CI enforces the ratchet: a change that lowers coverage fails. New math content without a link is admitted only with a tracked formalization obligation (a strict xfail test or an issue that names the unit), never silently.

5. **Every level of the software chain.** The rule binds where the work happens, not only in this file:
   - writers and ingestion pipelines attach the link, or the formalization obligation, when they write a unit;
   - graph maintenance agents and scheduled health jobs report coverage, ungrounded links, stale links and property-only Lean evidence;
   - readers and viewers show a unit's Lean link and verdict, or that it has none;
   - CI runners and CI/CD run the ratchet check, run kernel verification on the organization's own runners, and gate deploys on both.

## Notes

- Kernel checks run where the Lean build cache is warm, locally or on the organization's own runners. Hosted CI enforces the ratchet over the recorded verdicts; it does not need to recompile Lean.
- An export of a unit carries its Lean link and its verdict ([KNOWLEDGE_FORMAT_COMPATIBILITY_POLICY.md](KNOWLEDGE_FORMAT_COMPATIBILITY_POLICY.md)).
