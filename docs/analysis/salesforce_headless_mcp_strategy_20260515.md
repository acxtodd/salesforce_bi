# Salesforce Headless / MCP Strategy For AscendixIQ

Date: 2026-05-15
Status: Draft strategy note
Role: BA/PM architecture planning

## Executive Take

Salesforce Headless 360 and Hosted MCP should not be treated as a wholesale
replacement for the current AscendixIQ search platform yet. The better near-term
strategy is to use them as governed live-access and action surfaces around the
current retrieval core.

Current AscendixIQ strength is cross-object semantic retrieval, answer synthesis,
citations, and CRE-specific query behavior over a denormalized Turbopuffer index.
Salesforce's new strength is governed, per-user live access to Salesforce data,
metadata, Flows, Apex actions, Named Queries, and eventually richer Agentforce
experiences through standard APIs and MCP.

The strategic direction should be hybrid:

1. Keep Turbopuffer + custom query orchestration as the semantic candidate
   retrieval layer.
2. Add live Salesforce fetch after retrieval for authoritative display fields,
   freshness, and FLS-sensitive detail.
3. Move write-back execution behind Salesforce-native business logic surfaces:
   Apex Invocable Actions, Flows, GraphQL/UI API mutations, or Composite Graph,
   exposed through our platform and optionally through Hosted MCP.
4. Treat Hosted MCP as a customer/admin integration channel and governance
   layer, not as the only product runtime.
5. Use Salesforce headless metadata, GraphQL introspection, API Catalog, and
   packaged invocable actions to reduce custom configuration burden over time.

## Current Product Baseline

AscendixIQ currently uses:

- LWC + Apex as the Salesforce user-facing surface.
- AWS Lambda `/query` as the model/tool orchestration layer.
- Turbopuffer for vector, keyword, metadata filter, and aggregate retrieval.
- AppFlow -> S3 -> EventBridge -> `cdc_sync` for live CDC on the five live
  objects.
- Poll sync for expansion objects.
- Ascendix Search metadata compiled into versioned runtime artifacts.

Important current limits:

- CDC/poll freshness can lag or fail operationally.
- Denormalizing display fields into Turbopuffer creates 256-attribute pressure.
- Parent updates do not automatically cascade to all denormalized children.
- Runtime config correctness depends on a custom compiler over Ascendix Search
  metadata.
- Write-back needs a durable, governed architecture before create and
  multi-record flows are expanded.

## What Changed In Salesforce

The relevant Salesforce movement is broader than MCP.

Salesforce is positioning Headless 360 as a platform shift where capabilities
are available through APIs, MCP tools, or CLI commands. Hosted MCP Servers are
now GA for Enterprise Edition orgs and above, and expose data, flows, Apex
actions, queries, and related capabilities through MCP with Salesforce-hosted
authentication and permission enforcement.

Key official capabilities:

- Hosted MCP supports per-user OAuth and can expose SObject CRUD, Apex
  Invocable Actions, Aura-enabled methods, Apex REST, Flows, Named Queries,
  Prompt Builder templates, Data 360 SQL, Tableau Next, and API Catalog tools.
- Custom MCP servers let admins curate persona-specific tool sets instead of
  exposing every operation.
- Salesforce recommends custom tools for scoped access and business logic:
  Named Queries for controlled read slices, Apex Invocable Actions for
  multi-step or validated operations.
- GraphQL API offers field selection, aggregation, schema introspection, and
  permission-shaped schemas. GraphQL mutations are generally available in API
  v66.0 and later for UI API-supported objects, including `allOrNone` behavior.
- Pub/Sub API provides a lower-level real-time CDC/event stream than AppFlow,
  with gRPC/HTTP2 delivery, flow control, event schema access, and subscription
  to CDC, platform events, and real-time event monitoring.
- Agent API provides a way to invoke Agentforce agents from external systems,
  but it is a different product runtime with credit consumption and timeout
  constraints.
- Data 360 MCP is emerging but currently still carries preview/local/single-org
  characteristics in the open-source server path; useful for future RAG/control
  plane experiments, not a near-term replacement for the current runtime.

## Strategic Pillars

### 1. Real-Time Or Near-Real-Time Updates

Recommended strategy:

- Keep the current CDC path in place until a controlled benchmark proves a
  better path.
- Add a Pub/Sub API spike as the most credible replacement or supplement for
  AppFlow CDC. Pub/Sub API is designed for direct CDC/platform-event
  subscriptions and removes the AppFlow/S3/EventBridge indirection.
- Separately add post-retrieval live fetch for display fields. This does not
  replace indexing, but it reduces the business impact of CDC lag because final
  answer details come from Salesforce at response time.

Likely target architecture:

- Index stores semantic candidate fields, IDs, object type, and selected
  stable filters.
- Query retrieves candidate IDs from Turbopuffer.
- Query layer fetches authoritative current details from Salesforce using
  REST, GraphQL, or a packaged Apex/Aura facade.
- Live details are merged into citations/cards/answer context.

This directly supports current task `4.33`, but the research suggests we should
broaden it from "hybrid retrieval spike" to "freshness and attribute-cap
strategy."

### 2. Auto-Configuration

Recommended strategy:

- Continue to treat Ascendix Search metadata as high-signal business intent.
- Use Salesforce headless metadata surfaces to validate and enrich that intent,
  not replace it blindly.
- Add an explicit "write metadata" contract that is separate from search config.

Useful Salesforce surfaces:

- GraphQL schema introspection for permission-shaped field availability.
- UI API / GraphQL metadata for layouts, fields, requiredness, and supported
  objects.
- Hosted MCP custom servers and API Catalog as a deployable packaging target
  for customer-admin configuration.
- Packaged Apex Invocable Actions and Flows as ISV-distributed capabilities that
  customer admins can expose through Hosted MCP.

Product implication:

- Search config answers "what should be searchable and shown."
- Live metadata answers "what can this user see or edit right now."
- Write config answers "what operations are safe for downstream consumers to
  propose and execute."

These must remain separate contracts.

### 3. Accuracy

Recommended strategy:

- Keep semantic retrieval custom. This is where AscendixIQ differentiates.
- Improve factual accuracy by grounding final answer context in live Salesforce
  data after candidate retrieval.
- Improve tool accuracy by curating fewer, stronger tools rather than exposing
  broad SObject access to the model.

Concrete accuracy improvements:

- Use live fetch for current values, parent fields, and display cards.
- Use permission-shaped GraphQL or Apex facades so inaccessible fields fail
  closed.
- Keep citations tied to Salesforce record IDs and live-fetched fields.
- Move broad "search all fields" decisions away from raw model reasoning and
  into compiled field registries plus Salesforce metadata validation.
- Add eval sets for freshness probes: update a parent field, query the child
  answer, verify the answer reflects live Salesforce rather than stale denorm.

Hosted MCP itself does not solve semantic retrieval quality. It solves governed
access and tool execution. The product should use it where that is the problem.

### 4. Downstream Record Editing

This is the largest strategic shift.

Downstream consumers should not be handed generic SObject write access as the
main integration pattern. The safe product shape is a proposal-and-execution
platform:

1. Consumer app sends intent or proposed diff to AscendixIQ.
2. AscendixIQ resolves target records, validates writable fields, and returns a
   structured proposal.
3. Human or downstream workflow approves.
4. Execution runs through Salesforce-native logic with user/context/audit
   semantics preserved.
5. Result is reported back with record links, changed fields, and failures.

Preferred execution ladder:

- Single-record, UI-adjacent edits: GraphQL/UI API mutation or standard
  Salesforce form path, when user context and UX are local to Salesforce.
- Business-rule edits: Apex Invocable Action or Flow, especially when validation,
  side effects, or audit language matter.
- Multi-record/chained edits: Composite Graph or queued Apex/Lambda worker with
  a durable proposal envelope and all-or-none semantics where appropriate.
- External AI clients: Hosted MCP custom server can expose the same packaged
  Apex/Flow actions to admins who want Claude/ChatGPT/etc. access.

This keeps our platform as the orchestration and governance product while using
Salesforce-native execution for enforcement.

## What To Avoid

- Do not replace the retrieval core with generic Salesforce MCP SObject tools.
  Broad SObject tools are useful for admin/developer productivity but too
  uncurated for high-quality CRE answer behavior.
- Do not expose `sobject-all` as the product write surface for downstream
  consumers.
- Do not let Hosted MCP availability drive the whole architecture. It is GA for
  Enterprise Edition and above, but OEM/embedded customer availability and
  packaging constraints must be verified.
- Do not collapse search metadata and write metadata. Fields useful for retrieval
  are often invalid or unsafe as write targets.
- Do not promise native create success/cancel detection from external or native
  Salesforce create flows unless we validate the detection path.

## Roadmap Implications

### Reframe Existing Tasks

`4.33` should become the first proof of hybrid live-fetch retrieval:

- Candidate retrieval from Turbopuffer.
- Live detail fetch from Salesforce for Sale.
- Freshness probes and 256-attribute relief measured quantitatively.
- Compare REST, GraphQL, and Apex facade options where feasible.

`4.34` should become the write execution ADR:

- Compare current LWC sync REST, GraphQL/UI API mutation, Apex Invocable/Flow,
  queued worker, Composite Graph, and Hosted MCP exposure.
- Make a decision by use case, not globally.
- Prototype at least one external-consumer edit path, not only Salesforce LWC.

`4.17.7` and `4.17.8` should wait for the `4.34` decision:

- Writable metadata contract depends on execution mode.
- Structured proposal transport should be shaped as an external API envelope,
  not just LWC state.

### New Candidate Workstreams

1. Salesforce Headless Capability Matrix
   - Validate Hosted MCP, Agent API, GraphQL, Pub/Sub API, API Catalog, Flows,
     Apex Invocable Actions, Composite Graph, and Data 360 against this product.

2. Pub/Sub API CDC Spike
   - Compare AppFlow CDC vs direct Pub/Sub CDC for latency, replay behavior,
     operational burden, and failure detection.

3. External Write Proposal API
   - Define the platform-facing contract for downstream apps:
     `propose`, `approve/submit`, `status`, `cancel`, `audit`.

4. Packaged Action Surface
   - Create packaged Apex Invocable Actions for safe CRE operations such as
     update lease stage, update availability status, create inquiry, create
     task/follow-up, and update contact details.

5. Hosted MCP Customer Pilot
   - In an Enterprise sandbox, expose the packaged actions through a custom MCP
     server and test from Claude/Postman/MCP Inspector.

## Decision Framework

Use this rubric for each capability:

| Question | Prefer Salesforce Headless/MCP | Prefer Current AWS/Turbopuffer |
|---|---|---|
| Need semantic cross-object search? | No | Yes |
| Need current authoritative field values? | Yes | No |
| Need per-user FLS/sharing enforcement? | Yes | Only with added work |
| Need CRE-specific ranking/synthesis? | Not enough | Yes |
| Need controlled write execution? | Yes, through Apex/Flow/GraphQL | Only as orchestrator |
| Need external non-SF app integration? | Maybe, if MCP client fits | Yes, via our API |
| Need multitenant ISV packaging? | Not yet proven for Hosted MCP config | Yes, we control it |
| Need operational ownership outside Salesforce? | No | Yes |

## Recommended Next Step

Create a short strategy sprint with three deliverables:

1. A Headless/MCP capability matrix grounded in official docs and a sandbox test.
2. A Sale hybrid live-fetch spike tied to `4.33`.
3. A write-path ADR/prototype tied to `4.34`, centered on external consumer
   write-back rather than only the Salesforce LWC.

The output should be a go/no-go on each of these bets:

- `GO`: live fetch after semantic retrieval.
- `GO`: Salesforce-native execution surface for writes.
- `PROBE`: Pub/Sub API as a cleaner CDC path.
- `PROBE`: Hosted MCP as a customer/admin integration channel.
- `DEFER`: Agentforce Agent API and Data 360 MCP as product runtime replacements.

## Sources Checked

- Salesforce Hosted MCP overview:
  https://developer.salesforce.com/docs/platform/hosted-mcp-servers/guide/hosted-mcp-servers-overview.html
- Salesforce Hosted MCP best practices:
  https://developer.salesforce.com/docs/platform/hosted-mcp-servers/guide/best-practices.html
- Salesforce Hosted MCP custom servers:
  https://developer.salesforce.com/docs/platform/hosted-mcp-servers/guide/custom-servers.html
- Hosted MCP GA announcement:
  https://developer.salesforce.com/blogs/2026/04/salesforce-hosted-mcp-servers-are-now-generally-available
- Salesforce products supporting MCP:
  https://developer.salesforce.com/docs/platform/hosted-mcp-servers/guide/products-supporting-mcp.html
- Agent API:
  https://developer.salesforce.com/docs/ai/agentforce/guide/agent-api.html
- Agent API get started / auth:
  https://developer.salesforce.com/docs/ai/agentforce/guide/agent-api-get-started.html
- Agent API considerations:
  https://developer.salesforce.com/docs/ai/agentforce/guide/agent-api-considerations.html
- Data 360 MCP Developer Preview:
  https://developer.salesforce.com/blogs/2026/05/introducing-the-data-360-mcp-server-developer-preview
- Salesforce Pub/Sub API:
  https://developer.salesforce.com/docs/platform/pub-sub-api/guide/intro.html
- Salesforce GraphQL API:
  https://developer.salesforce.com/docs/platform/graphql/guide/intro-graphql-api.html
- Salesforce GraphQL mutations:
  https://developer.salesforce.com/docs/platform/graphql/guide/mutations-schema.html
- Salesforce Platform API overview including Composite Graph limits:
  https://developer.salesforce.com/blogs/2024/04/accessing-object-data-with-salesforce-platform-apis
- Salesforce Headless 360 announcement:
  https://www.salesforce.com/news/stories/salesforce-headless-360-announcement/
