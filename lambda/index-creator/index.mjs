import { SignatureV4 } from '@aws-sdk/signature-v4';
import { defaultProvider } from '@aws-sdk/credential-provider-node';
import { HttpRequest } from '@aws-sdk/protocol-http';
import https from 'https';
import crypto from 'crypto';

class Sha256 {
    constructor(secret) {
        this.hash = crypto.createHash('sha256');
        if (secret) {
            this.hash = crypto.createHmac('sha256', secret);
        }
    }

    update(data, encoding) {
        this.hash.update(data, encoding);
    }

    digest() {
        return Promise.resolve(this.hash.digest());
    }
}

export const handler = async (event) => {
    console.log('Event:', JSON.stringify(event, null, 2));

    const requestType = event.RequestType;
    if (requestType === 'Delete') {
        // Optionally delete the index, but for now we skip to preserve data
        return { PhysicalResourceId: event.PhysicalResourceId };
    }

    const endpoint = event.ResourceProperties.endpoint; // e.g. https://...
    const indexName = event.ResourceProperties.indexName;
    const region = process.env.AWS_REGION;

    // Remove protocol if present
    const domain = endpoint.replace(/^https?:\/\//, '');
    const url = `https://${domain}/${indexName}`;

    const indexBody = {
        settings: {
            "index.knn": true
        },
        mappings: {
            properties: {
                "embedding": {
                    "type": "knn_vector",
                    "dimension": 1024, // Titan Embed Text v2
                    "method": {
                        "name": "hnsw",
                        "engine": "faiss",
                        "parameters": {
                            "m": 16,
                            "ef_construction": 512
                        },
                        "space_type": "l2"
                    }
                },
                "text": { "type": "text" },
                "metadata": { "type": "text" }
            }
        }
    };

    try {
        // Check if index exists first
        const exists = await sendRequest('HEAD', url, null, region, domain);
        if (exists.statusCode === 200) {
            console.log(`Index ${indexName} already exists.`);
            return { PhysicalResourceId: indexName };
        }

        // Create index
        console.log(`Creating index ${indexName}...`);
        const response = await sendRequest('PUT', url, JSON.stringify(indexBody), region, domain);

        if (response.statusCode >= 200 && response.statusCode < 300) {
            console.log(`Index ${indexName} created. Verifying availability...`);
            
            // CRITICAL: Wait for index to be fully available before returning success
            // OpenSearch Serverless needs time to propagate the index
            await waitForIndexAvailable(url, region, domain, indexName, 30);
            
            console.log(`Index ${indexName} verified and ready.`);
            return { PhysicalResourceId: indexName };
        } else {
            throw new Error(`Failed to create index: ${response.statusCode} ${response.body}`);
        }
    } catch (error) {
        console.error('Error:', error);
        throw error;
    }
};

async function waitForIndexAvailable(url, region, domain, indexName, maxAttempts) {
    console.log(`Waiting for index ${indexName} to be available...`);
    
    for (let attempt = 1; attempt <= maxAttempts; attempt++) {
        try {
            const response = await sendRequest('GET', url, null, region, domain);
            
            if (response.statusCode === 200) {
                console.log(`Index ${indexName} is available (attempt ${attempt}/${maxAttempts})`);
                return true;
            }
            
            console.log(`Index not yet available (attempt ${attempt}/${maxAttempts}), waiting 2 seconds...`);
            await new Promise(resolve => setTimeout(resolve, 2000));
        } catch (error) {
            console.log(`Error checking index availability (attempt ${attempt}/${maxAttempts}): ${error.message}`);
            if (attempt === maxAttempts) {
                throw new Error(`Index ${indexName} not available after ${maxAttempts} attempts`);
            }
            await new Promise(resolve => setTimeout(resolve, 2000));
        }
    }
    
    throw new Error(`Index ${indexName} not available after ${maxAttempts} attempts`);
}

async function sendRequest(method, url, body, region, domain) {
    const signer = new SignatureV4({
        credentials: defaultProvider(),
        region: region,
        service: 'aoss',
        sha256: Sha256,
    });

    const request = new HttpRequest({
        method: method,
        hostname: domain,
        path: new URL(url).pathname,
        headers: {
            'Content-Type': 'application/json',
            'host': domain,
        },
        body: body,
    });

    const signedRequest = await signer.sign(request);

    return new Promise((resolve, reject) => {
        const req = https.request({
            ...signedRequest,
            host: domain,
            path: signedRequest.path,
            method: method,
        }, (res) => {
            let data = '';
            res.on('data', (chunk) => data += chunk);
            res.on('end', () => {
                resolve({
                    statusCode: res.statusCode,
                    body: data
                });
            });
        });

        req.on('error', reject);
        if (body) {
            req.write(body);
        }
        req.end();
    });
}
