#!/usr/bin/env python3
"""
Test script for the link extraction API endpoint.
Run this after starting the FastAPI server.
"""

import requests
import json
from typing import List, Dict

API_BASE_URL = "http://localhost:5000"

def test_health_check():
    """Test the health check endpoint."""
    response = requests.get(f"{API_BASE_URL}/health")
    print("Health Check Response:")
    print(json.dumps(response.json(), indent=2))
    print("-" * 50)
    return response.status_code == 200

def test_extract_links(url: str):
    """Test the link extraction endpoint."""
    payload = {"url": url}
    response = requests.post(
        f"{API_BASE_URL}/extract-links",
        json=payload,
        headers={"Content-Type": "application/json"}
    )
    
    print(f"\nExtracting links from: {url}")
    print("=" * 50)
    
    if response.status_code == 200:
        data = response.json()
        print(f"Success: {data['success']}")
        print(f"Status Code: {data.get('status_code', 'N/A')}")
        print(f"Total Links Found: {data['count']}")
        
        if data.get('error'):
            print(f"Error: {data['error']}")
        
        if data['links']:
            print(f"\nFirst 10 links found:")
            for i, link in enumerate(data['links'][:10], 1):
                print(f"  {i}. {link}")
            
            if data['count'] > 10:
                print(f"  ... and {data['count'] - 10} more links")
    else:
        print(f"Request failed with status code: {response.status_code}")
        print(f"Error: {response.text}")
    
    print("-" * 50)
    return response.status_code == 200

def test_extraction_history():
    """Test the extraction history endpoint."""
    response = requests.get(f"{API_BASE_URL}/extract-links/history")
    print("\nExtraction History:")
    print("=" * 50)
    
    if response.status_code == 200:
        history = response.json()
        print(f"Total extractions: {len(history)}")
        
        for item in history[:3]:  # Show last 3 extractions
            print(f"\n- ID: {item['id']}")
            print(f"  URL: {item['url']}")
            print(f"  Created: {item['created_at']}")
            print(f"  Links found: {item['result']['count']}")
    else:
        print(f"Request failed with status code: {response.status_code}")
    
    print("-" * 50)
    return response.status_code == 200

if __name__ == "__main__":
    print("Testing Link Extraction API")
    print("=" * 50)
    
    # Test health check
    if test_health_check():
        print("✓ Health check passed\n")
    
    # Test with various URLs
    test_urls = [
        "https://www.python.org",
        "https://github.com",
        "https://www.example.com",
        "https://invalid-url-that-does-not-exist.com",
    ]
    
    for url in test_urls:
        try:
            test_extract_links(url)
        except Exception as e:
            print(f"Error testing {url}: {e}")
            print("-" * 50)
    
    # Test extraction history
    test_extraction_history()
    
    print("\n✓ All tests completed!")