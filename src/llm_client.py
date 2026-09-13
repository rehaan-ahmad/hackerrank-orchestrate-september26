"""
LLM Client Module for Buy or Wait?
Anthropic SDK wrapper with caching, token usage tracking, and batching.
"""

class LLMClient:
    """Anthropic Claude API client wrapper."""
    def __init__(self, api_key: str):
        self.api_key = api_key

    def write_usage_report(self, output_path: str):
        pass
