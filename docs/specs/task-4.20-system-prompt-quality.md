# Task 4.20: System Prompt Quality and Export Automation

## 1. Metadata

- Task ID: 4.20 (parent), 4.20.1–4.20.4 (subtasks)
- Title: System prompt quality and export automation
- Status: pending
- Owner: Todd Terry
- Last Updated: 2026-03-24
- Related Task(s): none
- Related Docs:
  - `docs/agent_prompt_export.md` — stakeholder-facing prompt snapshot
  - `lib/system_prompt.py` — runtime prompt builder (source of truth)
  - `lib/write_proposal.py` — writable field metadata used by prompt builder

## 2. Problem

A prompt engineering review of `docs/agent_prompt_export.md` against Anthropic
best practices found eight issues in two categories:

**Production accuracy** — the model is observed making wrong object-type choices
on ambiguous queries (e.g. "what's happening in Dallas" routes to the wrong
object). The prompt tells the model to "reason about object selection" (guideline
17) but provides no structured reasoning scaffold or negative examples.

**Prompt hygiene** — the export file is stale (missing propose_edit tool, 2
guidelines, 3 few-shot examples added since 2026-03-21), field information
appears 2–3× across prompt sections (token waste), the CLARIFY marker format
is defined by scattered examples rather than a single spec, and XML structural
tags are not used despite being an Anthropic best practice for separating
data from instructions.

## 3. Goal

Improve agent query accuracy on ambiguous/complex questions and bring the prompt
export, structure, and documentation up to Anthropic prompt engineering standards
so the prompt is reviewable by stakeholders and maintainable by developers.

## 4. Non-Goals

- Changing tool schemas or adding new tools (that's 4.17/4.19 scope).
- Changing the query handler, tool dispatch, or any runtime Python beyond
  `lib/system_prompt.py`.
- Rewriting the field reference content — the curated descriptions are good.
- Prompt chaining or multi-turn orchestration changes.

## 5. Current State

### Prompt builder
`lib/system_prompt.py` exposes:
- `SYSTEM_PROMPT` — static fallback (5 objects, 2 tools). Used only when
  `denorm_config.yaml` is unavailable.
- `build_system_prompt(config)` — dynamic builder (all objects, 3 tools).
  Production path.
- `build_tool_definitions(config)` — dynamic tool definitions.

### Export
`docs/agent_prompt_export.md` is a manually-maintained snapshot. It was last
updated 2026-03-21 and is missing:
- `propose_edit` tool definition
- Few-shot example #2 (market filter), #13 (sort_order + top_n), #14
  (propose_edit)
- Guideline 10 (conversation history / button-driven follow-ups)
- Guideline 20 (write proposal writable contract)

### Known failure modes
- Model picks wrong object type on ambiguous queries.
- No negative examples in the prompt — model has no anti-pattern guidance.
- CLARIFY marker format must be inferred from scattered examples.

## 6. Target Behavior

After this task ships:
1. `scripts/export_agent_prompt.py` generates the export deterministically from
   `build_system_prompt()` + `build_tool_definitions()`. The export can never
   drift from production.
2. The model uses a structured 3-step reasoning process for ambiguous object
   selection before calling tools.
3. Anti-pattern examples show the model what NOT to do (unnecessary multi-step,
   fabricated rankings, match-everything text_query hacks).
4. The CLARIFY marker format is formally defined once and referenced by name.
5. Major prompt sections are wrapped in XML tags for stronger instruction
   boundaries.
6. Hardcoded dates in few-shot examples include a note that they are
   illustrative and relative dates must be computed from "today's date" above.
7. A guideline covers tool error / partial result handling.
8. Field-level notes that duplicate the Field Reference are consolidated.

## 7. Scope

### In Scope

| Subtask | Deliverable |
|---|---|
| 4.20.1 | Export automation script |
| 4.20.2 | Object selection reasoning scaffold + negative examples |
| 4.20.3 | Structural improvements (XML tags, CLARIFY spec, token dedup) |
| 4.20.4 | Edge case coverage (date alignment, error handling guideline) |

### Out of Scope

- Changes to `lib/tool_dispatch.py` or `lib/query_handler.py`.
- Changes to the LWC or Apex layer.
- New tool definitions.
- Production A/B testing of prompt variants (no infra for this yet).

## 8. Design

### 4.20.1 — Export automation script

Create `scripts/export_agent_prompt.py` that:
1. Loads `denorm_config.yaml`.
2. Calls `build_system_prompt(config)` and `build_tool_definitions(config)`.
3. Writes the output to `docs/agent_prompt_export.md` in the existing format
   (system prompt block, tool definitions block, footer with date/stats).
4. Prints a summary to stdout (object count, tool count, guideline count).

The script must be runnable standalone:
```bash
python3 scripts/export_agent_prompt.py
```

Add a note to `docs/agent_prompt_export.md` header: "Auto-generated — do not
edit manually. Run `python3 scripts/export_agent_prompt.py` to regenerate."

### 4.20.2 — Object selection reasoning scaffold + negative examples

**A. Reasoning scaffold** — Replace guideline 17 in `_build_guidelines()` with:

```
17. **For complex questions, reason about object selection before calling tools.**
    When the question could apply to multiple object types (e.g. "what's
    happening in Dallas"), work through these steps before making tool calls:
    (a) What entity is the user asking about? (a building, a deal, a person,
        a space, a task, a requirement)
    (b) What action do they want? (find, count, compare, track, summarize)
    (c) Which object's fields best match the intent?
    Search the most specific matching object type first. If genuinely ambiguous,
    emit CLARIFY options for the two most likely interpretations rather than
    guessing.
```

**B. Negative examples** — Append to `_FEW_SHOT_EXAMPLES` after the last
positive example:

```
### Anti-pattern examples — do NOT do these

**WRONG — unnecessary multi-step when denormalized fields exist**
User: "Show me leases in Dallas"
  Step 1: search_records(object_type="Property", filters={"city": "Dallas"})
  Step 2: search_records(object_type="Lease", filters={"property_name_in": [results from step 1]})
Why wrong: Lease has denormalized property_city. Use it directly:
  search_records(object_type="Lease", filters={"property_city": "Dallas"})

**WRONG — fabricating a ranking from raw search hits**
User: "Who are our top brokers by deal value?"
  search_records(object_type="Deal", limit=50)
  → then manually summing deal_value per broker from results
Why wrong: Raw search hits are not a complete dataset. Use aggregate_records
with group_by for rankings, or clarify if the grouping dimension is ambiguous.

**WRONG — using text_query as a match-everything hack**
User: "How many properties do we have?"
  search_records(object_type="Property", text_query="a the is of and")
Why wrong: For counts, use aggregate_records(object_type="Property", aggregate="count").
Never use stopwords as a match-everything trick.
```

### 4.20.3 — Structural improvements

**A. XML tags** — In `build_system_prompt()` (and `SYSTEM_PROMPT`), wrap the
three major data/instruction sections:

```python
# Field reference section
<field_reference>
{field_reference}
</field_reference>

# Examples section
<examples>
{_FEW_SHOT_EXAMPLES}{_WRITE_PROPOSAL_EXAMPLE}
</examples>

# Guidelines section
<guidelines>
{guidelines}
</guidelines>
```

Leave the opening paragraphs (role, date, vocabulary, tools) unwrapped — they
are short preamble that benefits from being top-level.

**B. CLARIFY marker formal spec** — Add as a new block before guideline 1 in
`_build_guidelines()`:

```
**Clickable option format (CLARIFY markers)**
Format: ``[CLARIFY:button label|full self-contained query text]``
Each option's query text must be a complete standalone question that can be
submitted with no conversation context. Use this marker whenever presenting
follow-up suggestions or disambiguation options.
```

Then simplify the inline CLARIFY explanations in guidelines 1, 6, 10, and 19
to reference "CLARIFY markers (defined above)" instead of re-explaining the
format each time.

**C. Token deduplication** — Remove or condense these guideline passages that
restate the Field Reference:

| Guideline | What it restates | Action |
|---|---|---|
| 12 (rent_low / rent_high) | Availability field reference lines 39-40 | Remove. Already stated clearly in field ref with "rent_low: asking rent low end (per SF)". |
| 15 (geography scope) | Field reference per-object market/submarket notes | Condense to one sentence: "Geography filter support varies by object — see Field Reference for which objects support market, submarket, region, vs. city/state." |
| 4 (denormalized fields bullet list) | Field reference "(denormalized)" annotations | Keep the *rule* ("use denormalized fields to avoid multi-step") but replace the 7-line bullet list with: "See the '(denormalized)' annotations in the Field Reference above for the full list." |

**Estimated token savings**: ~300-400 tokens per prompt invocation.

### 4.20.4 — Edge case coverage

**A. Date alignment** — Add a one-line note at the top of the examples section
in `_FEW_SHOT_EXAMPLES`:

```
Note: Dates in examples below are illustrative. Always compute relative dates
(e.g. "last 12 months") from today's date stated above.
```

**B. Error handling guideline** — Add as guideline 21 in `_build_guidelines()`:

```
21. **If a tool returns an error or unexpected result, explain plainly.**
    Do not retry silently with altered parameters. Tell the user what happened,
    suggest a corrected query if the cause is obvious (e.g. unsupported filter
    field), or recommend broadening/narrowing their request.
```

## 9. Files / Surfaces Likely To Change

| File | Change |
|---|---|
| `lib/system_prompt.py` | Guidelines, examples, XML wrapping, CLARIFY spec (4.20.2, 4.20.3, 4.20.4) |
| `scripts/export_agent_prompt.py` | New file (4.20.1) |
| `docs/agent_prompt_export.md` | Regenerated by script (4.20.1) |
| `tests/test_system_prompt.py` | Add/update tests for new guidelines, XML tags, example count |

## 10. Dependencies

- None. All changes are in prompt text and a new script. No upstream task
  dependencies.

## 11. Acceptance Criteria Interpretation

See per-subtask AC in `tasks.json`. Key judgment calls:

- "XML tags" means the three major sections (field_reference, examples,
  guidelines) are wrapped. The preamble stays unwrapped.
- "Token deduplication" means removing restated content from guidelines, not
  removing information from the Field Reference or tool descriptions.
- "Negative examples" means 2-3 anti-pattern examples, not exhaustive coverage
  of every possible mistake.

## 12. Testing Plan

### Automated

- `tests/test_system_prompt.py`:
  - Assert `build_system_prompt()` output contains `<field_reference>`,
    `<examples>`, `<guidelines>` tags.
  - Assert `build_system_prompt()` output contains the reasoning scaffold text
    (e.g. "What entity is the user asking about").
  - Assert `build_system_prompt()` output contains "Anti-pattern" section.
  - Assert CLARIFY marker spec appears exactly once.
  - Assert guideline 12 (rent_low/rent_high standalone) is removed.
  - Assert `scripts/export_agent_prompt.py` produces output matching
    `build_system_prompt()` + `build_tool_definitions()`.

### Manual

- Run the export script and diff against the previous export to verify no
  unintended content loss.
- Manually test 3-5 ambiguous queries (e.g. "what's happening in Dallas",
  "show me everything for ACME") against the updated prompt in the sandbox
  and verify the model reasons about object selection before calling tools.

## 13. Risks / Open Questions

- **XML tag impact on Bedrock**: Claude via Bedrock Converse API handles XML
  tags in system prompts, but verify that the tags don't interfere with
  Bedrock's own message formatting. Low risk — XML in system prompts is a
  standard Anthropic pattern.
- **Negative example length**: Adding 3 anti-pattern examples adds ~200 tokens.
  Offset by the ~300-400 token savings from deduplication, so net token count
  should decrease slightly.
- **Guideline renumbering**: Removing guideline 12 and modifying 4/15 shifts
  numbers. Existing tests that assert specific guideline numbers will need
  updating. Consider using guideline names/anchors instead of numbers in tests.

## 14. Handoff Notes

**Recommended implementation order**: 4.20.2 → 4.20.3 → 4.20.4 → 4.20.1.
Rationale: make all prompt content changes first (4.20.2–4.20.4), then build
the export script (4.20.1) so it captures the final state in one pass.

**Known traps**:
- Edit `lib/system_prompt.py` only — not the bundle copies in `lambda/query/lib/`.
  Run `scripts/bundle_query.sh` after all changes to sync.
- The static `SYSTEM_PROMPT` and `TOOL_DEFINITIONS` (5-object fallback) should
  also get XML tags and the reasoning scaffold for consistency, even though
  production uses the dynamic builder.
- `_build_guidelines()` is used by both static and dynamic paths. Changes there
  apply to both.

**Required validation before marking complete**:
- `python3 -m pytest tests/test_system_prompt.py -v` passes.
- `python3 scripts/export_agent_prompt.py` runs without error and produces
  a complete export.
- Manual query test confirms object selection reasoning is visible in model
  behavior (not just present in prompt text).
