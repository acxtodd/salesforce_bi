# Field Mapping Strategy: From Hardcoded to Dynamic Configuration

## The Problem You Identified

You're absolutely right - we hardcoded field mappings for objects whose structure we don't know yet. When connecting to a real Salesforce instance, we need a way to dynamically configure which fields to index for custom objects.

## The Solution: Three-Phase Approach

### Phase 1: POC (Current Implementation) - Hardcoded Mappings

**What we just built:**
```python
POC_OBJECT_FIELDS = {
    "Property__c": {
        "text_fields": ["Name", "Address__c", "City__c", "State__c"],
        "long_text_fields": ["Description__c", "Amenities__c"],
        "relationship_fields": ["Account__c", "Property_Manager__c"],
        "display_name": "Name"
    }
}
```

**Purpose**: Prove the concept works with known objects
**Limitation**: Can't handle arbitrary custom objects without code changes

---

### Phase 2: Configuration File (Quick Win)

**For connecting to a real instance soon**, add a simple configuration approach:

#### Option A: Environment Variables
```python
# In Lambda environment variables
CUSTOM_OBJECT_CONFIG = json.loads(os.environ.get('CUSTOM_OBJECT_CONFIG', '{}'))

# Merge with POC defaults
OBJECT_FIELDS = {**POC_OBJECT_FIELDS, **CUSTOM_OBJECT_CONFIG}
```

Deploy with:
```bash
export CUSTOM_OBJECT_CONFIG='{"CustomObject__c": {"text_fields": ["Name", "Field1__c"], ...}}'
```

#### Option B: S3 Configuration File
```python
# Load from S3 on Lambda cold start
def load_config_from_s3():
    s3 = boto3.client('s3')
    config = s3.get_object(
        Bucket=os.environ['CONFIG_BUCKET'],
        Key='object-field-mappings.json'
    )
    return json.loads(config['Body'].read())

OBJECT_FIELDS = load_config_from_s3()
```

**Benefits**:
- No code changes needed to add objects
- Can update configuration without redeployment
- Simple JSON format

**Limitations**:
- Manual configuration required
- No UI for admins
- No validation

---

### Phase 3: Salesforce Custom Metadata Type (Production)

**The proper solution** outlined in the design document:

#### 1. Create Custom Metadata Type in Salesforce

```apex
// IndexConfiguration__mdt
Object API Name: IndexConfiguration
Label: Index Configuration

Fields:
- ObjectApiName__c (Text 80): "Property__c"
- Enabled__c (Checkbox): true
- TextFields__c (Long Text Area): "Name, Address__c, City__c, State__c"
- LongTextFields__c (Long Text Area): "Description__c, Amenities__c"
- RichTextFields__c (Long Text Area): "Marketing_Content__c"
- RelationshipFields__c (Text Area): "Account__c, Property_Manager__c"
- ChunkingStrategy__c (Picklist): "Combined" or "ByField"
- MaxChunkTokens__c (Number): 500
- IncludeInSearch__c (Checkbox): true
- DisplayNameField__c (Text 80): "Name"
- PreviewFields__c (Text Area): "Name, Address__c, City__c"
```

#### 2. Admin UI in Salesforce

Admins can configure objects through:
- Setup → Custom Metadata Types → Index Configuration → Manage Records
- Or build a Lightning Web Component for easier configuration

#### 3. Lambda Queries Configuration at Runtime

```python
import requests

def get_object_configuration(sobject: str, sf_session) -> Dict:
    """
    Query Salesforce for object configuration.
    Cached for 24 hours to reduce API calls.
    """
    # Check cache first
    cache_key = f"config:{sobject}"
    cached = get_from_cache(cache_key)
    if cached:
        return cached
    
    # Query Custom Metadata Type
    query = f"""
        SELECT ObjectApiName__c, TextFields__c, LongTextFields__c,
               RichTextFields__c, RelationshipFields__c, ChunkingStrategy__c,
               MaxChunkTokens__c, DisplayNameField__c
        FROM IndexConfiguration__mdt
        WHERE ObjectApiName__c = '{sobject}' AND Enabled__c = true
    """
    
    response = sf_session.query(query)
    
    if response['totalSize'] == 0:
        # Fall back to POC defaults or skip
        return POC_OBJECT_FIELDS.get(sobject)
    
    config = response['records'][0]
    
    # Parse comma-separated fields
    field_config = {
        "text_fields": [f.strip() for f in config['TextFields__c'].split(',')],
        "long_text_fields": [f.strip() for f in config['LongTextFields__c'].split(',')],
        "relationship_fields": [f.strip() for f in config['RelationshipFields__c'].split(',')],
        "display_name": config['DisplayNameField__c'],
        "chunking_strategy": config['ChunkingStrategy__c'],
        "max_tokens": config['MaxChunkTokens__c']
    }
    
    # Cache for 24 hours
    set_cache(cache_key, field_config, ttl=86400)
    
    return field_config
```

#### 4. Updated Chunking Lambda

```python
def chunk_record(record: Dict[str, Any], sobject: str, sf_session) -> List[Dict[str, Any]]:
    """
    Chunk a Salesforce record using dynamic configuration.
    """
    # Get configuration (from cache or Salesforce)
    config = get_object_configuration(sobject, sf_session)
    
    if not config:
        print(f"No configuration found for {sobject}, skipping")
        return []
    
    # Extract text using configured fields
    full_text = extract_text_from_record(record, config)
    
    # Apply configured chunking strategy
    if config['chunking_strategy'] == 'ByField':
        chunks = chunk_by_field(record, config)
    else:
        chunks = chunk_combined(full_text, config)
    
    return chunks
```

---

## Migration Path: How to Connect to Real Instance

### Step 1: Use POC Hardcoded Mappings (Now)
- Works for the 7 POC objects
- Proves the pipeline works end-to-end

### Step 2: Add S3 Configuration (Next Sprint)
When you connect to a real instance:

1. **Discover the custom objects**:
```bash
# Query Salesforce for custom objects
sf data query -q "SELECT QualifiedApiName FROM EntityDefinition WHERE IsCustomizable = true"
```

2. **Describe each object to get fields**:
```bash
sf sobject describe -s Property__c --json
```

3. **Create configuration file**:
```json
{
  "Property__c": {
    "text_fields": ["Name", "Address__c", "City__c"],
    "long_text_fields": ["Description__c"],
    "relationship_fields": ["Account__c"],
    "display_name": "Name"
  },
  "Lease__c": {
    "text_fields": ["Name", "Status__c"],
    "long_text_fields": ["Terms__c"],
    "relationship_fields": ["Property__c", "Account__c"],
    "display_name": "Name"
  }
}
```

4. **Upload to S3**:
```bash
aws s3 cp object-config.json s3://your-data-bucket/config/object-field-mappings.json
```

5. **Update Lambda to load from S3** (modify `lambda/chunking/index.py`):
```python
import boto3
import json

s3 = boto3.client('s3')

def load_object_config():
    try:
        response = s3.get_object(
            Bucket=os.environ['DATA_BUCKET'],
            Key='config/object-field-mappings.json'
        )
        custom_config = json.loads(response['Body'].read())
        # Merge with POC defaults
        return {**POC_OBJECT_FIELDS, **custom_config}
    except:
        # Fall back to POC defaults
        return POC_OBJECT_FIELDS

# Load once on cold start
OBJECT_FIELDS = load_object_config()
```

### Step 3: Implement Custom Metadata Type (Phase 3)
For production deployment:
1. Deploy `IndexConfiguration__mdt` to Salesforce
2. Build admin UI for configuration
3. Update Lambda to query Salesforce for configuration
4. Add caching layer (DynamoDB or Lambda memory)

---

## Recommended Approach for Your Next Steps

**For connecting to a real instance soon**, I recommend:

### Quick Win: S3 Configuration (1-2 days)
1. Create a script to discover objects and fields from Salesforce
2. Generate configuration JSON
3. Upload to S3
4. Modify chunking Lambda to load from S3
5. Redeploy Lambda

### Code Changes Needed:
```python
# lambda/chunking/index.py - Add at top
import boto3
import os

s3_client = boto3.client('s3')
CONFIG_BUCKET = os.environ.get('DATA_BUCKET')
CONFIG_KEY = 'config/object-field-mappings.json'

def load_object_config():
    """Load object configuration from S3, fall back to POC defaults."""
    try:
        response = s3_client.get_object(Bucket=CONFIG_BUCKET, Key=CONFIG_KEY)
        custom_config = json.loads(response['Body'].read())
        print(f"Loaded configuration for {len(custom_config)} objects from S3")
        return {**POC_OBJECT_FIELDS, **custom_config}
    except Exception as e:
        print(f"Failed to load S3 config, using POC defaults: {e}")
        return POC_OBJECT_FIELDS

# Load on cold start
OBJECT_FIELDS = load_object_config()

# Rest of code stays the same, but use OBJECT_FIELDS instead of POC_OBJECT_FIELDS
```

### Discovery Script:
```python
# scripts/discover_salesforce_objects.py
import json
from simple_salesforce import Salesforce

sf = Salesforce(username='...', password='...', security_token='...')

# Query custom objects
objects = sf.query("""
    SELECT QualifiedApiName, Label 
    FROM EntityDefinition 
    WHERE IsCustomizable = true AND IsCustomSetting = false
""")

config = {}

for obj in objects['records']:
    api_name = obj['QualifiedApiName']
    
    # Describe object to get fields
    describe = sf.__getattr__(api_name).describe()
    
    text_fields = []
    long_text_fields = []
    relationship_fields = []
    display_name = 'Name'
    
    for field in describe['fields']:
        if not field['updateable']:
            continue
            
        if field['type'] in ['string', 'email', 'phone', 'url']:
            text_fields.append(field['name'])
        elif field['type'] == 'textarea':
            long_text_fields.append(field['name'])
        elif field['type'] in ['reference', 'lookup']:
            relationship_fields.append(field['name'])
        
        if field['nameField']:
            display_name = field['name']
    
    config[api_name] = {
        "text_fields": text_fields[:10],  # Limit to avoid too many fields
        "long_text_fields": long_text_fields,
        "relationship_fields": relationship_fields,
        "display_name": display_name
    }

# Save to file
with open('object-field-mappings.json', 'w') as f:
    json.dump(config, f, indent=2)

print(f"Generated configuration for {len(config)} objects")
```

---

## Summary

**Current State**: Hardcoded for POC ✅  
**Next Step**: S3 configuration file (recommended for real instance)  
**Future**: Salesforce Custom Metadata Type (production-ready)

The S3 approach gives you flexibility without the complexity of Custom Metadata Type, and you can migrate to Phase 3 later when you need admin-friendly configuration.

Want me to implement the S3 configuration approach now?
