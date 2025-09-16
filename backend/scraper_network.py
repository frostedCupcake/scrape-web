import re
import json
import asyncio
from typing import List, Set, Dict, Any
from urllib.parse import urlparse
from playwright.async_api import async_playwright
from config import settings

async def extract_links_from_network(url: str) -> Dict[str, Any]:
    """
    Extract links by intercepting network requests and parsing API responses.
    This is the most reliable method for JavaScript-heavy sites.
    """
    try:
        parsed = urlparse(url)
        base_domain = parsed.netloc.lower().replace('www.', '')
        base_url = f"{parsed.scheme}://{parsed.netloc}"
        links = set()
        api_responses = []
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                proxy={
                    "server": settings.proxy_server,
                    "username": settings.proxy_username,
                    "password": settings.proxy_password
                }
            )
            
            context = await browser.new_context()
            page = await context.new_page()
            
            # Set up network interception
            async def handle_response(response):
                try:
                    # Only intercept JSON responses that might contain blog data
                    if ('json' in response.headers.get('content-type', '').lower() or 
                        response.url.endswith('.json') or
                        'api' in response.url.lower() or
                        'blog' in response.url.lower() or
                        'post' in response.url.lower()):
                        
                        content = await response.text()
                        api_responses.append({
                            'url': response.url,
                            'content': content,
                            'content_type': response.headers.get('content-type', '')
                        })
                        print(f"Captured API response: {response.url}")
                        
                except Exception as e:
                    pass
            
            page.on('response', handle_response)
            
            try:
                # Navigate and wait for page to fully load
                await page.goto(url, wait_until='networkidle', timeout=30000)
                await page.wait_for_timeout(5000)
                
                # Scroll to trigger any lazy loading
                await page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
                await page.wait_for_timeout(3000)
                
                # Also get static content as fallback
                static_links = await page.eval_on_selector_all(
                    'a[href]',
                    'els => els.map(el => el.href)'
                )
                
                for link in static_links:
                    if link and base_domain in link and '/blog/' in link:
                        links.add(link)
                
            finally:
                await context.close()
                await browser.close()
        
        print(f"Captured {len(api_responses)} API responses")
        
        # Process all captured API responses with regex
        for response in api_responses:
            content = response['content']
            
            # Multiple regex patterns to extract blog URLs from JSON/API responses
            patterns = [
                # Direct blog URLs
                r'https?://[^"\s]*?/blog/[^"\s]+',
                r'"(\/blog\/[^"]+)"',
                r"'(\/blog\/[^']+)'",
                
                # Blog slugs in JSON
                r'"slug"\s*:\s*"([^"]+)"',
                r'"path"\s*:\s*"(\/blog\/[^"]+)"',
                r'"href"\s*:\s*"(\/blog\/[^"]+)"',
                r'"url"\s*:\s*"(\/blog\/[^"]+)"',
                r'"permalink"\s*:\s*"(\/blog\/[^"]+)"',
                
                # Next.js/React router patterns
                r'"route"\s*:\s*"(\/blog\/[^"]+)"',
                r'"pathname"\s*:\s*"(\/blog\/[^"]+)"',
                
                # Blog post identifiers
                r'"id"\s*:\s*"([^"]*blog[^"]*)"',
                r'"title"\s*:\s*"([^"]+)"\s*,\s*"slug"\s*:\s*"([^"]+)"',
                
                # URL-like patterns in text
                r'\/blog\/[a-zA-Z0-9][a-zA-Z0-9\-]*[a-zA-Z0-9]',
                r'blog\/[a-zA-Z0-9][a-zA-Z0-9\-_]*',
            ]
            
            for pattern in patterns:
                matches = re.findall(pattern, content, re.IGNORECASE)
                for match in matches:
                    # Handle tuple matches from groups
                    if isinstance(match, tuple):
                        for submatch in match:
                            if submatch and 'blog' in submatch.lower():
                                process_match(submatch, base_url, links)
                    else:
                        process_match(match, base_url, links)
            
            # Also try to parse as JSON and walk the structure
            try:
                if content.strip().startswith('{') or content.strip().startswith('['):
                    data = json.loads(content)
                    extract_urls_from_json(data, base_url, links)
            except:
                pass
        
        # Filter and clean up links
        filtered_links = set()
        for link in links:
            # Skip unwanted patterns
            if not any(unwanted in link.lower() for unwanted in 
                      ['.js', '.css', '.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp',
                       'assets', 'static', 'cdn']):
                if '/blog/' in link and link != f"{base_url}/blog":
                    # Ensure it's from the same domain
                    link_domain = urlparse(link).netloc.lower().replace('www.', '')
                    if not link_domain or link_domain == base_domain:
                        filtered_links.add(link)
        
        return {
            "success": True,
            "method": "network_interception",
            "url": url,
            "links": sorted(list(filtered_links)),
            "count": len(filtered_links),
            "api_responses_captured": len(api_responses)
        }
        
    except Exception as e:
        return {
            "success": False,
            "method": "network_interception",
            "error": str(e),
            "links": [],
            "count": 0
        }

def process_match(match, base_url, links):
    """Process a regex match and add valid URLs to links set"""
    if not match or len(match) < 3:
        return
        
    # Clean up the match
    match = match.strip('\'"\\/')
    
    if match.startswith('http'):
        # Already a full URL
        links.add(match)
    elif match.startswith('/blog/'):
        # Relative URL starting with /blog/
        links.add(base_url + match)
    elif match.startswith('blog/'):
        # Relative URL starting with blog/
        links.add(base_url + '/' + match)
    elif 'blog' in match and '/' not in match:
        # Might be a slug - construct blog URL
        links.add(f"{base_url}/blog/{match}")

def extract_urls_from_json(data, base_url, links, depth=0):
    """Recursively extract URLs from JSON data"""
    if depth > 5:  # Prevent infinite recursion
        return
        
    try:
        if isinstance(data, dict):
            for key, value in data.items():
                if isinstance(value, str):
                    # Check if the value looks like a blog URL or slug
                    if ('blog' in value.lower() and 
                        (value.startswith('/') or value.startswith('http') or 
                         (len(value) > 3 and len(value) < 100 and '-' in value))):
                        process_match(value, base_url, links)
                elif isinstance(value, (dict, list)):
                    extract_urls_from_json(value, base_url, links, depth + 1)
        elif isinstance(data, list):
            for item in data:
                extract_urls_from_json(item, base_url, links, depth + 1)
    except:
        pass