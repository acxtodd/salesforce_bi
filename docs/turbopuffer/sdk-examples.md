# SDK Examples

Last updated: 2026-03-18

These examples are condensed from the official turbopuffer docs plus Context7 entries for the official TypeScript and Python SDKs. Use them as starting points, not as exhaustive API references.

## TypeScript

Package:

```bash
npm install @turbopuffer/typescript
```

Initialize one shared client:

```ts
import * as tpuf from "@turbopuffer/typescript";

const turbopuffer = new tpuf.Turbopuffer({
  apiKey: process.env.TURBOPUFFER_API_KEY,
  region: "gcp-us-central1",
});

const ns = turbopuffer.namespace("docs-example-ts");
```

Write hybrid-searchable documents:

```ts
await ns.write({
  distanceMetric: "cosine_distance",
  upsertRows: [
    {
      id: 1,
      vector: [0.1, 0.2, 0.3],
      chunk_text: "uuid fields are smaller than string UUIDs",
      category: "schema",
    },
  ],
  schema: {
    chunk_text: {
      type: "string",
      fullTextSearch: true,
    },
  },
});
```

Run vector retrieval:

```ts
const result = await ns.query({
  rankBy: ["vector", "ANN", [0.1, 0.2, 0.3]],
  topK: 10,
  includeAttributes: ["chunk_text", "category"],
});
```

Run filtered retrieval:

```ts
const filtered = await ns.query({
  rankBy: ["vector", "ANN", [0.1, 0.2, 0.3]],
  topK: 10,
  filters: ["And", [["category", "Eq", "schema"]]],
  includeAttributes: ["chunk_text", "category"],
});
```

## Python

Package:

```bash
pip install turbopuffer
```

Initialize one shared client:

```python
import os
import turbopuffer

tpuf = turbopuffer.Turbopuffer(
    api_key=os.getenv("TURBOPUFFER_API_KEY"),
    region="gcp-us-central1",
)

ns = tpuf.namespace("docs-example-py")
```

Write documents with schema:

```python
ns.write(
    upsert_rows=[
        {
            "id": "769c134d-07b8-4225-954a-b6cc5ffc320c",
            "vector": [0.1, 0.1],
            "text": "the fox is quick and brown",
            "permissions": [
                "ee1f7c89-a3aa-43c1-8941-c987ee03e7bc",
                "95cdf8be-98a9-4061-8eeb-2702b6bbcb9e",
            ],
        },
    ],
    distance_metric="cosine_distance",
    schema={
        "id": "uuid",
        "text": {
            "type": "string",
            "full_text_search": True,
        },
        "permissions": {
            "type": "[]uuid",
        },
    },
)
```

Run BM25 search:

```python
result = ns.query(
    rank_by=("text", "BM25", "quick fox"),
    top_k=10,
    include_attributes=["text"],
)
```

Run hybrid multi-query:

```python
response = ns.multi_query(
    queries=[
        {
            "rank_by": ("vector", "ANN", [0.1, 0.2]),
            "top_k": 10,
            "include_attributes": ["text"],
        },
        {
            "rank_by": ("text", "BM25", "quick fox"),
            "top_k": 10,
            "include_attributes": ["text"],
        },
    ]
)
```

## Practical Notes

- Reuse the client instance across requests.
- Keep `includeAttributes` or `include_attributes` minimal.
- Put hybrid fusion and reranking in your app layer.
- Verify exact SDK method names against the current installed version before large code changes.

Primary sources:

- https://turbopuffer.com/docs/vector
- https://turbopuffer.com/docs/query
- https://turbopuffer.com/docs/write
- Context7: `/turbopuffer/turbopuffer-typescript`
- Context7: `/turbopuffer/turbopuffer-python`
