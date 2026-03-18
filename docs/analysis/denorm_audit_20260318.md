# Denormalization Effectiveness Audit — Root Cause Analysis

**Date:** 2026-03-18
**Namespace:** `org_00Ddl000003yx57EAA` (ascendix-beta-sandbox)
**Method:** Code audit + Turbopuffer data audit + Salesforce CLI describe/SOQL verification
**Framing:** Systemic issues that would reproduce on any org deployment, not sandbox-specific fixes

---

## Root Cause 1: Partial Record Load — Operator Error, Not Code Bug

### Evidence

| Object | Original Load (9df0004, 2026-03-15) | Salesforce Today | Turbopuffer Today |
|--------|-------------------------------------|-----------------|-------------------|
| Property | 2,466 | 2,470 | 603 |
| Lease | 483 | 483 | 225 |
| Availability | 527 | *(not counted)* | 158 |
| Deal | *(not loaded)* | 2,391 | 0 |
| Sale | *(not loaded)* | 55 | 0 |

The original load (commit `9df0004`) successfully loaded 2,466 properties, 483 leases, 527 availabilities. The current Turbopuffer state (603/225/158) is **lower** than the original load — records were lost, possibly from a namespace wipe or partial re-load that overwrote the original data.

### Code analysis — the pipeline is correct

- `bulk_load.py` line 390: `object_names = args.objects or list(config.keys())` — default is all objects in config.
- `build_soql()` (denormalize.py line 104): builds `SELECT ... FROM {object_name}` with **no WHERE clause, no LIMIT**.
- `query_all()` (salesforce_client.py lines 388-418): handles Salesforce pagination via `nextRecordsUrl` loop until `done == True`.
- **No per-record error handling** in `load_object()` (lines 285-293) — one bad record would crash the entire object and stop processing. But this would produce a visible error, not a silent partial load.

### Root cause

The code would load all records from all configured objects. The partial state is from one of:
1. **`--objects` flag was used** to load only a subset (e.g., `--objects ascendix__Property__c ascendix__Lease__c ascendix__Availability__c`), which excluded Deal and Sale.
2. **A subsequent re-load or test overwrote the namespace** with fewer records (e.g., during CDC testing or a namespace wipe+reload with a different record set).
3. **An error mid-pipeline** crashed the embedding or upsert stage partway through, and the operator didn't notice.

### Systemic fix needed

None for the query/pagination code — it works. But three robustness gaps exist:

**Gap A: No load validation step.** After bulk_load completes, there's no count verification — "I loaded N records, Turbopuffer has N records for this object_type." A simple post-load count check would catch partial loads immediately.

**Gap B: No per-record error tolerance.** A single malformed record in the flatten/text/embed loop crashes the entire object. The pipeline should catch per-record errors, log them, and continue with the remaining records.

**Gap C: No parent-change propagation.** Denormalized parent fields (Market name, Owner name, Property address on child records, etc.) are snapshots taken at bulk-load or CDC-sync time. If a parent record changes — Geography renamed, Account merged, Property address updated — the denormalized children in the index go stale silently. The current CDC pipeline only watches the 5 POC objects; it does not re-denormalize children when a parent changes.

This was observed directly: Geography records were seeded in Salesforce on 2026-03-18, but the 29 properties that reference them still show no `market_name` in Turbopuffer because the Property records themselves weren't modified (no CDC event fired).

**Short-term mitigation:** Periodic full re-load (e.g., nightly or weekly) to refresh all denormalized fields. **Long-term fix (scope TBD):** Subscribe to CDC on parent objects (Account, Geography) and re-denormalize affected children when a parent changes. This requires mapping parent→child relationships in reverse and is a meaningful design effort — flagging here for future scoping, not as a Phase 3 blocker.

---

## Root Cause 2: Missing Relationships — Config Generator Works but Was Bypassed

### How the generator discovers relationships

`generate_denorm_config.py` iterates ALL reference fields from `describe()`:

```python
# Line 266-268
if f.get("type") == "reference" and f.get("referenceTo"):
    meta.reference_fields[name] = f["referenceTo"][0]
```

Then in `build_config_for_object()` (line 450), **every reference field** gets a parent section — no scoring threshold, no filtering. If a field is type=reference, it becomes a parent.

For each parent, it includes:
1. Parent's nameField (always)
2. Parent's compact layout fields
3. Dot-notation columns from child list views that reference this parent

### What actually happened

The current `denorm_config.yaml` header says:
```
# Corrected against live sandbox org 00Ddl000003yx57EAA
# Generated: 2026-03-15
```

But the generator's `--objects` default is only **3 objects**:
```python
# Line 893-897
default=[
    "ascendix__Property__c",
    "ascendix__Lease__c",
    "ascendix__Availability__c",
],
```

Deal and Sale are **not in the default**. They were added to the YAML manually later (they appear in the committed config but without the auto-generated score comments). The manual additions only included `ascendix__Property__c` as a parent — the other party relationships were never added.

### What the generator would have discovered (verified via `sf sobject describe`)

**Lease** has 15 reference fields. The generator would auto-include ALL of them as parents:

| Reference Field | Target | Currently in Config? |
|----------------|--------|---------------------|
| ascendix__Property__c | Property | Yes |
| ascendix__Tenant__c | Account | Yes |
| ascendix__OwnerLandlord__c | Account | Yes |
| ascendix__TenantRepBroker__c | Account | **NO — would be auto-discovered** |
| ascendix__ListingBrokerCompany__c | Account | **NO — would be auto-discovered** |
| ascendix__ListingBrokerContact__c | Contact | **NO — would be auto-discovered** |
| ascendix__TenantContact__c | Contact | **NO — would be auto-discovered** |
| ascendix__OwnerLandlordContact__c | Contact | **NO — would be auto-discovered** |
| ascendix__Floor__c | Floor | NO (low value) |
| ascendix__MasterLease__c | Lease | NO (self-ref) |
| ascendix__OriginatingDeal__c | Deal | NO (cross-object) |
| ascendix__SOM__c | SOM | NO (system) |
| + CreatedById, LastModifiedById | User | NO (system) |

**Deal** has 27 reference fields — the most relationship-heavy object. Salesforce data population:

| Reference Field | Target | Label | SF Fill (of 2,391) |
|----------------|--------|-------|-------------------|
| ascendix__Tenant__c | Account | Tenant | 1,280 (53.5%) |
| ascendix__Client__c | Account | Client | 1,008 (42.2%) |
| ascendix__Buyer__c | Account | Buyer | 631 (26.4%) |
| ascendix__OwnerLandlord__c | Account | Owner/Landlord | 293 (12.3%) |
| ascendix__ListingBrokerCompany__c | Account | Listing Broker Company | 174 (7.3%) |
| ascendix__Seller__c | Account | Seller | 55 (2.3%) |
| ascendix__TenantRepBroker__c | Account | Tenant Rep Broker | 20 (0.8%) |
| ascendix__BuyerRep__c | Account | Buyer Rep | — |
| ascendix__LeadBrokerCompany__c | Account | Lead Broker Company | — |
| ascendix__Lender__c | Account | Lender | — |
| ascendix__Property__c | Property | Property | — |
| ascendix__Availability__c | Availability | Availability | — |
| ascendix__Listing__c | Listing | Listing | — |
| + 10 Contact fields | Contact | Various contacts | — |
| + system fields | User/RecordType | — | — |

**Sale** has 17 reference fields:

| Reference Field | Target | Label | SF Fill (of 55) |
|----------------|--------|-------|----------------|
| ascendix__Buyer__c | Account | Buyer | 35 (63.6%) |
| ascendix__Seller__c | Account | Seller | 20 (36.4%) |
| ascendix__ListingBrokerCompany__c | Account | Listing Broker | 1 |
| ascendix__SellingBroker__c | Account | Selling Broker | 0 |
| ascendix__BuyerRep__c | Account | Buyer Rep | — |
| ascendix__Lender__c | Account | Lender | — |
| ascendix__Property__c | Property | Property | — |
| + 5 Contact fields, Floor, SOM, OriginatingDeal | — | — | — |

**Availability** has 10 reference fields including geography that's not in config:

| Reference Field | Target | Label | In Config? |
|----------------|--------|-------|-----------|
| ascendix__Property__c | Property | Property | Yes |
| ascendix__Market__c | Geography | Market | **NO** |
| ascendix__SubMarket__c | Geography | Sub Market | **NO** |
| ascendix__Region__c | Geography | Region | **NO** |
| ascendix__Listing__c | Listing | Listing | NO |
| ascendix__Floor__c | Floor | Floor | NO |

### Root cause

**The generator was never run against all 5 objects, and manually-added configs omitted relationships.** If `generate_denorm_config.py` had been run with `--objects ascendix__Property__c ascendix__Lease__c ascendix__Availability__c ascendix__Deal__c ascendix__Sale__c` against the live sandbox, it would have auto-discovered every reference field.

### Systemic fix needed

**Fix A: Add Deal and Sale to the generator's default object list.** Line 893-897 currently defaults to 3 objects. Should be all 5 POC objects.

**Fix B: Re-run the generator against the live org for all 5 objects.** This will auto-discover all party/broker/contact relationships. Then review and commit.

**Fix C (optional): Filter out low-value parent references.** The generator will include *every* reference field — including `CreatedById`, `LastModifiedById`, `ascendix__SOM__c`, `ascendix__Floor__c`, self-references, etc. A denylist of system/low-value parent objects would keep the config clean:
```python
PARENT_DENYLIST = {"User", "RecordType", "Group", "ascendix__SOM__c"}
```

---

## Root Cause 3: Ambiguous Text Labels — Design Gap in `build_text()`

### The problem

`build_text()` in denormalize.py (line 174-179):
```python
for ref_field, pfield_names in parent_config.items():
    parent_vals = parent_fields.get(ref_field, {})
    for pf in pfield_names:
        val = parent_vals.get(pf)
        if val is not None:
            parts.append(f"{clean_label(pf)}: {val}")
```

This uses the **parent field name** as the label, not the **relationship name**. When multiple parents have a `Name` field (Property.Name, Tenant.Name, Owner.Name), they all appear as `Name: <value>` in the embedding text.

### Example

A Lease record text today:
```
Lease: | Name: Suite 4300 | Name: Preston Park Financial Center | City: Plano | State: TX | Name: Stone Miller
```

Three different `Name:` values — the embedding model cannot distinguish property from tenant from owner.

### Contrast with document keys

`build_document()` (line 218-224) **does** use the relationship prefix:
```python
prefix = clean_label(ref_field).lower()
doc[f"{prefix}_{clean_label(pf).lower()}"] = val
```

This produces `tenant_name`, `ownerlandlord_name`, `property_name` — correctly disambiguated. But the text field used for BM25 and embedding doesn't get this treatment.

### Systemic fix

Change `build_text()` line 179 from:
```python
parts.append(f"{clean_label(pf)}: {val}")
```
to:
```python
parts.append(f"{clean_label(ref_field)} {clean_label(pf)}: {val}")
```

This would produce:
```
Lease: | Name: Suite 4300 | Property Name: Preston Park Financial Center | Property City: Plano | Tenant Name: Stone Miller | OwnerLandlord Name: Edwards RE Partners
```

This is a one-line fix that works on any org — no config change needed.

---

## Root Cause 4: Inactive/Expired Records Indexed — No Status Filtering

### The problem

`build_soql()` generates `SELECT ... FROM {object_name}` with no WHERE clause. Every record is indexed regardless of status, including:
- Expired leases (46% of loaded leases have `termexpirationdate < today`)
- Closed/inactive availabilities
- Closed/lost deals

### Salesforce's active/inactive metaphor

CRE objects don't have a universal `IsActive` flag. Status varies by object:
- **Lease:** `ascendix__TermExpirationDate__c` (date comparison) or a status picklist if present
- **Availability:** `ascendix__Status__c` (picklist — "Open", "Closed", etc.)
- **Deal:** `ascendix__Stage__c` / `ascendix__Status__c` (picklist — "Closed Won", "Closed Lost", etc.)
- **Sale:** `ascendix__Status__c` (picklist)

### Design decision for dev

**Option A: Index-time filtering** — Add configurable WHERE clauses per object in denorm_config.yaml:
```yaml
ascendix__Lease__c:
  filter: "ascendix__TermExpirationDate__c >= TODAY OR ascendix__TermExpirationDate__c = null"
  # ... fields ...
```
Pro: Smaller index, no expired data in results. Con: Loses historical query capability.

**Option B: Query-time filtering** — Always index everything, let the query Lambda filter with `termexpirationdate_gte: "2026-01-01"` when the user asks about "current" leases.
Pro: Preserves history. Con: Requires the LLM to know when to add date filters.

**Option C: Soft filtering via metadata** — Index everything but add a computed `is_active` field at denorm time. The LLM or user can filter on it.
Pro: Best of both worlds. Con: Requires defining "active" per object type.

**Recommendation:** Option C — add a computed `is_active` boolean at denorm time. The definition is config-driven per object. Defer to dev for implementation.

---

## Root Cause 5: Market/SubMarket — Sandbox Data Issue (Resolved)

**Original finding (2026-03-18 morning):** 29 properties had `ascendix__Market__c` populated but pointing to deleted Geography records. Only 1 Geography record (Austin) existed.

**Status: PATCHED.** Geography data has been seeded. Current state:

| Type | Count | Examples |
|------|-------|---------|
| Region | 4 | US South, US Northeast, US Southeast, Europe |
| Market | 14 | Dallas-Fort Worth (17 props), New York Metro (7), Dublin (3), Austin, Houston, etc. |
| Sub Market | 12 | Downtown/Uptown Dallas (2), Plano/Legacy, Frisco North, Midtown Manhattan, etc. |

**Property geography fill:**
- Market: 29 of 2,470 properties (1.2%) — low, but now resolving correctly
- SubMarket: 5 of 2,470 properties (0.2%)
- PPFC now resolves to Market = **Dallas-Fort Worth**, SubMarket = null

**Availability geography fill:**
- Market: 25 availabilities have Market links
- SubMarket/Region: 0

**Conclusion:** The pipeline code was always correct — it handles null parents gracefully. The prior 0% fill was caused by deleted Geography records, now restored. The remaining low fill rate (29/2,470 for Market) is a data assignment task, not a code issue. On a production org with Geography data maintained, the pipeline will denormalize market/submarket automatically.

**Note for dev:** Availability has its own `ascendix__Market__c`, `ascendix__SubMarket__c`, and `ascendix__Region__c` geography fields (confirmed via `sf sobject describe`). These are **not in the current denorm_config.yaml** and should be added when the generator is re-run (RC-2b).

---

## Summary: Systemic Issues for Dev

| # | Root Cause | Category | Fix |
|---|-----------|----------|-----|
| **RC-1a** | No post-load count verification | bulk_load.py | Add count check after upsert: "Expected N, got N in Turbopuffer" |
| **RC-1b** | No per-record error tolerance | bulk_load.py | try/except around per-record flatten/text/embed, log and continue |
| **RC-1c** | No parent-change propagation | Architecture | Parent changes (Geography, Account) don't trigger child re-denorm. Short-term: periodic re-load. Long-term: parent CDC subscription (scope TBD) |
| **RC-2a** | Generator defaults to 3 objects, not 5 | generate_denorm_config.py | Add Deal and Sale to `--objects` default |
| **RC-2b** | Config was hand-edited, bypassing auto-discovery | Process | Re-run generator against live org for all 5 objects |
| **RC-2c** | Generator includes system parents (User, RecordType, SOM) | generate_denorm_config.py | Add parent object denylist |
| **RC-3** | `build_text()` uses parent field name, not relationship name | denormalize.py | Prefix with `clean_label(ref_field)` — one-line fix |
| **RC-4** | No status/expiration filtering | denormalize.py + config | Add computed `is_active` field per object type |
| ~~RC-5~~ | ~~Market/SubMarket Geography deleted~~ | ~~Sandbox data~~ | ~~**RESOLVED** — Geography seeded (30 records). Pipeline was correct.~~ |

### Priority order (systemic impact)

1. **RC-2a + RC-2b**: Re-run generator with all 5 objects → auto-discovers all relationships
2. **RC-3**: Fix `build_text()` label ambiguity → one-line change, improves all embedding quality
3. **RC-1a + RC-1b**: Add load validation + per-record error handling → prevents silent data loss
4. **RC-4**: Add `is_active` computed field → design decision needed first
5. **RC-2c**: Parent denylist → quality-of-life, prevents noise from system references

### Sandbox data status (not systemic — patched 2026-03-18)

- Geography: **Resolved.** 30 records seeded (4 regions, 14 markets, 12 submarkets). 29 properties now resolve to markets (e.g., PPFC → Dallas-Fort Worth).
- Property field sparsity (PropertyClass 3.8%, TotalBuildingArea 1.2%): Sandbox data quality. Pipeline correct.
- Deal/Sale record counts (2,391 / 55): Exist in SF, never bulk-loaded. Addressed by RC-2a.
