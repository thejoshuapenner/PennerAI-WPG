import sys
import os
import unittest
from unittest.mock import patch, MagicMock

# Ensure services directory is in import path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from services.membrane import MembraneClient

class TestMembraneClientUpdates(unittest.TestCase):
    def setUp(self):
        self.client = MembraneClient(api_key="test_api_key", base_url="https://mock-membrane-api.com")

    @patch("requests.post")
    def test_headers_and_preserve_context(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"choices": [{"message": {"content": "Hello world"}}]}
        mock_post.return_value = mock_response

        # Test simple chat completion (default headers)
        self.client.chat_completion(messages=[{"role": "user", "content": "hi"}])
        mock_post.assert_called_once()
        headers = mock_post.call_args[1]["headers"]
        self.assertEqual(headers["Authorization"], "Bearer test_api_key")
        self.assertNotIn("X-Membrane-Preserve-Context", headers)

        mock_post.reset_mock()

        # Test with preserve_context=True
        self.client.chat_completion(messages=[{"role": "user", "content": "hi"}], preserve_context=True)
        mock_post.assert_called_once()
        headers = mock_post.call_args[1]["headers"]
        self.assertEqual(headers["X-Membrane-Preserve-Context"], "true")

    @patch("requests.post")
    def test_swarm_plan(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"trajectory": {"estimated_retail_cost": 0.05}}
        mock_post.return_value = mock_response

        result = self.client.swarm_plan(
            chunks=["chunk1", "chunk2"],
            max_concurrency=5,
            extraction_criteria={"system_persona": "Tester", "target_signals": ["test"]},
            invariant_set_id="test_lock"
        )
        mock_post.assert_called_once()
        url = mock_post.call_args[0][0]
        self.assertEqual(url, "https://mock-membrane-api.com/v1/swarm/plan")
        payload = mock_post.call_args[1]["json"]
        self.assertEqual(payload["chunks"], ["chunk1", "chunk2"])
        self.assertEqual(payload["max_concurrency"], 5)
        self.assertEqual(payload["invariant_set_id"], "test_lock")
        self.assertEqual(result["trajectory"]["estimated_retail_cost"], 0.05)

    @patch("requests.post")
    def test_swarm_state(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "SUCCESS", "signature": "MEMBRANE_VERIFIED_MOCK"}
        mock_post.return_value = mock_response

        result = self.client.swarm_state(
            task_type="python_code",
            payload="print('hello')",
            agent_id="test_agent",
            destination_path="test_script.py"
        )
        mock_post.assert_called_once()
        url = mock_post.call_args[0][0]
        self.assertEqual(url, "https://mock-membrane-api.com/v1/swarm/state")
        body = mock_post.call_args[1]["json"]
        self.assertEqual(body["task_type"], "python_code")
        self.assertEqual(body["payload"], "print('hello')")
        self.assertEqual(body["agent_id"], "test_agent")
        self.assertEqual(body["destination_path"], "test_script.py")
        self.assertEqual(result["status"], "SUCCESS")

    @patch("requests.post")
    def test_swarm_map_strict_rules_pass(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"extractions": []}
        mock_post.return_value = mock_response

        # Payload passes strict rules, should execute with swarm_mode "canary"
        self.client.swarm_map(
            chunks=["chunk1", "chunk2"],
            system_prompt="Extract test info",
            extraction_criteria={"system_persona": "Persona", "target_signals": ["sig1"]},
            swarm_mode="canary"
        )
        mock_post.assert_called_once()
        headers = mock_post.call_args[1]["headers"]
        self.assertEqual(headers.get("X-Membrane-Swarm-Mode"), "canary")

    @patch("requests.post")
    def test_swarm_map_strict_rules_fallback(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"extractions": []}
        mock_post.return_value = mock_response

        # 1. Too many chunks (>25)
        self.client.swarm_map(
            chunks=["chunk"] * 30,
            system_prompt="Extract info",
            extraction_criteria={"system_persona": "Persona", "target_signals": ["sig1"]},
            swarm_mode="canary"
        )
        headers = mock_post.call_args[1]["headers"]
        self.assertEqual(headers.get("X-Membrane-Swarm-Mode"), "legacy")

        mock_post.reset_mock()

        # 2. Too large chunk (>25000 chars)
        self.client.swarm_map(
            chunks=["a" * 30000],
            system_prompt="Extract info",
            extraction_criteria={"system_persona": "Persona", "target_signals": ["sig1"]},
            swarm_mode="canary"
        )
        headers = mock_post.call_args[1]["headers"]
        self.assertEqual(headers.get("X-Membrane-Swarm-Mode"), "legacy")

        mock_post.reset_mock()

        # 3. Invalid extraction criteria structure (missing target_signals/system_persona)
        self.client.swarm_map(
            chunks=["chunk1"],
            system_prompt="Extract info",
            extraction_criteria={"type": "json_object"}, # Doesn't have system_persona/target_signals
            swarm_mode="canary"
        )
        headers = mock_post.call_args[1]["headers"]
        self.assertEqual(headers.get("X-Membrane-Swarm-Mode"), "legacy")

if __name__ == "__main__":
    unittest.main()
