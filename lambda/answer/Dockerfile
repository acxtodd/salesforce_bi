FROM --platform=linux/arm64 public.ecr.aws/docker/library/python:3.11-slim

# Copy Lambda Web Adapter (multi-arch image auto-selects arm64 for Lambda)
COPY --from=public.ecr.aws/awsguru/aws-lambda-adapter:0.8.4 /lambda-adapter /opt/extensions/lambda-adapter

# Install dependencies
COPY requirements.txt .
RUN pip install -r requirements.txt

# Copy function code
COPY index.py .
COPY main.py .

# Set the CMD to your handler
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
