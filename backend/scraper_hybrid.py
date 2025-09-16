import re
import json
import asyncio
import requests
from typing import List, Set, Dict, Any
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
from config import settings

def normalize_url(url: str) -> str:
    """
    Normalize URL by removing tracking parameters while keeping functional ones.
    """
    # Same as existing normalize_url function
    tracking_params = {
        'utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content',
        'utm_id', 'utm_cid', 'utm_reader', 'utm_referrer', 'utm_name',
        'utm_social', 'utm_social-type', 'utm_brand', 'utm_pubreferrer',
        'fbclid', 'gclid', 'dclid', 'msclkid',
        'ref', 'referrer', 'source', 'campaign',
        'mc_cid', 'mc_eid',  # Mailchimp
        'yclid',  # Yandex
        '_ga', '_gid',  # Google Analytics
        'affiliate', 'affiliateCode',
        'amp', 'amp;'
    }
    
    from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
    parsed = urlparse(url)
    
    # Parse query parameters
    query_params = parse_qs(parsed.query, keep_blank_values=True)
    
    # Keep only non-tracking parameters
    filtered_params = {
        key: value for key, value in query_params.items()
        if key.lower() not in {p.lower() for p in tracking_params}
    }
    
    # Rebuild the query string
    new_query = urlencode(filtered_params, doseq=True)
    
    # Normalize path - remove trailing slash unless it's the root path
    path = parsed.path
    if path != '/' and path.endswith('/'):
        path = path.rstrip('/')
    
    # Rebuild the URL without fragment (hash) and with filtered query
    normalized = urlunparse((
        parsed.scheme,
        parsed.netloc,
        path,
        parsed.params,
        new_query,
        ''  # Remove fragment
    ))
    
    return normalized

def extract_static_links(url: str) -> Dict[str, Any]:
    """
    Method 1: Static HTML scraping using requests + BeautifulSoup
    """
    try:
        # Get the domain from URL
        parsed = urlparse(url)
        base_domain = parsed.netloc.lower().replace('www.', '')
        
        headers = {
            'User-Agent': settings.user_agent,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
        }
        
        response = requests.get(url, headers=headers, timeout=settings.default_timeout)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        links = set()
        
        # Find all anchor tags with href
        for a in soup.find_all('a', href=True):
            href = a['href']
            
            # Skip anchors and javascript links
            if href.startswith('#') or href.startswith('javascript:') or href.startswith('mailto:'):
                continue
                
            # Convert relative to absolute
            absolute_url = urljoin(url, href)
            
            # Only same domain links
            link_domain = urlparse(absolute_url).netloc.lower().replace('www.', '')
            if link_domain == base_domain:
                # Skip unwanted patterns
                if not any(pattern in absolute_url.lower() for pattern in 
                          ['cdn', '.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', 
                           'assets', 'static', '.js', '.css']):
                    links.add(normalize_url(absolute_url))
        
        return {
            "success": True,
            "method": "static",
            "url": url,
            "status_code": response.status_code,
            "links": sorted(list(links)),
            "count": len(links)
        }
        
    except Exception as e:
        return {
            "success": False,
            "method": "static",
            "error": str(e),
            "links": [],
            "count": 0
        }

def extract_nextjs_data(url: str) -> Dict[str, Any]:
    """
    Method 2: Extract links from Next.js __NEXT_DATA__ 
    """
    try:
        headers = {'User-Agent': settings.user_agent}
        response = requests.get(url, headers=headers, timeout=settings.default_timeout)
        response.raise_for_status()
        
        html = response.text
        links = set()
        parsed_url = urlparse(url)
        base_url = f"{parsed_url.scheme}://{parsed_url.netloc}"
        
        # Look for __NEXT_DATA__
        match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(1))
                
                def walk_json(obj, depth=0):
                    if depth > 10:  # Prevent infinite recursion
                        return
                        
                    if isinstance(obj, dict):
                        for k, v in obj.items():
                            # Look for slug, path, href, url keys
                            if k in ['slug', 'path', 'href', 'url'] and isinstance(v, str):
                                if v.startswith('/') and len(v) > 1:
                                    # Skip static assets
                                    if not v.endswith(('.js', '.css', '.png', '.jpg', '.jpeg', '.gif', '.svg')):
                                        full_url = base_url + v
                                        links.add(normalize_url(full_url))
                            elif isinstance(v, (dict, list)):
                                walk_json(v, depth + 1)
                    elif isinstance(obj, list):
                        for item in obj:
                            walk_json(item, depth + 1)
                
                walk_json(data)
                
            except json.JSONDecodeError:
                pass
        
        # Also look for self.__next_f.push() calls (Next.js 13+)
        next_f_matches = re.findall(r'self\.__next_f\.push\(\[\d+,"(.+?)"\]\)', html)
        print(f"Found {len(next_f_matches)} self.__next_f.push calls")
        
        for i, match in enumerate(next_f_matches):
            try:
                # Unescape the JSON string - handle multiple escape levels
                json_str = match.replace('\\\\', '\\').replace('\\"', '"').replace('\\/', '/')
                
                # Try multiple regex patterns to find blog URLs
                blog_patterns = [
                    r'/blog/[a-zA-Z0-9-]+(?:-[a-zA-Z0-9-]+)*',  # Standard blog slugs
                    r'/blog/[^"\\s<>]+[a-zA-Z0-9-]+',  # Generic blog paths
                    r'"slug":"([^"]+)"',  # JSON slug values
                    r'"path":"(/blog/[^"]+)"',  # JSON path values
                    r'"href":"(/blog/[^"]+)"',  # JSON href values
                    r'"/blog/([^"/]+)',  # Simple blog path extraction
                ]
                
                for pattern_regex in blog_patterns:
                    matches = re.findall(pattern_regex, json_str)
                    for match in matches:
                        # Handle both full paths and just slugs
                        if match.startswith('/blog/'):
                            url_path = match
                        elif isinstance(match, str) and not match.startswith('/'):
                            url_path = f'/blog/{match}'
                        else:
                            url_path = match
                            
                        # Skip unwanted patterns
                        if not any(ext in url_path for ext in ['.js', '.css', '.png', '.jpg', '.gif', '.svg']):
                            if url_path != '/blog' and len(url_path) > 6:
                                full_url = base_url + url_path
                                links.add(normalize_url(full_url))
                                print(f"  Found blog URL: {url_path}")
                
                # Also try to parse as JSON
                try:
                    data = json.loads(json_str)
                    walk_json(data)
                except json.JSONDecodeError:
                    # If JSON parsing fails, look for URL patterns in the string
                    continue
                    
            except Exception as e:
                continue
        
        return {
            "success": True,
            "method": "nextjs",
            "url": url,
            "links": sorted(list(links)),
            "count": len(links)
        }
        
    except Exception as e:
        return {
            "success": False,
            "method": "nextjs", 
            "error": str(e),
            "links": [],
            "count": 0
        }

async def extract_dynamic_links(url: str) -> Dict[str, Any]:
    """
    Method 3: Dynamic rendering with smart element clicking
    """
    try:
        parsed = urlparse(url)
        base_domain = parsed.netloc.lower().replace('www.', '')
        links = set()
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                proxy={
                    "server": settings.proxy_server,
                    "username": settings.proxy_username,
                    "password": settings.proxy_password
                }
            )
            
            page = await browser.new_page()
            
            try:
                print(f"Loading page: {url}")
                await page.goto(url, wait_until='domcontentloaded', timeout=15000)
                
                # Wait for page to fully load
                print("Waiting for page to render...")
                await page.wait_for_timeout(5000)
                
                # Scroll to trigger lazy loading
                await page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
                await page.wait_for_timeout(2000)
                
                # Method 3a: Extract static links first
                try:
                    dom_links = await page.eval_on_selector_all(
                        'a[href]', 
                        'els => els.map(el => el.href)'
                    )
                    
                    for link in dom_links:
                        if link:
                            link_domain = urlparse(link).netloc.lower().replace('www.', '')
                            if not link_domain or link_domain == base_domain:
                                if not any(pattern in link.lower() for pattern in 
                                          ['cdn', '.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp',
                                           'assets', 'static', '.js', '.css']):
                                    links.add(normalize_url(link))
                except Exception as e:
                    print(f"Static link extraction failed: {e}")
                
                # Method 3b: Smart clicking - only elements with repeated class names
                print("Analyzing repeated class name patterns...")
                try:
                    # Find elements with repeated class names (2 or more elements)
                    class_analysis = await page.evaluate('''
                        () => {
                            const elements = document.querySelectorAll('button, [role="button"], a, [onclick], div[class]');
                            const classCount = {};
                            const elementsByClass = {};
                            
                            // Count class occurrences and group elements
                            elements.forEach((el, index) => {
                                if (el.className && el.className.trim()) {
                                    const classes = el.className.trim();
                                    classCount[classes] = (classCount[classes] || 0) + 1;
                                    
                                    if (!elementsByClass[classes]) {
                                        elementsByClass[classes] = [];
                                    }
                                    elementsByClass[classes].push({
                                        index,
                                        text: el.textContent?.trim().substring(0, 50),
                                        tagName: el.tagName.toLowerCase(),
                                        href: el.href,
                                        visible: el.offsetWidth > 0 && el.offsetHeight > 0,
                                        hasClickHandler: !!el.onclick
                                    });
                                }
                            });
                            
                            // Find repeated classes (2 or more elements) - sorted by count
                            const repeatedClasses = Object.entries(classCount)
                                .filter(([className, count]) => count >= 2)
                                .sort((a, b) => b[1] - a[1])
                                .slice(0, 10);  // Top 10 repeated classes
                            
                            return repeatedClasses.map(([className, count]) => ({
                                className,
                                count,
                                elements: elementsByClass[className].filter(el => el.visible)
                            }));
                        }
                    ''')
                    
                    print(f"Found {len(class_analysis)} repeated class patterns")
                    
                    # Only proceed if we found repeated class patterns
                    if len(class_analysis) == 0:
                        print("  ⚠️  No repeated class patterns found - skipping element clicking")
                    else:
                        # Click elements from repeated patterns only
                        clicked_urls = set()
                        original_url = page.url
                        
                        for pattern_idx, pattern in enumerate(class_analysis[:5]):  # Top 5 patterns
                            if len(clicked_urls) >= 10:  # Limit total clicks
                                break
                                
                            print(f"Pattern {pattern_idx + 1}: '{pattern['className'][:80]}...' ({pattern['count']} elements)")
                            
                            # Click up to 3 elements from each repeated pattern
                            for i, element_info in enumerate(pattern['elements'][:3]):
                                if len(clicked_urls) >= 10:
                                    break
                                    
                                try:
                                    # Navigate back to original page if we're somewhere else
                                    if page.url != original_url:
                                        await page.goto(original_url, wait_until='domcontentloaded', timeout=10000)
                                        await page.wait_for_timeout(1000)
                                    
                                    # Find the element by its class
                                    element_selector = f'.{pattern["className"].replace(" ", ".")}'
                                    try:
                                        # Get all elements with this class
                                        class_elements = await page.locator(element_selector).all()
                                        
                                        if i < len(class_elements):
                                            element = class_elements[i]
                                            
                                            # Check if element is still visible and clickable
                                            is_visible = await element.is_visible()
                                            if not is_visible:
                                                continue
                                            
                                            before_url = page.url
                                            print(f"  Clicking element {i+1}: '{element_info['text'][:30]}...' ({element_info['tagName']})")
                                            
                                            # Handle different element types
                                            if element_info['tagName'] == 'a' and element_info['href']:
                                                # For links, add the href without clicking
                                                print(f"    → Link href: {element_info['href']}")
                                                links.add(normalize_url(element_info['href']))
                                            else:
                                                # For buttons and other clickable elements
                                                try:
                                                    await element.click(timeout=5000)
                                                    await page.wait_for_timeout(3000)  # Wait for navigation
                                                    
                                                    after_url = page.url
                                                    
                                                    if after_url != before_url:
                                                        print(f"    ✓ Navigation: {before_url} → {after_url}")
                                                        clicked_urls.add(normalize_url(after_url))
                                                        links.add(normalize_url(after_url))
                                                    else:
                                                        print(f"    - No navigation detected")
                                                        
                                                except Exception as click_error:
                                                    print(f"    ✗ Click failed: {click_error}")
                                            
                                    except Exception as selector_error:
                                        print(f"    ✗ Selector failed: {selector_error}")
                                        continue
                                        
                                except Exception as e:
                                    print(f"    ✗ Element processing failed: {e}")
                                    continue
                        
                        print(f"Successfully clicked and captured {len(clicked_urls)} navigation URLs from repeated patterns")
                    
                except Exception as e:
                    print(f"Smart clicking failed: {e}")
                    
            finally:
                await browser.close()
        
        return {
            "success": True,
            "method": "dynamic",
            "url": url,
            "links": sorted(list(links)),
            "count": len(links)
        }
        
    except Exception as e:
        return {
            "success": False,
            "method": "dynamic",
            "error": str(e), 
            "links": [],
            "count": 0
        }

async def extract_links_hybrid(url: str) -> Dict[str, Any]:
    """
    Hybrid approach: Try all three methods and combine results
    """
    all_links = set()
    methods_used = []
    errors = []
    
    # Method 1: Static HTML scraping (fastest)
    print(f"Trying static HTML scraping...")
    static_result = extract_static_links(url)
    if static_result["success"] and static_result["count"] > 0:
        all_links.update(static_result["links"])
        methods_used.append("static")
        print(f"  ✓ Static: {static_result['count']} links")
    else:
        if not static_result["success"]:
            errors.append(f"Static: {static_result.get('error', 'unknown')}")
        print(f"  - Static: {static_result['count']} links")
    
    # Method 2: Next.js data extraction
    print(f"Trying Next.js data extraction...")
    nextjs_result = extract_nextjs_data(url)
    if nextjs_result["success"] and nextjs_result["count"] > 0:
        all_links.update(nextjs_result["links"])
        methods_used.append("nextjs")
        print(f"  ✓ Next.js: {nextjs_result['count']} links")
    else:
        if not nextjs_result["success"]:
            errors.append(f"Next.js: {nextjs_result.get('error', 'unknown')}")
        print(f"  - Next.js: {nextjs_result['count']} links")
    
    # Method 3: Dynamic rendering (if needed)
    if len(all_links) < 5:  # If we don't have many links, try dynamic
        print(f"Trying dynamic rendering...")
        dynamic_result = await extract_dynamic_links(url)
        if dynamic_result["success"] and dynamic_result["count"] > 0:
            all_links.update(dynamic_result["links"])
            methods_used.append("dynamic")
            print(f"  ✓ Dynamic: {dynamic_result['count']} links")
        else:
            if not dynamic_result["success"]:
                errors.append(f"Dynamic: {dynamic_result.get('error', 'unknown')}")
            print(f"  - Dynamic: {dynamic_result['count']} links")
    
    return {
        "success": len(all_links) > 0,
        "url": url,
        "links": sorted(list(all_links)),
        "count": len(all_links),
        "methods_used": methods_used,
        "errors": errors if errors else None
    }