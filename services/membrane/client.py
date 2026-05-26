import os
import json
import requests
from typing import List, Dict, Any, Optional, Iterator

class MembraneClient:
    def __init__(self, api_key: Optional[str] = None, base_url: str = "https://membrane-api.com"):
        self.api_key = api_key or os.environ.get("MEMBRANE_API_KEY", "")
        self.base_url = base_url.rstrip("/")
        
    def _headers(self) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json"
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def chat_completion(
        self,
        messages: List[Dict[str, Any]],
        model: str = "membrane-engagement-layer",
        temperature: float = 0.0,
        response_format: Optional[Dict[str, Any]] = None,
        stream: bool = False,
        extra_body: Optional[Dict[str, Any]] = None
    ) -> Any:
        """
        Calls the Membrane API chat completions endpoint.
        Leverages hosted capabilities such as semantic caching, bouncer/guard checks, and cost telemetry.
        """
        url = f"{self.base_url}/v1/chat/completions"
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "stream": stream
        }
        if response_format:
            payload["response_format"] = response_format
        if extra_body:
            payload.update(extra_body)

        try:
            if stream:
                # Returns a generator for SSE streaming
                response = requests.post(url, headers=self._headers(), json=payload, stream=True, timeout=120)
                response.raise_for_status()
                return self._stream_generator(response)
            else:
                response = requests.post(url, headers=self._headers(), json=payload, timeout=120)
                response.raise_for_status()
                return response.json()
        except requests.exceptions.RequestException as e:
            # Return technical error detail in structured format if possible
            error_msg = f"Membrane Connection Error: {str(e)}"
            if response_format:
                return {
                    "choices": [{
                        "message": {
                            "content": json.dumps({"narrative": f"TECHNICAL ERROR: {error_msg}", "citations": [], "actions": []})
                        }
                    }]
                }
            else:
                return {
                    "choices": [{
                        "message": {
                            "content": f"Error contacting Membrane API: {error_msg}"
                        }
                    }]
                }

    def _stream_generator(self, response: requests.Response) -> Iterator[str]:
        """Generator that yields clean SSE text chunks."""
        for line in response.iter_lines():
            if line:
                decoded_line = line.decode("utf-8")
                yield decoded_line

    def swarm_map(
        self,
        chunks: List[str],
        system_prompt: str,
        extraction_criteria: Optional[Dict[str, Any]] = None,
        model: str = "membrane-engagement-layer",
        temperature: float = 0.0,
        max_concurrency: int = 10
    ) -> Dict[str, Any]:
        """
        Calls the Membrane parallel Map-Reduce Swarm endpoint for document extractions.
        Splits processing concurrently at the API level (avoiding local rate limit throttling).
        """
        url = f"{self.base_url}/v1/swarm/map"
        payload = {
            "model": model,
            "chunks": chunks,
            "system_prompt": system_prompt,
            "temperature": temperature,
            "max_concurrency": max_concurrency
        }
        if extraction_criteria:
            payload["extraction_criteria"] = extraction_criteria

        try:
            response = requests.post(url, headers=self._headers(), json=payload, timeout=240)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"Membrane Swarm API Call Failed: {e}")
            # Mock fallback response in the format expected by Scrapers to prevent process crash
            return {
                "object": "swarm.extraction_matrix",
                "model": model,
                "task_id": "failed_call",
                "is_truncated": False,
                "extractions": [],
                "membrane_metadata": {
                    "status": "FAILED",
                    "total_raw_extractions_captured": 0,
                    "warning_msg": str(e),
                    "value_ledger": {
                        "actual_cost_incurred": 0.0,
                        "gross_unoptimized_cost": 0.0,
                        "net_enterprise_savings": 0.0
                    }
                }
            }
