import requests
import json
import time

BASE_URL = "http://localhost:8002"
DEV_KEY = "sk-penner-dev-2026"
INVALID_KEY = "sk-invalid-key"

def test_api_key_verification():
    print("\n--- Test 1: API Key Verification ---")
    
    # 1. No key
    try:
        r = requests.post(f"{BASE_URL}/api/v1/search", json={"query": "test"})
        print(f"No key status: {r.status_code} (expected 401)")
    except Exception as e:
        print(f"No key error: {e}")
        
    # 2. Invalid key
    headers_invalid = {"Authorization": f"Bearer {INVALID_KEY}"}
    try:
        r = requests.post(f"{BASE_URL}/api/v1/search", json={"query": "test"}, headers=headers_invalid)
        print(f"Invalid key status: {r.status_code} (expected 401)")
    except Exception as e:
        print(f"Invalid key error: {e}")
        
    # 3. Valid key
    headers_valid = {"Authorization": f"Bearer {DEV_KEY}"}
    try:
        r = requests.post(f"{BASE_URL}/api/v1/search", json={"query": "Bellevue", "limit": 2}, headers=headers_valid)
        print(f"Valid key status: {r.status_code} (expected 200)")
        if r.status_code == 200:
            print(f"Search results keys: {list(r.json().keys())}")
    except Exception as e:
        print(f"Valid key error: {e}")

def test_tools_discovery():
    print("\n--- Test 2: Tools Discovery ---")
    headers = {"Authorization": f"Bearer {DEV_KEY}"}
    try:
        r = requests.post(f"{BASE_URL}/api/v1/tools", headers=headers)
        print(f"Tools status: {r.status_code} (expected 200)")
        if r.status_code == 200:
            tools = r.json().get("tools", [])
            print(f"Discovered {len(tools)} tools:")
            for t in tools:
                print(f" - {t['name']}: {t['description'][:50]}...")
    except Exception as e:
        print(f"Tools discovery error: {e}")

def test_tool_execution():
    print("\n--- Test 3: Tool Execution ---")
    headers = {"Authorization": f"Bearer {DEV_KEY}"}
    payload = {
        "name": "get_latest_audits",
        "arguments": {"jurisdiction": "Orting", "limit": 2}
    }
    try:
        r = requests.post(f"{BASE_URL}/api/v1/tools/execute", json=payload, headers=headers)
        print(f"Execute tool status: {r.status_code} (expected 200)")
        if r.status_code == 200:
            result = r.json().get("result", [])
            print(f"Execution returned {len(result)} audit findings.")
            if result:
                print(f"Sample: {result[0].get('jurisdiction')} - Category: {result[0].get('category')}")
    except Exception as e:
        print(f"Tool execution error: {e}")

def test_search_and_correlation():
    print("\n--- Test 4: Search & Correlation ---")
    headers = {"Authorization": f"Bearer {DEV_KEY}"}
    
    # Test search
    try:
        r_search = requests.post(f"{BASE_URL}/api/v1/search", json={"query": "internal controls", "limit": 2}, headers=headers)
        print(f"Search status: {r_search.status_code}")
        if r_search.status_code == 200:
            print(f"Search returned {len(r_search.json().get('results', []))} results.")
    except Exception as e:
        print(f"Search error: {e}")
        
    # Test correlation
    try:
        r_corr = requests.post(f"{BASE_URL}/api/v1/correlation", json={"query": "procurement policy", "limit": 2}, headers=headers)
        print(f"Correlation status: {r_corr.status_code}")
        if r_corr.status_code == 200:
            print(f"Correlation returned {len(r_corr.json().get('correlations', []))} correlations.")
    except Exception as e:
        print(f"Correlation error: {e}")

def test_openai_chat_completions_non_streaming():
    print("\n--- Test 5: OpenAI Chat Completions (Non-Streaming) ---")
    headers = {"Authorization": f"Bearer {DEV_KEY}"}
    payload = {
        "model": "pennerai-agent-v1",
        "messages": [
            {"role": "user", "content": "Were there any procurement violations in Bellevue School District audits?"}
        ],
        "stream": False,
        "temperature": 0.1
    }
    try:
        r = requests.post(f"{BASE_URL}/api/v1/chat", json=payload, headers=headers)
        print(f"Chat status: {r.status_code} (expected 200)")
        if r.status_code == 200:
            res_json = r.json()
            print("Response Metadata:")
            print(f" - ID: {res_json.get('id')}")
            print(f" - Model: {res_json.get('model')}")
            print(f" - Confidence: {res_json.get('confidence')}")
            print(f" - Last Updated: {res_json.get('last_updated')}")
            print(f" - Sources Count: {len(res_json.get('sources', []))}")
            print(f" - Content Snippet: {res_json['choices'][0]['message']['content'][:200]}...")
    except Exception as e:
        print(f"Chat completions error: {e}")

def test_openai_chat_completions_streaming():
    print("\n--- Test 6: OpenAI Chat Completions (Streaming) ---")
    headers = {"Authorization": f"Bearer {DEV_KEY}"}
    payload = {
        "model": "pennerai-agent-v1",
        "messages": [
            {"role": "user", "content": "Give me a brief summary of Orting audits."}
        ],
        "stream": True,
        "temperature": 0.1
    }
    try:
        r = requests.post(f"{BASE_URL}/api/v1/chat", json=payload, headers=headers, stream=True)
        print(f"Stream response status: {r.status_code} (expected 200)")
        if r.status_code == 200:
            print("Streaming chunks:")
            for line in r.iter_lines():
                if line:
                    decoded = line.decode("utf-8")
                    if decoded.startswith("data: "):
                        data_str = decoded[6:]
                        if data_str.strip() == "[DONE]":
                            print("\n[Stream finished]")
                            break
                        try:
                            data = json.loads(data_str)
                            delta = data["choices"][0]["delta"]
                            content = delta.get("content", "") if isinstance(delta, dict) else getattr(delta, "content", "")
                            print(content, end="", flush=True)
                        except Exception as ex:
                            print(f"\n[RAW CHUNK ERROR: {ex}] Raw Chunk: {data_str}")
    except Exception as e:
        print(f"Streaming error: {e}")


def test_usage_report():
    print("\n--- Test 7: Usage Report ---")
    headers = {"Authorization": f"Bearer {DEV_KEY}"}
    try:
        r = requests.get(f"{BASE_URL}/api/v1/usage", headers=headers)
        print(f"Usage status: {r.status_code} (expected 200)")
        if r.status_code == 200:
            print(f"Usage data: {json.dumps(r.json(), indent=2)}")
    except Exception as e:
        print(f"Usage report error: {e}")

if __name__ == "__main__":
    test_api_key_verification()
    test_tools_discovery()
    test_tool_execution()
    test_search_and_correlation()
    test_openai_chat_completions_non_streaming()
    test_openai_chat_completions_streaming()
    test_usage_report()
