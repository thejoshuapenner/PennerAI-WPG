import os
import json
import requests
from typing import List, Dict, Any, Optional, Iterator

class MembraneClient:
    def __init__(self, api_key: Optional[str] = None, base_url: str = "https://membrane-api.com"):
        self.api_key = api_key or os.environ.get("MEMBRANE_API_KEY", "")
        self.base_url = base_url.rstrip("/")
        
    def _headers(self, extra_headers: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json"
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        if extra_headers:
            headers.update(extra_headers)
        return headers

    def chat_completion(
        self,
        messages: List[Dict[str, Any]],
        model: str = "membrane-engagement-layer",
        temperature: float = 0.0,
        response_format: Optional[Dict[str, Any]] = None,
        stream: bool = False,
        preserve_context: bool = False,
        extra_body: Optional[Dict[str, Any]] = None,
        extra_headers: Optional[Dict[str, str]] = None
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

        req_headers = {}
        if extra_headers:
            req_headers.update(extra_headers)
        if preserve_context:
            req_headers["X-Membrane-Preserve-Context"] = "true"

        try:
            if stream:
                # Returns a generator for SSE streaming
                response = requests.post(url, headers=self._headers(req_headers), json=payload, stream=True, timeout=120)
                response.raise_for_status()
                return self._stream_generator(response)
            else:
                response = requests.post(url, headers=self._headers(req_headers), json=payload, timeout=120)
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
        max_concurrency: int = 10,
        swarm_mode: Optional[str] = None
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

        resolved_mode = swarm_mode or os.environ.get("MEMBRANE_SWARM_MODE", "canary")
        
        # Check strict gate rules if mode is early_gate or canary
        if resolved_mode in ["early_gate", "canary"]:
            is_valid = True
            reasons = []
            if not (1 <= len(chunks) <= 25):
                is_valid = False
                reasons.append(f"chunks count ({len(chunks)}) must be between 1 and 25")
            
            total_chars = sum(len(c) for c in chunks)
            if total_chars > 200000:
                is_valid = False
                reasons.append(f"total character count ({total_chars}) exceeds 200,000 ceiling")
                
            if any(len(c) > 25000 for c in chunks):
                is_valid = False
                reasons.append("one or more chunks exceed 25,000 character limit")
                
            if not isinstance(extraction_criteria, dict):
                is_valid = False
                reasons.append("extraction_criteria must be a dictionary")
            else:
                if "system_persona" not in extraction_criteria or "target_signals" not in extraction_criteria:
                    is_valid = False
                    reasons.append("extraction_criteria must contain 'system_persona' and 'target_signals'")
                    
            if not is_valid:
                print(f"⚠️ Swarm payload violates strict rules for '{resolved_mode}' mode (Reasons: {', '.join(reasons)}). Falling back to 'legacy' mode.")
                resolved_mode = "legacy"

        req_headers = {}
        if resolved_mode:
            req_headers["X-Membrane-Swarm-Mode"] = resolved_mode

        try:
            response = requests.post(url, headers=self._headers(req_headers), json=payload, timeout=240)
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

    def swarm_plan(
        self,
        chunks: List[str],
        max_concurrency: int = 20,
        extraction_criteria: Optional[Dict[str, Any]] = None,
        invariant_set_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Calls the Membrane Predictive Swarm Plan endpoint.
        Generates estimated cost, concurrency recommendations, latency forecasts, and risk scores.
        """
        url = f"{self.base_url}/v1/swarm/plan"
        payload = {
            "chunks": chunks,
            "max_concurrency": max_concurrency
        }
        if extraction_criteria:
            payload["extraction_criteria"] = extraction_criteria
        if invariant_set_id:
            payload["invariant_set_id"] = invariant_set_id

        try:
            response = requests.post(url, headers=self._headers(), json=payload, timeout=120)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"Membrane Swarm Plan Call Failed: {e}")
            return {
                "object": "swarm.plan_failed",
                "warning_msg": str(e),
                "trajectory": {
                    "estimated_retail_cost": 0.0,
                    "estimated_execution_latency_sec": 0.0,
                    "recommended_concurrency": 1,
                    "aggregate_risk_score": 10.0
                }
            }

    def swarm_state(
        self,
        task_type: str,
        payload: str,
        agent_id: Optional[str] = None,
        target_agent_id: Optional[str] = None,
        destination_path: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Validates model-generated Python code or React components inside a compile-time isolated sandbox.
        """
        url = f"{self.base_url}/v1/swarm/state"
        body = {
            "task_type": task_type,
            "payload": payload
        }
        if agent_id:
            body["agent_id"] = agent_id
        if target_agent_id:
            body["target_agent_id"] = target_agent_id
        if destination_path:
            body["destination_path"] = destination_path

        try:
            response = requests.post(url, headers=self._headers(), json=body, timeout=120)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"Membrane Swarm State Call Failed: {e}")
            return {
                "status": "FAILED",
                "error": str(e),
                "compiled": False
            }

