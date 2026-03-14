import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__)))

try:
    import aws_lambda_powertools.utilities.streaming
    print("Imported aws_lambda_powertools.utilities.streaming")
    print(dir(aws_lambda_powertools.utilities.streaming))
except ImportError as e:
    print(f"ImportError: {e}")

try:
    from aws_lambda_powertools.utilities.streaming import ResponseStream
    print("Found ResponseStream")
except ImportError:
    print("ResponseStream NOT found")
