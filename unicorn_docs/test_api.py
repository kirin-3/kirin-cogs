#!/usr/bin/env python3
"""
Test script to verify OpenRouter API connection and embedding generation.
"""

import os
import json
import requests
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

def test_api_connection():
    """Test the OpenRouter API connection."""
    print("🔍 Testing OpenRouter API Connection...")
    print(f"API Key: {'*' * 20 if OPENROUTER_API_KEY else 'NOT SET'}")
    
    if not OPENROUTER_API_KEY:
        print("❌ Error: OPENROUTER_API_KEY not found in environment variables.")
        print("Please create a .env file with your OpenRouter API key:")
        print("OPENROUTER_API_KEY=your_api_key_here")
        return False
    
    # Test with a simple embedding request
    test_text = "This is a test document for embedding generation."
    
    try:
        print(f"📝 Testing with text: '{test_text}'")
        
        response = requests.post(
            url="https://openrouter.ai/api/v1/embeddings",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json"
            },
            data=json.dumps({
                "model": "text-embedding-ada-002",
                "input": test_text
            }),
            timeout=30
        )
        
        print(f"📊 Response Status: {response.status_code}")
        print(f"📄 Response Headers: {dict(response.headers)}")
        print(f"📝 Response Text (first 500 chars): {response.text[:500]}")
        
        if response.status_code == 200:
            try:
                result = response.json()
                print("✅ JSON parsing successful!")
                print(f"📊 Response structure: {list(result.keys())}")
                
                if 'data' in result and len(result['data']) > 0:
                    embedding = result['data'][0]['embedding']
                    print(f"✅ Embedding generated successfully!")
                    print(f"📊 Embedding length: {len(embedding)}")
                    print(f"📊 First 5 values: {embedding[:5]}")
                    return True
                else:
                    print("❌ No embedding data in response")
                    return False
                    
            except json.JSONDecodeError as e:
                print(f"❌ JSON parsing failed: {e}")
                return False
        else:
            print(f"❌ API request failed with status {response.status_code}")
            return False
            
    except requests.exceptions.RequestException as e:
        print(f"❌ Request failed: {e}")
        return False
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return False

def test_models():
    """Test available models on OpenRouter."""
    print("\n🔍 Testing available models...")
    
    try:
        response = requests.get(
            url="https://openrouter.ai/api/v1/models",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json"
            },
            timeout=30
        )
        
        if response.status_code == 200:
            models = response.json()
            print("✅ Models API accessible")
            
            # Look for embedding models
            embedding_models = []
            for model in models.get('data', []):
                if 'embedding' in model.get('name', '').lower():
                    embedding_models.append(model['name'])
            
            print(f"📊 Found {len(embedding_models)} embedding models:")
            for model in embedding_models[:5]:  # Show first 5
                print(f"  - {model}")
                
            return True
        else:
            print(f"❌ Models API failed: {response.status_code}")
            return False
            
    except Exception as e:
        print(f"❌ Models API error: {e}")
        return False

if __name__ == "__main__":
    print("🚀 OpenRouter API Test Script")
    print("=" * 50)
    
    # Test API connection
    api_works = test_api_connection()
    
    if api_works:
        # Test models
        test_models()
        print("\n✅ All tests passed! Your API key is working correctly.")
    else:
        print("\n❌ API tests failed. Please check your API key and try again.")
        print("\nTroubleshooting:")
        print("1. Verify your API key is correct")
        print("2. Check if you have credits in your OpenRouter account")
        print("3. Ensure your account has access to embedding models")
        print("4. Try regenerating your API key")
