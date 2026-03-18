#!/usr/bin/env python3
"""
Seed a pragmatic Geography catalog and remap orphaned Property market/submarket lookups.

This script is designed to bridge a sandbox data gap where Property records still
reference deleted Geography rows. It creates a modest market/submarket catalog,
reuses existing Geography rows when possible, and updates the affected Property
records to point at the new seeded Geography rows.

Default behavior is dry-run. Use --apply to make Salesforce changes.

Examples:
    python3 scripts/one-off/seed_geography_bridge.py
    python3 scripts/one-off/seed_geography_bridge.py --target-org ascendix-beta-sandbox
    python3 scripts/one-off/seed_geography_bridge.py --apply
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shlex
import subprocess
import sys
from dataclasses import dataclass
from typing import Any

SF_TARGET_ORG = os.environ.get("SF_TARGET_ORG", "ascendix-beta-sandbox")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
LOGGER = logging.getLogger("seed_geography_bridge")


@dataclass(frozen=True)
class GeographySeed:
    key: str
    name: str
    geo_type: str
    parent_key: str | None = None


PRAGMATIC_GEOGRAPHY_SEEDS: list[GeographySeed] = [
    GeographySeed("region:us_south", "US South", "Region"),
    GeographySeed("region:us_northeast", "US Northeast", "Region"),
    GeographySeed("region:us_southeast", "US Southeast", "Region"),
    GeographySeed("region:europe", "Europe", "Region"),
    GeographySeed("market:austin", "Austin", "Market", parent_key="region:us_south"),
    GeographySeed("market:atlanta", "Atlanta", "Market", parent_key="region:us_southeast"),
    GeographySeed("market:chicago", "Chicago", "Market", parent_key="region:us_northeast"),
    GeographySeed(
        "market:dallas_fort_worth",
        "Dallas-Fort Worth",
        "Market",
        parent_key="region:us_south",
    ),
    GeographySeed(
        "market:daytona_beach",
        "Daytona Beach",
        "Market",
        parent_key="region:us_southeast",
    ),
    GeographySeed("market:denver", "Denver", "Market", parent_key="region:us_south"),
    GeographySeed("market:dublin", "Dublin", "Market", parent_key="region:europe"),
    GeographySeed("market:houston", "Houston", "Market", parent_key="region:us_south"),
    GeographySeed(
        "market:los_angeles",
        "Los Angeles",
        "Market",
        parent_key="region:us_south",
    ),
    GeographySeed("market:miami", "Miami", "Market", parent_key="region:us_southeast"),
    GeographySeed(
        "market:new_york_metro",
        "New York Metro",
        "Market",
        parent_key="region:us_northeast",
    ),
    GeographySeed("market:phoenix", "Phoenix", "Market", parent_key="region:us_south"),
    GeographySeed(
        "market:san_francisco_bay_area",
        "San Francisco Bay Area",
        "Market",
        parent_key="region:us_south",
    ),
    GeographySeed(
        "market:st_augustine",
        "St. Augustine",
        "Market",
        parent_key="region:us_southeast",
    ),
    GeographySeed(
        "submarket:cedars_south_downtown",
        "Cedars / South Downtown Dallas",
        "Sub Market",
        parent_key="market:dallas_fort_worth",
    ),
    GeographySeed(
        "submarket:central_dallas",
        "Downtown / Uptown Dallas",
        "Sub Market",
        parent_key="market:dallas_fort_worth",
    ),
    GeographySeed(
        "submarket:plano_legacy",
        "Plano / Legacy",
        "Sub Market",
        parent_key="market:dallas_fort_worth",
    ),
    GeographySeed(
        "submarket:frisco_north",
        "Frisco North",
        "Sub Market",
        parent_key="market:dallas_fort_worth",
    ),
    GeographySeed(
        "submarket:midtown_manhattan",
        "Midtown Manhattan",
        "Sub Market",
        parent_key="market:new_york_metro",
    ),
    GeographySeed(
        "submarket:lower_manhattan",
        "Financial District / Lower Manhattan",
        "Sub Market",
        parent_key="market:new_york_metro",
    ),
    GeographySeed(
        "submarket:downtown_brooklyn",
        "Downtown Brooklyn",
        "Sub Market",
        parent_key="market:new_york_metro",
    ),
    GeographySeed(
        "submarket:ifsc",
        "IFSC",
        "Sub Market",
        parent_key="market:dublin",
    ),
    GeographySeed(
        "submarket:south_city_centre",
        "South City Centre",
        "Sub Market",
        parent_key="market:dublin",
    ),
    GeographySeed(
        "submarket:blanchardstown",
        "Blanchardstown",
        "Sub Market",
        parent_key="market:dublin",
    ),
    GeographySeed(
        "submarket:mason_ave_corridor",
        "Mason Ave Corridor",
        "Sub Market",
        parent_key="market:daytona_beach",
    ),
    GeographySeed(
        "submarket:st_augustine_west",
        "St. Augustine West",
        "Sub Market",
        parent_key="market:st_augustine",
    ),
]

ORPHAN_MARKET_TO_SEED_KEY = {
    "a0Rfk0000003dPpEAI": "market:dallas_fort_worth",
    "a0Rfk0000003dQ4EAI": "market:dallas_fort_worth",
    "a0Rfk0000003dQ5EAI": "market:new_york_metro",
    "a0Rfk0000003dQ7EAI": "market:dallas_fort_worth",
    "a0Rfk0000003dQAEAY": "market:daytona_beach",
    "a0Rfk0000003dQBEAY": "market:dallas_fort_worth",
    "a0Rfk0000003dQJEAY": "market:dublin",
    "a0Rfk0000003dQMEAY": "market:dallas_fort_worth",
    "a0Rfk0000003dQUEAY": "market:st_augustine",
}

ORPHAN_SUBMARKET_TO_SEED_KEY = {
    "a0Rfk0000003dQ0EAI": "submarket:cedars_south_downtown",
    "a0Rfk0000003dQ3EAI": "submarket:central_dallas",
    "a0Rfk0000003dQ8EAI": "submarket:mason_ave_corridor",
    "a0Rfk0000003dQVEAY": "submarket:st_augustine_west",
}

ORPHAN_REGION_TO_SEED_KEY = {
    "a0Rfk0000003dQ6EAI": "region:us_south",
    "a0Rfk0000003dQEEAY": "region:us_northeast",
    "a0Rfk0000003dQTEAY": "region:us_southeast",
}

MARKET_TO_REGION_SEED_KEY = {
    "market:austin": "region:us_south",
    "market:atlanta": "region:us_southeast",
    "market:chicago": "region:us_northeast",
    "market:dallas_fort_worth": "region:us_south",
    "market:daytona_beach": "region:us_southeast",
    "market:denver": "region:us_south",
    "market:dublin": "region:europe",
    "market:houston": "region:us_south",
    "market:los_angeles": "region:us_south",
    "market:miami": "region:us_southeast",
    "market:new_york_metro": "region:us_northeast",
    "market:phoenix": "region:us_south",
    "market:san_francisco_bay_area": "region:us_south",
    "market:st_augustine": "region:us_southeast",
}


class SalesforceCliError(RuntimeError):
    pass


class GeographyBridgeSeeder:
    def __init__(self, target_org: str, apply: bool) -> None:
        self.target_org = target_org
        self.apply = apply
        self.seed_by_key = {seed.key: seed for seed in PRAGMATIC_GEOGRAPHY_SEEDS}
        self.seed_ids: dict[str, str] = {}
        self.stats = {
            "geographies_created": 0,
            "geographies_updated": 0,
            "geographies_reused": 0,
            "properties_updated": 0,
            "properties_skipped": 0,
        }

    def run(self) -> int:
        self.verify_sf_connection()
        existing_geos = self.fetch_existing_geographies()
        self.ensure_seed_geographies(existing_geos)
        properties = self.fetch_orphaned_properties()
        self.remap_properties(properties)
        self.log_summary()
        return 0

    def verify_sf_connection(self) -> None:
        LOGGER.info("Verifying Salesforce CLI access to %s", self.target_org)
        result = self.sf_json(["org", "display", "--target-org", self.target_org, "--json"])
        org = result.get("result", {})
        LOGGER.info(
            "Connected to %s (%s)",
            org.get("username", "unknown"),
            org.get("instanceUrl", "unknown"),
        )

    def sf_json(self, args: list[str]) -> dict[str, Any]:
        cmd = ["sf", *args]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            raise SalesforceCliError(
                f"Command failed: {' '.join(shlex.quote(part) for part in cmd)}\n"
                f"stderr: {result.stderr.strip()}"
            )

        payload = result.stdout.strip() or result.stderr.strip()
        try:
            data = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise SalesforceCliError(
                f"Failed to parse JSON from {' '.join(shlex.quote(part) for part in cmd)}"
            ) from exc

        if data.get("status") not in (None, 0):
            raise SalesforceCliError(
                f"CLI returned non-zero status for {' '.join(shlex.quote(part) for part in cmd)}: "
                f"{data.get('message') or data}"
            )
        return data

    def soql(self, query: str) -> list[dict[str, Any]]:
        data = self.sf_json(
            ["data", "query", "--target-org", self.target_org, "--query", query, "--json"]
        )
        return data.get("result", {}).get("records", [])

    def values_arg(self, values: dict[str, Any]) -> str:
        parts = []
        for key, value in values.items():
            if value is None:
                continue
            escaped = str(value).replace("\\", "\\\\").replace("'", "\\'")
            parts.append(f"{key}='{escaped}'")
        return " ".join(parts)

    def create_record(self, sobject: str, values: dict[str, Any]) -> str:
        if not self.apply:
            LOGGER.info("[DRY RUN] Create %s: %s", sobject, values)
            return f"dry-run-{sobject}-{values.get('ascendix__SourceSystemNumber__c', values.get('Name', 'record'))}"

        data = self.sf_json(
            [
                "data",
                "create",
                "record",
                "--target-org",
                self.target_org,
                "--sobject",
                sobject,
                "--values",
                self.values_arg(values),
                "--json",
            ]
        )
        record_id = data.get("result", {}).get("id")
        if not record_id:
            raise SalesforceCliError(f"Create did not return an id for {sobject}: {values}")
        return record_id

    def update_record(self, sobject: str, record_id: str, values: dict[str, Any]) -> None:
        if not values:
            return
        if not self.apply:
            LOGGER.info("[DRY RUN] Update %s %s: %s", sobject, record_id, values)
            return

        self.sf_json(
            [
                "data",
                "update",
                "record",
                "--target-org",
                self.target_org,
                "--sobject",
                sobject,
                "--record-id",
                record_id,
                "--values",
                self.values_arg(values),
                "--json",
            ]
        )

    def fetch_existing_geographies(self) -> list[dict[str, Any]]:
        LOGGER.info("Loading existing Geography rows")
        return self.soql(
            "SELECT Id, Name, ascendix__Type__c, ascendix__Parent__c, "
            "ascendix__SourceSystemNumber__c "
            "FROM ascendix__Geography__c"
        )

    def fetch_orphaned_properties(self) -> list[dict[str, Any]]:
        LOGGER.info("Loading Properties with market/submarket references")
        return self.soql(
            "SELECT Id, Name, ascendix__City__c, ascendix__State__c, ascendix__Street__c, "
            "ascendix__Market__c, ascendix__SubMarket__c "
            "FROM ascendix__Property__c "
            "WHERE ascendix__Market__c != NULL OR ascendix__SubMarket__c != NULL "
            "ORDER BY ascendix__City__c, Name"
        )

    def ensure_seed_geographies(self, existing_geos: list[dict[str, Any]]) -> None:
        existing_by_source = {
            rec.get("ascendix__SourceSystemNumber__c"): rec
            for rec in existing_geos
            if rec.get("ascendix__SourceSystemNumber__c")
        }
        existing_by_name_type = {
            (str(rec.get("Name", "")).strip().lower(), rec.get("ascendix__Type__c")): rec
            for rec in existing_geos
        }

        markets = [seed for seed in PRAGMATIC_GEOGRAPHY_SEEDS if seed.parent_key is None]
        submarkets = [seed for seed in PRAGMATIC_GEOGRAPHY_SEEDS if seed.parent_key is not None]

        for seed in [*markets, *submarkets]:
            desired_parent_id = self.seed_ids.get(seed.parent_key) if seed.parent_key else None
            record = existing_by_source.get(seed.key)
            source = "source_key"
            if record is None:
                record = existing_by_name_type.get((seed.name.lower(), seed.geo_type))
                source = "name_type"

            if record:
                self.seed_ids[seed.key] = record["Id"]
                updates = {}
                if source == "name_type" and record.get("ascendix__SourceSystemNumber__c") != seed.key:
                    updates["ascendix__SourceSystemNumber__c"] = seed.key
                if desired_parent_id and record.get("ascendix__Parent__c") != desired_parent_id:
                    updates["ascendix__Parent__c"] = desired_parent_id

                if updates:
                    LOGGER.info(
                        "Reusing Geography %s (%s) and normalizing metadata",
                        record["Id"],
                        seed.name,
                    )
                    self.update_record("ascendix__Geography__c", record["Id"], updates)
                    self.stats["geographies_updated"] += 1
                else:
                    LOGGER.info("Reusing Geography %s for %s", record["Id"], seed.name)
                    self.stats["geographies_reused"] += 1
                continue

            values = {
                "Name": seed.name,
                "ascendix__Type__c": seed.geo_type,
                "ascendix__SourceSystemNumber__c": seed.key,
                "ascendix__Parent__c": desired_parent_id,
            }
            record_id = self.create_record("ascendix__Geography__c", values)
            self.seed_ids[seed.key] = record_id
            self.stats["geographies_created"] += 1
            LOGGER.info("Seeded Geography %s -> %s", seed.name, record_id)

    def remap_properties(self, properties: list[dict[str, Any]]) -> None:
        LOGGER.info("Evaluating %d Properties for remapping", len(properties))
        unmatched_market_ids = set()
        unmatched_submarket_ids = set()
        unmatched_region_ids = set()

        for record in properties:
            current_region = record.get("ascendix__Region__c")
            current_market = record.get("ascendix__Market__c")
            current_submarket = record.get("ascendix__SubMarket__c")

            region_seed_key = ORPHAN_REGION_TO_SEED_KEY.get(current_region)
            market_seed_key = ORPHAN_MARKET_TO_SEED_KEY.get(current_market)
            submarket_seed_key = ORPHAN_SUBMARKET_TO_SEED_KEY.get(current_submarket)

            if current_region and region_seed_key is None:
                unmatched_region_ids.add(current_region)
            if current_market and market_seed_key is None:
                unmatched_market_ids.add(current_market)
            if current_submarket and submarket_seed_key is None:
                unmatched_submarket_ids.add(current_submarket)

            updates = {}
            if region_seed_key:
                updates["ascendix__Region__c"] = self.seed_ids[region_seed_key]
            elif market_seed_key:
                inferred_region = MARKET_TO_REGION_SEED_KEY.get(market_seed_key)
                if inferred_region:
                    updates["ascendix__Region__c"] = self.seed_ids[inferred_region]
            if market_seed_key:
                updates["ascendix__Market__c"] = self.seed_ids[market_seed_key]
            if submarket_seed_key:
                updates["ascendix__SubMarket__c"] = self.seed_ids[submarket_seed_key]

            if not updates:
                self.stats["properties_skipped"] += 1
                continue

            if (
                updates.get("ascendix__Region__c") == current_region
                and
                updates.get("ascendix__Market__c") == current_market
                and updates.get("ascendix__SubMarket__c") == current_submarket
            ):
                self.stats["properties_skipped"] += 1
                continue

            LOGGER.info(
                "Remap Property %s (%s, %s): region %s -> %s, market %s -> %s, "
                "submarket %s -> %s",
                record["Name"],
                record.get("ascendix__City__c"),
                record.get("ascendix__State__c"),
                current_region,
                updates.get("ascendix__Region__c", current_region),
                current_market,
                updates.get("ascendix__Market__c", current_market),
                current_submarket,
                updates.get("ascendix__SubMarket__c", current_submarket),
            )
            self.update_record("ascendix__Property__c", record["Id"], updates)
            self.stats["properties_updated"] += 1

        if unmatched_region_ids:
            LOGGER.warning("Unmatched region IDs left untouched: %s", sorted(unmatched_region_ids))
        if unmatched_market_ids:
            LOGGER.warning("Unmatched market IDs left untouched: %s", sorted(unmatched_market_ids))
        if unmatched_submarket_ids:
            LOGGER.warning(
                "Unmatched submarket IDs left untouched: %s", sorted(unmatched_submarket_ids)
            )

    def log_summary(self) -> None:
        mode = "APPLY" if self.apply else "DRY RUN"
        LOGGER.info("")
        LOGGER.info("=== Geography Bridge Summary (%s) ===", mode)
        LOGGER.info("Seed catalog size: %d", len(PRAGMATIC_GEOGRAPHY_SEEDS))
        LOGGER.info("Geographies created: %d", self.stats["geographies_created"])
        LOGGER.info("Geographies updated: %d", self.stats["geographies_updated"])
        LOGGER.info("Geographies reused: %d", self.stats["geographies_reused"])
        LOGGER.info("Properties updated: %d", self.stats["properties_updated"])
        LOGGER.info("Properties skipped: %d", self.stats["properties_skipped"])
        LOGGER.info("")
        LOGGER.info(
            "Note: Property remaps will emit CDC, but Availability docs will still lack "
            "submarket text until denorm config/indexing is expanded."
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Seed pragmatic Geography rows and remap orphaned Property geography lookups.",
    )
    parser.add_argument(
        "--target-org",
        default=SF_TARGET_ORG,
        help=f"Salesforce target org alias (default: {SF_TARGET_ORG})",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Persist changes to Salesforce. Omit for dry-run.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        seeder = GeographyBridgeSeeder(target_org=args.target_org, apply=args.apply)
        return seeder.run()
    except SalesforceCliError as exc:
        LOGGER.error(str(exc))
        return 2
    except KeyboardInterrupt:
        LOGGER.error("Interrupted")
        return 130


if __name__ == "__main__":
    sys.exit(main())
