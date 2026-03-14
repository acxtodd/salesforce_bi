import boto3
import requests
from requests_aws4auth import AWS4Auth
import os

host = 'https://1zmrlod7vi7veq9r5v56.us-west-2.aoss.amazonaws.com'
region = 'us-west-2'
service = 'aoss'
credentials = boto3.Session().get_credentials()
awsauth = AWS4Auth(credentials.access_key, credentials.secret_key, region, service, session_token=credentials.token)

# List indices
path = '/_cat/indices?v'
url = host + path

print(f"Querying {url}")
response = requests.get(url, auth=awsauth)
print(f"Status: {response.status_code}")
print("Response:")
print(response.text)