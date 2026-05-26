import sys
import os
import json

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from services.backend.correlation_engine import save_correlation

def test():
    test_corr = {
        "title": "Test Correlation Direct Run",
        "hook": "This is a test hook",
        "report_markdown": "This is test report markdown",
        "citations": [{"id": "123", "source": "audit", "title": "Test Audit", "url": "http://test"}]
    }
    
    print("Saving test correlation...")
    res = save_correlation(test_corr)
    print(f"Result ID: {res}")

if __name__ == "__main__":
    test()
