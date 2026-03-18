#!/usr/bin/env python3
"""
Seed a pragmatic Geography catalog and remap orphaned Property/Availability geography lookups.

This script is designed to bridge sandbox data gaps where records still reference
deleted Geography rows. It creates a modest region/market/submarket catalog,
reuses existing Geography rows when possible, and updates the affected Property
and Availability records to point at the new seeded Geography rows.

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
    GeographySeed("region:us_west", "US West", "Region"),
    GeographySeed("region:us_midwest", "US Midwest", "Region"),
    GeographySeed("region:us_northeast", "US Northeast", "Region"),
    GeographySeed("region:us_mid_atlantic", "US Mid-Atlantic", "Region"),
    GeographySeed("region:us_southeast", "US Southeast", "Region"),
    GeographySeed("region:canada", "Canada", "Region"),
    GeographySeed("region:australia", "Australia", "Region"),
    GeographySeed("region:europe", "Europe", "Region"),
    GeographySeed("market:austin", "Austin", "Market", parent_key="region:us_south"),
    GeographySeed("market:atlanta", "Atlanta", "Market", parent_key="region:us_southeast"),
    GeographySeed("market:barrie", "Barrie", "Market", parent_key="region:canada"),
    GeographySeed("market:belleville", "Belleville", "Market", parent_key="region:canada"),
    GeographySeed("market:boston", "Boston", "Market", parent_key="region:us_northeast"),
    GeographySeed("market:brisbane", "Brisbane", "Market", parent_key="region:australia"),
    GeographySeed("market:calgary", "Calgary", "Market", parent_key="region:canada"),
    GeographySeed("market:chicago", "Chicago", "Market", parent_key="region:us_midwest"),
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
    GeographySeed("market:denver", "Denver", "Market", parent_key="region:us_west"),
    GeographySeed("market:dublin", "Dublin", "Market", parent_key="region:europe"),
    GeographySeed("market:houston", "Houston", "Market", parent_key="region:us_south"),
    GeographySeed(
        "market:los_angeles",
        "Los Angeles",
        "Market",
        parent_key="region:us_west",
    ),
    GeographySeed("market:miami", "Miami", "Market", parent_key="region:us_southeast"),
    GeographySeed("market:montreal", "Montreal", "Market", parent_key="region:canada"),
    GeographySeed(
        "market:new_york_metro",
        "New York Metro",
        "Market",
        parent_key="region:us_northeast",
    ),
    GeographySeed(
        "market:orange_county",
        "Orange County",
        "Market",
        parent_key="region:us_west",
    ),
    GeographySeed("market:orlando", "Orlando", "Market", parent_key="region:us_southeast"),
    GeographySeed("market:phoenix", "Phoenix", "Market", parent_key="region:us_south"),
    GeographySeed("market:sacramento", "Sacramento", "Market", parent_key="region:us_west"),
    GeographySeed("market:san_diego", "San Diego", "Market", parent_key="region:us_west"),
    GeographySeed(
        "market:san_francisco_bay_area",
        "San Francisco Bay Area",
        "Market",
        parent_key="region:us_west",
    ),
    GeographySeed(
        "market:san_antonio",
        "San Antonio",
        "Market",
        parent_key="region:us_south",
    ),
    GeographySeed("market:st_louis", "St. Louis", "Market", parent_key="region:us_midwest"),
    GeographySeed(
        "market:st_augustine",
        "St. Augustine",
        "Market",
        parent_key="region:us_southeast",
    ),
    GeographySeed("market:tampa_bay", "Tampa Bay", "Market", parent_key="region:us_southeast"),
    GeographySeed("market:toronto", "Toronto", "Market", parent_key="region:canada"),
    GeographySeed("market:vancouver", "Vancouver", "Market", parent_key="region:canada"),
    GeographySeed(
        "market:virginia_tidewater",
        "Virginia Tidewater",
        "Market",
        parent_key="region:us_mid_atlantic",
    ),
    GeographySeed(
        "market:washington_dc_metro",
        "Washington DC Metro",
        "Market",
        parent_key="region:us_mid_atlantic",
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
        "submarket:clayton",
        "Clayton",
        "Sub Market",
        parent_key="market:st_louis",
    ),
    GeographySeed(
        "submarket:downtown_dc",
        "Downtown DC",
        "Sub Market",
        parent_key="market:washington_dc_metro",
    ),
    GeographySeed(
        "submarket:downtown_san_diego",
        "Downtown San Diego",
        "Sub Market",
        parent_key="market:san_diego",
    ),
    GeographySeed(
        "submarket:mason_ave_corridor",
        "Mason Ave Corridor",
        "Sub Market",
        parent_key="market:daytona_beach",
    ),
    GeographySeed(
        "submarket:northeast_san_antonio_live_oak",
        "Northeast San Antonio / Live Oak",
        "Sub Market",
        parent_key="market:san_antonio",
    ),
    GeographySeed(
        "submarket:northwest_san_antonio",
        "Northwest San Antonio",
        "Sub Market",
        parent_key="market:san_antonio",
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
    "market:barrie": "region:canada",
    "market:belleville": "region:canada",
    "market:boston": "region:us_northeast",
    "market:brisbane": "region:australia",
    "market:calgary": "region:canada",
    "market:chicago": "region:us_midwest",
    "market:dallas_fort_worth": "region:us_south",
    "market:daytona_beach": "region:us_southeast",
    "market:denver": "region:us_west",
    "market:dublin": "region:europe",
    "market:houston": "region:us_south",
    "market:los_angeles": "region:us_west",
    "market:miami": "region:us_southeast",
    "market:montreal": "region:canada",
    "market:new_york_metro": "region:us_northeast",
    "market:orange_county": "region:us_west",
    "market:orlando": "region:us_southeast",
    "market:phoenix": "region:us_west",
    "market:sacramento": "region:us_west",
    "market:san_diego": "region:us_west",
    "market:san_antonio": "region:us_south",
    "market:san_francisco_bay_area": "region:us_west",
    "market:st_louis": "region:us_midwest",
    "market:st_augustine": "region:us_southeast",
    "market:tampa_bay": "region:us_southeast",
    "market:toronto": "region:canada",
    "market:vancouver": "region:canada",
    "market:virginia_tidewater": "region:us_mid_atlantic",
    "market:washington_dc_metro": "region:us_mid_atlantic",
}

ORPHAN_AVAILABILITY_MARKET_TO_SEED_KEY = {
    "a0Rfk0000003dQCEAY": "market:san_antonio",
    "a0Rfk0000003dQDEAY": "market:san_antonio",
    "a0Rfk0000003dQJEAY": "market:dublin",
}

AVAILABILITY_MARKET_TO_SUBMARKET_SEED_KEY = {
    "a0Rfk0000003dQCEAY": "submarket:northwest_san_antonio",
    "a0Rfk0000003dQDEAY": "submarket:northeast_san_antonio_live_oak",
}

AVAILABILITY_PROPERTY_TO_SUBMARKET_SEED_KEY = {
    "4 Custom House Plaza, IFSC, Dublin 1, D01 R3K6": "submarket:ifsc",
    "Plaza 211, Blanchardstown Corporate Park": "submarket:blanchardstown",
}

PROPERTY_EXACT_ASSIGNMENTS = {
    "1 Commerical Avenue": {"market": "market:new_york_metro"},
    "1 Sansome St": {"market": "market:san_francisco_bay_area"},
    "100 Main St. Fort worth (Gas Station)": {"market": "market:dallas_fort_worth"},
    "1001 Connecticut Ave NW": {
        "market": "market:washington_dc_metro",
        "submarket": "submarket:downtown_dc",
    },
    "10037 Menchaca RD": {"market": "market:austin"},
    "101 NW 20th St": {"market": "market:miami"},
    "105 Brazil St": {"market": "market:los_angeles"},
    "11 Faneuil St, Brighton, MA 02135": {"market": "market:boston"},
    "11151 TRADE CENTER DRIVE": {"market": "market:sacramento"},
    "1120 Galveston Ave": {"market": "market:dallas_fort_worth"},
    "1123 FLORES ST": {"market": "market:san_antonio"},
    "11245 Old FM 2243 Leander, TX": {"market": "market:austin"},
    "11507 Slater Dr": {"market": "market:dallas_fort_worth"},
    "1200 Ross Ave": {
        "market": "market:dallas_fort_worth",
        "submarket": "submarket:central_dallas",
    },
    "12221 Merit Drive": {"market": "market:dallas_fort_worth"},
    "1225 North Loop West": {"market": "market:houston"},
    "1250 René-Lévesque Boul O": {"market": "market:montreal"},
    "12707 Silicon Dr": {
        "market": "market:san_antonio",
        "submarket": "submarket:northeast_san_antonio_live_oak",
    },
    "1301 Fannin Office Tower": {"market": "market:houston"},
    "13080 Dallas Pky, Frisco, TX 75033": {
        "market": "market:dallas_fort_worth",
        "submarket": "submarket:frisco_north",
    },
    "135 S Lemon St, Orange, CA 92866": {"market": "market:orange_county"},
    "1400 Corporate Drive": {"market": "market:dallas_fort_worth"},
    "1411 5th Street": {"market": "market:los_angeles"},
    "1455 West Loop South": {"market": "market:houston"},
    "15 Adelaide Street Brisbane City QLD 4000": {"market": "market:brisbane"},
    "150 John F Kennedy Pky": {"market": "market:new_york_metro"},
    "1590 West 4th Ave": {"market": "market:vancouver"},
    "1595 S. OLD ORCHARD LN.": {"market": "market:dallas_fort_worth"},
    "1601 W Randol Mill Rd, Arlington, TX 76012": {"market": "market:dallas_fort_worth"},
    "161 Bridge Street": {"market": "market:belleville"},
    "1625 Grigsby Avenue": {"market": "market:dallas_fort_worth"},
    "1650 S. CHERRY LN": {"market": "market:dallas_fort_worth"},
    "16982 North Fwy": {"market": "market:houston"},
    "1700 Pacific Tower": {
        "market": "market:dallas_fort_worth",
        "submarket": "submarket:central_dallas",
    },
    "17Seventeen McKinney": {
        "market": "market:dallas_fort_worth",
        "submarket": "submarket:central_dallas",
    },
    "1801 N Greenville Ave": {"market": "market:dallas_fort_worth"},
    "1801 North Parkway": {"market": "market:chicago"},
    "18815 Intercontinental Crossing Dr": {"market": "market:houston"},
    "1905 Lawrence Rd": {"market": "market:houston"},
    "1954-1974 S Main St Weatherford, TX 76086": {"market": "market:dallas_fort_worth"},
    "19820 N 7th Ave, Phoenix, AZ 85027": {"market": "market:phoenix"},
    "20 N. Wacker Dr.": {"market": "market:chicago"},
    "2100 Ross Avenue": {
        "market": "market:dallas_fort_worth",
        "submarket": "submarket:central_dallas",
    },
    "2103 Coral Way": {"market": "market:miami"},
    "2180 General Booth Blvd - Hickman Place": {"market": "market:virginia_tidewater"},
    "225 Broadway": {
        "market": "market:san_diego",
        "submarket": "submarket:downtown_san_diego",
    },
    "2301-2303 Centennial Dr | Building 208": {"market": "market:dallas_fort_worth"},
    "23785 Cabot Blvd": {"market": "market:san_francisco_bay_area"},
    "239 George Street Brisbane City QLD 4000": {"market": "market:brisbane"},
    "2409 E 2nd Ave": {"market": "market:tampa_bay"},
    "2515 McKinney Ave": {
        "market": "market:dallas_fort_worth",
        "submarket": "submarket:central_dallas",
    },
    "2550 Arthur Ave": {"market": "market:chicago"},
    "260 Peachtree St NW": {"market": "market:atlanta"},
    "2600 Olive": {"market": "market:los_angeles"},
    "3 Park Central": {"market": "market:dallas_fort_worth"},
    "300 Frank W Burr Blvd": {"market": "market:new_york_metro"},
    "300-324 Washington Blvd": {"market": "market:chicago"},
    "301 Congress": {"market": "market:austin"},
    "301 Coronation Drive, Hill End, Milton, Brisbane, Queensland, 4064, Australia": {
        "market": "market:brisbane"
    },
    "3101 W 95th Street": {"market": "market:chicago"},
    "311 Sherbourne St": {"market": "market:toronto"},
    "3500 Aloma Ave, Winter Park, FL 32792": {"market": "market:orlando"},
    "353 E Park Ave": {"market": "market:san_diego"},
    "38 Ellen Street": {"market": "market:barrie"},
    "413 W Touhy Ave, Des Plaines, IL 60018": {"market": "market:chicago"},
    "44 Iffley Rd, Boston, MA 02130": {"market": "market:boston"},
    "443 Main St": {"market": "market:atlanta"},
    "4600 GEORGE WASHINGTON MEMORIAL HWY": {"market": "market:virginia_tidewater"},
    "47 E. South Street, Frederick, MD": {"market": "market:washington_dc_metro"},
    "500 North Brand": {"market": "market:los_angeles"},
    "5524-5986 S. Flamingo Rd": {"market": "market:miami"},
    "5551 NW 77th St | Boca Raton": {"market": "market:miami"},
    "5901 Florin Rd, Sacramento, CA 95823": {"market": "market:sacramento"},
    "611 Dog Track Rd": {"market": "market:orlando"},
    "6175 Main Street": {
        "market": "market:dallas_fort_worth",
        "submarket": "submarket:frisco_north",
    },
    "6309 Guhn Rd": {"market": "market:houston"},
    "6330 West Loop South": {"market": "market:houston"},
    "640 E Vista Way": {"market": "market:san_diego"},
    "6401 Broadway": {"market": "market:denver"},
    "650 Wellington St. E": {"market": "market:toronto"},
    "7410 Greenhaven Dr, Sacramento, CA 95831": {"market": "market:sacramento"},
    "75 INTERNATIONAL BLVD": {"market": "market:toronto"},
    "750 Orange City Square": {"market": "market:orange_county"},
    "8110-8220 Parkside Ave": {"market": "market:houston"},
    "8378-8384 Melrose Avenue": {"market": "market:los_angeles"},
    "8935 Research Drive": {"market": "market:orange_county"},
    "9250-9256 Acadie Blvd": {"market": "market:montreal"},
    "9753 Katy Freeway Houston, Texas 77024": {"market": "market:houston"},
    "Avco Center10850 Wilshire Blvd": {"market": "market:los_angeles"},
    "BMO Harris Bank": {"market": "market:st_louis"},
    "Bella Vista": {
        "market": "market:san_antonio",
        "submarket": "submarket:northeast_san_antonio_live_oak",
    },
    "Center 40 Executive": {"market": "market:st_louis"},
    "Chester Springs Shopping Center": {"market": "market:new_york_metro"},
    "City Center": {"market": "market:san_francisco_bay_area"},
    "City Center Fort Worth": {"market": "market:dallas_fort_worth"},
    "Collin Creek Village": {
        "market": "market:dallas_fort_worth",
        "submarket": "submarket:plano_legacy",
    },
    "Dyer Office Condo": {"market": "market:chicago"},
    "Former Golden Corral Buffet & Grill 2018 N Imperial Ave": {"market": "market:san_diego"},
    "Frost Bank Tower": {"market": "market:austin"},
    "HACIENDA PROFESSIONAL": {"market": "market:san_francisco_bay_area"},
    "Horizon Village": {"market": "market:phoenix"},
    "Huebner Commons West": {
        "market": "market:san_antonio",
        "submarket": "submarket:northwest_san_antonio",
    },
    "Kingsgate Mall": {"market": "market:vancouver"},
    "Lakeview Corners2409 Lakeview Pky": {"market": "market:dallas_fort_worth"},
    "Le 5600 Complex": {"market": "market:montreal"},
    "Lebanon Ohio Center": {
        "market": "market:dallas_fort_worth",
        "submarket": "submarket:frisco_north",
    },
    "Loudoun Station": {"market": "market:washington_dc_metro"},
    "Mapleview Barrie": {"market": "market:barrie"},
    "Merit Tower": {"market": "market:dallas_fort_worth"},
    "Metro Executive Center": {"market": "market:miami"},
    "Northpointe Centre": {"market": "market:dallas_fort_worth"},
    "Office Alpha": {"market": "market:dallas_fort_worth"},
    "Old Towne Building I": {
        "market": "market:st_louis",
        "submarket": "submarket:clayton",
    },
    "Old Towne Building II": {
        "market": "market:st_louis",
        "submarket": "submarket:clayton",
    },
    "Old Towne Building III": {
        "market": "market:st_louis",
        "submarket": "submarket:clayton",
    },
    "Pacific Gateway Towers": {"market": "market:san_diego"},
    "Palliser South - 140 10th Avenue SE": {"market": "market:calgary"},
    "Park Centre III": {"market": "market:san_francisco_bay_area"},
    "Pepper Square Shopping Center": {"market": "market:dallas_fort_worth"},
    "Plaza Las Campanas, Office": {
        "market": "market:san_antonio",
        "submarket": "submarket:northwest_san_antonio",
    },
    "Preston Parker Crossing": {
        "market": "market:dallas_fort_worth",
        "submarket": "submarket:plano_legacy",
    },
    "Randolph Center": {"market": "market:los_angeles"},
    "SUPREME GOLF WAREHOUSE OUTLET": {"market": "market:dallas_fort_worth"},
    "Smartcentres Aurora": {"market": "market:toronto"},
    "Sunset Medical Tower": {"market": "market:los_angeles"},
    "Symphony Towers": {
        "market": "market:san_diego",
        "submarket": "submarket:downtown_san_diego",
    },
    "TELUS Sky": {"market": "market:calgary"},
    "The Anitas": {"market": "market:houston"},
    "The Berkshire - Preston Center": {"market": "market:dallas_fort_worth"},
    "The Meadows Building": {"market": "market:dallas_fort_worth"},
    "The Plaza at Thousand Oaks": {
        "market": "market:san_antonio",
        "submarket": "submarket:northeast_san_antonio_live_oak",
    },
    "The Shops at Plaza Las Campanas": {
        "market": "market:san_antonio",
        "submarket": "submarket:northwest_san_antonio",
    },
    "Trammell Crow Center": {
        "market": "market:dallas_fort_worth",
        "submarket": "submarket:central_dallas",
    },
    "WELLS FARGO MEADOWBROOK": {"market": "market:dallas_fort_worth"},
    "Woods Walk Office": {"market": "market:miami"},
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
            "properties_failed": 0,
            "availabilities_updated": 0,
            "availabilities_skipped": 0,
            "availabilities_failed": 0,
        }

    def run(self) -> int:
        self.verify_sf_connection()
        existing_geos = self.fetch_existing_geographies()
        self.ensure_seed_geographies(existing_geos)
        properties = self.fetch_orphaned_properties()
        self.remap_properties(properties)
        availabilities = self.fetch_orphaned_availabilities()
        self.remap_availabilities(availabilities)
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

    def seed_key_for_geo_id(self, geo_id: str | None) -> str | None:
        if not geo_id:
            return None
        for seed_key, seeded_id in self.seed_ids.items():
            if seeded_id == geo_id:
                return seed_key
        return None

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
        LOGGER.info("Loading Properties for geography sync")
        return self.soql(
            "SELECT Id, Name, ascendix__City__c, ascendix__State__c, ascendix__Street__c, "
            "ascendix__Region__c, "
            "ascendix__Market__c, ascendix__SubMarket__c "
            "FROM ascendix__Property__c "
            "WHERE ascendix__Region__c != NULL OR ascendix__Market__c != NULL "
            "OR ascendix__SubMarket__c != NULL "
            "OR (ascendix__Street__c != NULL AND ascendix__City__c != NULL "
            "AND ascendix__State__c != NULL) "
            "ORDER BY ascendix__City__c, Name"
        )

    def fetch_orphaned_availabilities(self) -> list[dict[str, Any]]:
        LOGGER.info("Loading Availabilities for geography sync")
        return self.soql(
            "SELECT Id, Name, ascendix__Region__c, ascendix__Market__c, ascendix__SubMarket__c, "
            "ascendix__Property__r.Name, ascendix__Property__r.ascendix__City__c, "
            "ascendix__Property__r.ascendix__State__c, "
            "ascendix__Property__r.ascendix__Region__c, "
            "ascendix__Property__r.ascendix__Market__c, "
            "ascendix__Property__r.ascendix__SubMarket__c "
            "FROM ascendix__Availability__c "
            "WHERE ascendix__Region__c != NULL OR ascendix__Market__c != NULL "
            "OR ascendix__SubMarket__c != NULL "
            "OR ascendix__Property__r.ascendix__Region__c != NULL "
            "OR ascendix__Property__r.ascendix__Market__c != NULL "
            "OR ascendix__Property__r.ascendix__SubMarket__c != NULL "
            "ORDER BY ascendix__Property__r.Name, Name"
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
            exact_assignment = PROPERTY_EXACT_ASSIGNMENTS.get(record["Name"])

            if exact_assignment:
                market_seed_key = exact_assignment["market"]
                submarket_seed_key = exact_assignment.get("submarket")
                region_seed_key = MARKET_TO_REGION_SEED_KEY.get(market_seed_key)
            else:
                region_seed_key = ORPHAN_REGION_TO_SEED_KEY.get(current_region)
                market_seed_key = ORPHAN_MARKET_TO_SEED_KEY.get(current_market)
                submarket_seed_key = ORPHAN_SUBMARKET_TO_SEED_KEY.get(current_submarket)

            if (
                current_region
                and region_seed_key is None
                and self.seed_key_for_geo_id(current_region) is None
            ):
                unmatched_region_ids.add(current_region)
            if (
                current_market
                and market_seed_key is None
                and self.seed_key_for_geo_id(current_market) is None
            ):
                unmatched_market_ids.add(current_market)
            if (
                current_submarket
                and submarket_seed_key is None
                and self.seed_key_for_geo_id(current_submarket) is None
            ):
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
            try:
                self.update_record("ascendix__Property__c", record["Id"], updates)
                self.stats["properties_updated"] += 1
            except SalesforceCliError as exc:
                LOGGER.error(
                    "Failed to remap Property %s (%s): %s",
                    record["Name"],
                    record["Id"],
                    exc,
                )
                self.stats["properties_failed"] += 1

        if unmatched_region_ids:
            LOGGER.warning("Unmatched region IDs left untouched: %s", sorted(unmatched_region_ids))
        if unmatched_market_ids:
            LOGGER.warning("Unmatched market IDs left untouched: %s", sorted(unmatched_market_ids))
        if unmatched_submarket_ids:
            LOGGER.warning(
                "Unmatched submarket IDs left untouched: %s", sorted(unmatched_submarket_ids)
            )

    def remap_availabilities(self, availabilities: list[dict[str, Any]]) -> None:
        LOGGER.info("Evaluating %d Availabilities for remapping", len(availabilities))
        unmatched_region_ids = set()
        unmatched_market_ids = set()
        unmatched_submarket_ids = set()

        for record in availabilities:
            current_region = record.get("ascendix__Region__c")
            current_market = record.get("ascendix__Market__c")
            current_submarket = record.get("ascendix__SubMarket__c")
            property_record = record.get("ascendix__Property__r") or {}
            property_name = property_record.get("Name")
            property_region = property_record.get("ascendix__Region__c")
            property_market = property_record.get("ascendix__Market__c")
            property_submarket = property_record.get("ascendix__SubMarket__c")

            region_seed_key = ORPHAN_REGION_TO_SEED_KEY.get(current_region)
            market_seed_key = ORPHAN_AVAILABILITY_MARKET_TO_SEED_KEY.get(current_market)
            submarket_seed_key = ORPHAN_SUBMARKET_TO_SEED_KEY.get(current_submarket)

            # Availability submarkets were not populated consistently, so prefer
            # property-based inference for the few known cases and fall back to the
            # market-cluster mapping only when it is geographically tight.
            if submarket_seed_key is None and property_name:
                submarket_seed_key = AVAILABILITY_PROPERTY_TO_SUBMARKET_SEED_KEY.get(property_name)
            if submarket_seed_key is None and current_market:
                submarket_seed_key = AVAILABILITY_MARKET_TO_SUBMARKET_SEED_KEY.get(current_market)

            if (
                current_region
                and region_seed_key is None
                and self.seed_key_for_geo_id(current_region) is None
            ):
                unmatched_region_ids.add(current_region)
            if (
                current_market
                and market_seed_key is None
                and self.seed_key_for_geo_id(current_market) is None
            ):
                unmatched_market_ids.add(current_market)
            if (
                current_submarket
                and submarket_seed_key is None
                and self.seed_key_for_geo_id(current_submarket) is None
            ):
                unmatched_submarket_ids.add(current_submarket)

            target_region = current_region
            target_market = current_market
            target_submarket = current_submarket

            if property_region:
                target_region = property_region
            elif region_seed_key:
                target_region = self.seed_ids[region_seed_key]
            elif property_market:
                property_market_seed_key = self.seed_key_for_geo_id(property_market)
                if property_market_seed_key:
                    inferred_region = MARKET_TO_REGION_SEED_KEY.get(property_market_seed_key)
                    if inferred_region:
                        target_region = self.seed_ids[inferred_region]
            elif market_seed_key:
                inferred_region = MARKET_TO_REGION_SEED_KEY.get(market_seed_key)
                if inferred_region:
                    target_region = self.seed_ids[inferred_region]

            if property_market:
                target_market = property_market
            elif market_seed_key:
                target_market = self.seed_ids[market_seed_key]

            if property_submarket:
                target_submarket = property_submarket
            elif submarket_seed_key:
                target_submarket = self.seed_ids[submarket_seed_key]

            updates = {}
            if target_region and target_region != current_region:
                updates["ascendix__Region__c"] = target_region
            if target_market and target_market != current_market:
                updates["ascendix__Market__c"] = target_market
            if target_submarket and target_submarket != current_submarket:
                updates["ascendix__SubMarket__c"] = target_submarket

            if not updates:
                self.stats["availabilities_skipped"] += 1
                continue

            LOGGER.info(
                "Remap Availability %s (%s): property=%s, region %s -> %s, market %s -> %s, "
                "submarket %s -> %s",
                record["Name"],
                record["Id"],
                property_name,
                current_region,
                target_region,
                current_market,
                target_market,
                current_submarket,
                target_submarket,
            )
            try:
                self.update_record("ascendix__Availability__c", record["Id"], updates)
                self.stats["availabilities_updated"] += 1
            except SalesforceCliError as exc:
                LOGGER.error(
                    "Failed to remap Availability %s (%s): %s",
                    record["Name"],
                    record["Id"],
                    exc,
                )
                self.stats["availabilities_failed"] += 1

        if unmatched_region_ids:
            LOGGER.warning(
                "Unmatched availability region IDs left untouched: %s",
                sorted(unmatched_region_ids),
            )
        if unmatched_market_ids:
            LOGGER.warning(
                "Unmatched availability market IDs left untouched: %s",
                sorted(unmatched_market_ids),
            )
        if unmatched_submarket_ids:
            LOGGER.warning(
                "Unmatched availability submarket IDs left untouched: %s",
                sorted(unmatched_submarket_ids),
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
        LOGGER.info("Properties failed: %d", self.stats["properties_failed"])
        LOGGER.info("Availabilities updated: %d", self.stats["availabilities_updated"])
        LOGGER.info("Availabilities skipped: %d", self.stats["availabilities_skipped"])
        LOGGER.info("Availabilities failed: %d", self.stats["availabilities_failed"])
        LOGGER.info("")
        LOGGER.info(
            "Note: Live lookups are repaired here, but search docs will not expose "
            "Availability geography until denorm config/indexing is expanded."
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Seed pragmatic Geography rows and remap orphaned Property/Availability "
            "geography lookups."
        ),
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
