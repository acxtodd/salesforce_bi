"""
Signal Harvester for Augmented Schema Discovery.

Harvests relevance signals from Ascendix Search configurations (Saved Searches,
ListViews, SearchLayouts) to boost field prioritization in the Planner.

**Feature: graph-aware-zero-config-retrieval**
**Requirements: 24.1-24.6, 25.1-25.5, 26.1-26.5**
**PRD Reference: docs/analysis/AUGMENTED_SCHEMA_DISCOVERY_PRD.md**
"""
import json
import urllib.request
import urllib.parse
import urllib.error
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Set
from collections import defaultdict


# Relevance score weights (from PRD Section 4)
SCORE_FILTER_FIELD = 10      # Fields in saved search filters
SCORE_RESULT_COLUMN = 5      # Fields in result columns
SCORE_SEARCH_LAYOUT = 10     # Fields in SearchLayout
SCORE_LISTVIEW_COLUMN = 8    # Fields in ListView columns
SCORE_SORTABLE_BONUS = 2     # Bonus for sortable fields
SCORE_RELATIONSHIP = 10      # Relationships found in saved searches

# Default primary relationships for CRE objects (2025-12-10)
# These relationships are always marked as primary even if not in saved searches
# to support queries like "deals where Transwestern is involved"
DEFAULT_PRIMARY_RELATIONSHIPS = {
    "ascendix__Deal__c": [
        # Broker fields - critical for "deals where X is involved" queries
        "ascendix__TenantRepBroker__c",
        "ascendix__ListingBrokerCompany__c",
        "ascendix__BuyerRep__c",
        "ascendix__LeadBrokerCompany__c",
        # Party fields
        "ascendix__Client__c",
        "ascendix__Buyer__c",
        "ascendix__Seller__c",
        "ascendix__Tenant__c",
        "ascendix__OwnerLandlord__c",
        # Property relationship
        "ascendix__Property__c",
    ],
    "ascendix__Lease__c": [
        "ascendix__Property__c",
        "ascendix__Tenant__c",
        "ascendix__OwnerLandlord__c",
        "ascendix__TenantRepBroker__c",
        "ascendix__ListingBrokerCompany__c",
    ],
    "ascendix__Availability__c": [
        "ascendix__Property__c",
    ],
    "ascendix__Listing__c": [
        "ascendix__Property__c",
        "ascendix__ListingBrokerCompany__c",
        "ascendix__ListingBrokerContact__c",
        "ascendix__OwnerLandlord__c",
    ],
    "ascendix__Inquiry__c": [
        "ascendix__Property__c",
        "ascendix__Availability__c",
        "ascendix__Listing__c",
        "ascendix__BrokerCompany__c",
    ],
}


@dataclass
class Signal:
    """
    A single relevance signal extracted from a configuration source.

    Attributes:
        field: Field API name (e.g., 'ascendix__City__c')
        score: Relevance score (1-10)
        context: Usage context ('filter', 'result_column', 'sort', 'relationship')
        source: Signal source name (e.g., 'SavedSearch: Class A office')
        value: Optional filter value for vocab seeding
    """
    field: str
    score: int
    context: str
    source: str
    value: Optional[str] = None


@dataclass
class VocabSeed:
    """
    A vocabulary term extracted from filter values.

    Attributes:
        term: The value to seed (e.g., 'Plano')
        field: Field API name it applies to
        source: Source of the seed
    """
    term: str
    field: str
    source: str


@dataclass
class FieldRelevance:
    """
    Aggregated relevance data for a single field.

    Attributes:
        relevance_score: Normalized score (0-10)
        usage_context: Set of contexts ('filter', 'result_column', 'sort')
        source_signals: List of source names for debugging
    """
    relevance_score: float
    usage_context: Set[str] = field(default_factory=set)
    source_signals: List[str] = field(default_factory=list)


@dataclass
class HarvestResult:
    """
    Complete result from signal harvesting.

    Attributes:
        field_scores: Mapping of field name to FieldRelevance
        vocab_seeds: List of vocabulary terms to seed
        primary_relationships: List of relationship fields marked as primary
        object_api_name: The object this harvest is for
    """
    field_scores: Dict[str, FieldRelevance]
    vocab_seeds: List[VocabSeed]
    primary_relationships: List[str]
    object_api_name: str


class TemplateParser:
    """
    Parses Ascendix Search template JSON structures.

    **Requirements: 24.2-24.5**
    """

    def parse_saved_search(
        self,
        template_json: str,
        search_name: str,
        target_object: str
    ) -> List[Signal]:
        """
        Parse a single saved search template and extract signals.

        Args:
            template_json: JSON string from ascendix_search__Template__c
            search_name: Name of the saved search (for source attribution)
            target_object: Object API name this search targets

        Returns:
            List of Signal objects extracted from the template
        """
        signals: List[Signal] = []

        try:
            template = json.loads(template_json) if template_json else {}
        except json.JSONDecodeError as e:
            print(f"Warning: Failed to parse template for '{search_name}': {e}")
            return signals

        source_name = f"SavedSearch: {search_name}"

        # Extract signals from each section
        for section in template.get('sectionsList', []):
            section_object = section.get('objectName', target_object)

            # Skip sections for different objects
            if section_object != target_object:
                continue

            # Parse filter fields (highest priority - Score 10)
            for filter_field in section.get('fieldsList', []):
                logical_name = filter_field.get('logicalName')
                if not logical_name:
                    continue

                # Create signal for filter field
                signals.append(Signal(
                    field=logical_name,
                    score=SCORE_FILTER_FIELD,
                    context='filter',
                    source=source_name,
                    value=filter_field.get('value')  # For vocab seeding
                ))

                # Check for relationship (lookupObject indicates relationship)
                lookup_object = filter_field.get('lookupObject')
                if lookup_object:
                    signals.append(Signal(
                        field=logical_name,
                        score=SCORE_RELATIONSHIP,
                        context='relationship',
                        source=source_name
                    ))

            # Check for relationship path in section
            relationship = section.get('relationship')
            if relationship:
                signals.append(Signal(
                    field=relationship,
                    score=SCORE_RELATIONSHIP,
                    context='relationship',
                    source=source_name
                ))

        # Parse result columns (Medium priority - Score 5)
        for column in template.get('resultColumns', []):
            logical_name = column.get('logicalName')
            if not logical_name:
                continue

            # Base score for result column
            score = SCORE_RESULT_COLUMN

            # Bonus for sortable columns
            if column.get('isSortable'):
                score += SCORE_SORTABLE_BONUS

            signals.append(Signal(
                field=logical_name,
                score=score,
                context='result_column',
                source=source_name
            ))

            # Track if sortable
            if column.get('isSortable'):
                signals.append(Signal(
                    field=logical_name,
                    score=SCORE_SORTABLE_BONUS,
                    context='sort',
                    source=source_name
                ))

        return signals


class ScoreAggregator:
    """
    Aggregates signals from multiple sources into normalized scores.

    **Requirements: 26.1-26.4**
    """

    def aggregate(
        self,
        signals: List[Signal],
        object_api_name: str
    ) -> HarvestResult:
        """
        Aggregate signals from multiple sources into a HarvestResult.

        Args:
            signals: List of Signal objects from all sources
            object_api_name: The object API name

        Returns:
            HarvestResult with normalized scores and vocab seeds
        """
        # Aggregate raw scores per field
        field_data: Dict[str, Dict[str, Any]] = defaultdict(lambda: {
            'raw_score': 0,
            'contexts': set(),
            'sources': []
        })

        vocab_seeds: List[VocabSeed] = []
        primary_relationships: Set[str] = set()

        # Add default primary relationships for this object (2025-12-10)
        # This ensures broker/party relationships are always included even without saved search signals
        default_rels = DEFAULT_PRIMARY_RELATIONSHIPS.get(object_api_name, [])
        primary_relationships.update(default_rels)

        for signal in signals:
            field_data[signal.field]['raw_score'] += signal.score
            field_data[signal.field]['contexts'].add(signal.context)

            # Avoid duplicate sources
            if signal.source not in field_data[signal.field]['sources']:
                field_data[signal.field]['sources'].append(signal.source)

            # Extract vocab seeds from filter values
            if signal.value and signal.context == 'filter':
                # Handle multi-value filters (e.g., "A+;A")
                values = signal.value.split(';') if ';' in signal.value else [signal.value]
                for v in values:
                    v = v.strip()
                    if v and not self._is_id_value(v):
                        vocab_seeds.append(VocabSeed(
                            term=v,
                            field=signal.field,
                            source=signal.source
                        ))

            # Track primary relationships
            if signal.context == 'relationship':
                primary_relationships.add(signal.field)

        # Normalize scores to 0-10 scale
        max_score = max((f['raw_score'] for f in field_data.values()), default=1)

        field_scores: Dict[str, FieldRelevance] = {}
        for field_name, data in field_data.items():
            # Normalize to 0-10, but cap at 10
            normalized_score = min(10.0, (data['raw_score'] / max_score) * 10)

            field_scores[field_name] = FieldRelevance(
                relevance_score=round(normalized_score, 1),
                usage_context=data['contexts'],
                source_signals=data['sources']
            )

        return HarvestResult(
            field_scores=field_scores,
            vocab_seeds=vocab_seeds,
            primary_relationships=list(primary_relationships),
            object_api_name=object_api_name
        )

    def _is_id_value(self, value: str) -> bool:
        """Check if value looks like a Salesforce ID (skip for vocab)."""
        # SF IDs are 15 or 18 chars, alphanumeric
        if len(value) in (15, 18) and value.isalnum():
            # Check if starts with record type prefix patterns
            if value[:3] in ('012', '001', '003', '005', '006'):
                return True
        return False


class SignalHarvester:
    """
    Main harvester that extracts relevance signals from Salesforce configurations.

    **Requirements: 24.1-24.6**

    This class queries Ascendix Search saved searches and extracts:
    - Filter fields (high relevance)
    - Result columns (medium relevance)
    - Relationship paths (graph edge markers)
    - Filter values (vocabulary seeds)
    """

    def __init__(
        self,
        access_token: str,
        instance_url: str,
        api_version: str = 'v59.0'
    ):
        """
        Initialize SignalHarvester.

        Args:
            access_token: Salesforce access token
            instance_url: Salesforce instance URL
            api_version: API version (default: v59.0)
        """
        self.access_token = access_token
        self.instance_url = instance_url
        self.api_version = api_version
        self.template_parser = TemplateParser()
        self.score_aggregator = ScoreAggregator()

    def harvest(self, object_api_name: str) -> HarvestResult:
        """
        Harvest all signals for an object from available sources.

        **Requirements: 24.1, 24.6, 25.1-25.5**

        Sources harvested (in priority order):
        1. Saved Searches (ascendix_search__Search__c) - filter fields, relationships
        2. ListViews - result columns, sort order
        3. SearchLayouts - search result columns

        Args:
            object_api_name: Salesforce object API name

        Returns:
            HarvestResult with aggregated field scores and vocab seeds
        """
        signals: List[Signal] = []

        # Harvest from Saved Searches (primary source - Req 24)
        try:
            saved_search_signals = self._harvest_saved_searches(object_api_name)
            signals.extend(saved_search_signals)
            print(f"Harvested {len(saved_search_signals)} signals from Saved Searches for {object_api_name}")
        except Exception as e:
            # Graceful degradation - continue without saved searches
            print(f"Warning: Failed to harvest saved searches for {object_api_name}: {e}")

        # Harvest from ListViews (Req 25.1-25.3)
        try:
            listview_signals = self._harvest_listviews(object_api_name)
            signals.extend(listview_signals)
            print(f"Harvested {len(listview_signals)} signals from ListViews for {object_api_name}")
        except Exception as e:
            # Graceful degradation - ListViews are supplementary
            print(f"Warning: Failed to harvest listviews for {object_api_name}: {e}")

        # Harvest from SearchLayouts (Req 25.4-25.5)
        try:
            search_layout_signals = self._harvest_search_layouts(object_api_name)
            signals.extend(search_layout_signals)
            print(f"Harvested {len(search_layout_signals)} signals from SearchLayouts for {object_api_name}")
        except Exception as e:
            # Graceful degradation - SearchLayouts are supplementary
            print(f"Warning: Failed to harvest search layouts for {object_api_name}: {e}")

        # Aggregate all signals
        result = self.score_aggregator.aggregate(signals, object_api_name)

        print(f"Signal harvest complete for {object_api_name}: "
              f"{len(result.field_scores)} fields scored, "
              f"{len(result.vocab_seeds)} vocab seeds, "
              f"{len(result.primary_relationships)} primary relationships")

        return result

    def _harvest_saved_searches(self, object_api_name: str) -> List[Signal]:
        """
        Harvest signals from ascendix_search__Search__c saved searches.

        **Requirements: 24.1-24.5**

        Args:
            object_api_name: Object API name to harvest for

        Returns:
            List of Signal objects from saved searches
        """
        signals: List[Signal] = []

        # Query saved searches - note: we don't filter by IsActive since
        # the field may not exist or may have a different name
        query = f"""
            SELECT Id, Name, ascendix_search__Template__c
            FROM ascendix_search__Search__c
            LIMIT 100
        """

        try:
            records = self._execute_soql(query)
        except Exception as e:
            # Package may not be installed
            if 'INVALID_TYPE' in str(e) or "doesn't exist" in str(e):
                print(f"Ascendix Search package not installed - skipping saved search harvest")
                return signals
            raise

        for record in records:
            template_json = record.get('ascendix_search__Template__c')
            search_name = record.get('Name', 'Unknown')

            if not template_json:
                continue

            # Parse template to find target object
            try:
                template = json.loads(template_json)
                # Check if this search targets our object
                sections = template.get('sectionsList', [])
                target_objects = {s.get('objectName') for s in sections if s.get('objectName')}

                if object_api_name not in target_objects:
                    continue

                # Parse and extract signals
                search_signals = self.template_parser.parse_saved_search(
                    template_json,
                    search_name,
                    object_api_name
                )
                signals.extend(search_signals)

            except json.JSONDecodeError:
                print(f"Warning: Invalid JSON in saved search '{search_name}'")
                continue

        return signals

    def _execute_soql(self, query: str) -> List[Dict[str, Any]]:
        """
        Execute SOQL query against Salesforce.

        Args:
            query: SOQL query string

        Returns:
            List of record dictionaries
        """
        encoded_query = urllib.parse.quote(query.strip())
        url = f"{self.instance_url}/services/data/{self.api_version}/query?q={encoded_query}"

        headers = {
            'Authorization': f'Bearer {self.access_token}',
            'Content-Type': 'application/json'
        }

        req = urllib.request.Request(url, headers=headers)

        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                result = json.loads(response.read().decode('utf-8'))
                return result.get('records', [])
        except urllib.error.HTTPError as e:
            error_body = e.read().decode('utf-8') if e.fp else ''
            raise Exception(f"SOQL query failed (HTTP {e.code}): {error_body}")

    def _harvest_listviews(self, object_api_name: str) -> List[Signal]:
        """
        Harvest signals from standard Salesforce ListViews.

        **Requirements: 25.1-25.3**

        Args:
            object_api_name: Object API name

        Returns:
            List of Signal objects from ListViews
        """
        signals: List[Signal] = []

        # Get list of ListViews for this object
        url = f"{self.instance_url}/services/data/{self.api_version}/sobjects/{object_api_name}/listviews"

        headers = {
            'Authorization': f'Bearer {self.access_token}',
            'Content-Type': 'application/json'
        }

        req = urllib.request.Request(url, headers=headers)

        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                result = json.loads(response.read().decode('utf-8'))
                listviews = result.get('listviews', [])
        except urllib.error.HTTPError as e:
            print(f"Warning: Could not fetch listviews for {object_api_name}: HTTP {e.code}")
            return signals

        # Get details for each ListView (limit to first 5 to avoid rate limits)
        for lv in listviews[:5]:
            lv_id = lv.get('id')
            lv_name = lv.get('label', 'Unknown')

            if not lv_id:
                continue

            try:
                describe_url = f"{self.instance_url}/services/data/{self.api_version}/sobjects/{object_api_name}/listviews/{lv_id}/describe"
                req = urllib.request.Request(describe_url, headers=headers)

                with urllib.request.urlopen(req, timeout=30) as response:
                    describe = json.loads(response.read().decode('utf-8'))

                source_name = f"ListView: {lv_name}"

                # Extract column signals
                for col in describe.get('columns', []):
                    field_name = col.get('fieldNameOrPath')
                    if not field_name:
                        continue

                    score = SCORE_LISTVIEW_COLUMN
                    if col.get('sortable'):
                        score += SCORE_SORTABLE_BONUS

                    signals.append(Signal(
                        field=field_name,
                        score=score,
                        context='result_column',
                        source=source_name
                    ))

                    # Check for cross-object paths (indicates relationship)
                    if '__r.' in field_name or '.' in field_name:
                        signals.append(Signal(
                            field=field_name.split('.')[0],
                            score=SCORE_RELATIONSHIP,
                            context='relationship',
                            source=source_name
                        ))

            except Exception as e:
                print(f"Warning: Could not describe ListView '{lv_name}': {e}")
                continue

        return signals

    def _harvest_search_layouts(self, object_api_name: str) -> List[Signal]:
        """
        Harvest signals from Salesforce SearchLayouts.

        **Requirements: 25.4-25.5**

        Args:
            object_api_name: Object API name

        Returns:
            List of Signal objects from SearchLayouts
        """
        signals: List[Signal] = []

        url = f"{self.instance_url}/services/data/{self.api_version}/search/layout?q={object_api_name}"

        headers = {
            'Authorization': f'Bearer {self.access_token}',
            'Content-Type': 'application/json'
        }

        req = urllib.request.Request(url, headers=headers)

        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                result = json.loads(response.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            print(f"Warning: Could not fetch search layout for {object_api_name}: HTTP {e.code}")
            return signals

        # Result is a list of layouts
        for layout in result if isinstance(result, list) else [result]:
            if layout.get('objectType') != object_api_name:
                continue

            source_name = 'SearchLayout'

            for col in layout.get('searchColumns', []):
                field_name = col.get('name')
                if not field_name:
                    continue

                signals.append(Signal(
                    field=field_name,
                    score=SCORE_SEARCH_LAYOUT,
                    context='search_column',
                    source=source_name
                ))

        return signals
