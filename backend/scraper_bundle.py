import re
import json
import asyncio
from typing import List, Set, Dict, Any
from urllib.parse import urljoin, urlparse
from playwright.async_api import async_playwright
from config import settings

async def extract_links_from_bundle(url: str) -> Dict[str, Any]:
    """
    Extract blog post links by parsing client bundle and extracting slug data.
    
    This approach:
    1. Loads the page and captures all JavaScript bundle content
    2. Searches for /blog/ patterns in the compiled code
    3. Extracts posts array with slug fields from modules
    4. Programmatically constructs URLs using https://domain/blog/{slug}
    5. Verifies navigation patterns with runtime checks
    """
    try:
        parsed = urlparse(url)
        base_url = f"{parsed.scheme}://{parsed.netloc}"
        blog_posts = set()
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)  # Remove proxy for testing
            
            page = await browser.new_page()
            
            try:
                print(f"Loading page: {url}")
                await page.goto(url, wait_until='load', timeout=15000)
                await page.wait_for_timeout(2000)
                
                print("Step 1: Capturing all JavaScript bundle sources...")
                
                # Get all script sources and inline scripts
                script_sources = await page.evaluate('''
                    () => {
                        const scripts = document.querySelectorAll('script');
                        const sources = [];
                        
                        scripts.forEach((script, index) => {
                            if (script.src) {
                                // External script - we'll fetch this
                                sources.push({
                                    type: 'external',
                                    src: script.src,
                                    index
                                });
                            } else if (script.textContent) {
                                // Inline script
                                sources.push({
                                    type: 'inline',
                                    content: script.textContent,
                                    index
                                });
                            }
                        });
                        
                        return sources;
                    }
                ''')
                
                print(f"Found {len(script_sources)} script sources")
                
                # Collect all JavaScript content
                all_js_content = []
                
                for script in script_sources[:20]:  # Limit to first 20 scripts
                    if script['type'] == 'inline':
                        all_js_content.append(script['content'])
                    elif script['type'] == 'external':
                        try:
                            # Fetch external script content
                            js_response = await page.goto(script['src'], wait_until='domcontentloaded', timeout=10000)
                            if js_response and js_response.status == 200:
                                js_content = await js_response.text()
                                all_js_content.append(js_content)
                                print(f"  ✓ Fetched external script: {script['src'][-50:]}")
                        except Exception as e:
                            print(f"  ✗ Failed to fetch script: {e}")
                
                # Go back to original page
                await page.goto(url, wait_until='domcontentloaded', timeout=15000)
                
                print(f"Step 2: Searching for patterns in {len(all_js_content)} scripts...")
                
                # Search for patterns in all JavaScript content
                slug_patterns = set()
                post_objects = []
                href_links = set()
                
                # Also extract regular hrefs from the page HTML
                print("Step 2a: Extracting regular href links from page...")
                page_links = await page.evaluate(f'''
                    () => {{
                        const links = document.querySelectorAll('a[href]');
                        const sameHostLinks = [];
                        const currentHost = '{parsed.netloc}';
                        
                        links.forEach(link => {{
                            const href = link.getAttribute('href');
                            if (href) {{
                                // Skip fragment-only links, mailto, tel
                                if (href.startsWith('#') || href.startsWith('mailto:') || href.startsWith('tel:')) {{
                                    return;
                                }}
                                
                                let fullUrl;
                                if (href.startsWith('http')) {{
                                    fullUrl = href;
                                }} else if (href.startsWith('/')) {{
                                    fullUrl = '{base_url}' + href;
                                }} else {{
                                    fullUrl = '{base_url}/' + href;
                                }}
                                
                                // Remove fragment from URL if present
                                if (fullUrl.includes('#')) {{
                                    fullUrl = fullUrl.split('#')[0];
                                }}
                                
                                try {{
                                    const url = new URL(fullUrl);
                                    if (url.hostname === currentHost && fullUrl.trim() !== '') {{
                                        sameHostLinks.push(fullUrl);
                                    }}
                                }} catch (e) {{
                                    // Invalid URL, skip
                                }}
                            }}
                        }});
                        
                        return sameHostLinks;
                    }}
                ''')
                
                for link in page_links:
                    href_links.add(link)
                
                print(f"Found {len(href_links)} same-domain href links")
                
                for i, content in enumerate(all_js_content):
                    if not content or len(content) < 100:  # Skip tiny scripts
                        continue
                    
                    # Pattern 1: Direct /blog/ URLs in strings
                    blog_urls = re.findall(r'["\']\/blog\/([^"\'\/\s]{3,50})["\']', content)
                    for slug in blog_urls:
                        if slug and '-' in slug:  # Blog slugs typically have hyphens
                            slug_patterns.add(slug)
                    
                    # Pattern 2: Look for post objects with slug fields
                    post_object_matches = re.findall(
                        r'\{[^}]*?["\']slug["\']:\s*["\']([^"\']{5,50})["\'][^}]*?\}', 
                        content, 
                        re.IGNORECASE
                    )
                    
                    for slug in post_object_matches:
                        if slug and '-' in slug:
                            slug_patterns.add(slug)
                    
                    # Pattern 3: router.push or window.location patterns
                    router_patterns = re.findall(
                        r'(?:router\.push|window\.location\.href|navigate)\(["\'](?:\/blog\/)?([^"\']{5,50})["\']', 
                        content
                    )
                    
                    for slug in router_patterns:
                        if slug and '-' in slug and not slug.startswith('http'):
                            slug_patterns.add(slug)
                    
                    # Pattern 4: Array of post objects
                    array_matches = re.findall(
                        r'\[(?:\s*\{[^}]*?["\']slug["\']:\s*["\']([^"\']{5,50})["\'][^}]*?\}\s*,?)+\s*\]',
                        content,
                        re.DOTALL
                    )
                    
                    for match in array_matches:
                        if match and '-' in match:
                            slug_patterns.add(match)
                
                print(f"Found {len(slug_patterns)} potential blog slugs")
                
                # Step 3: Construct URLs and verify them
                print("Step 3: Constructing URLs intelligently...")
                
                # Intelligently determine the base path from the current URL
                current_path = parsed.path.rstrip('/')
                if not current_path:
                    current_path = ""
                
                print(f"Current URL path: '{current_path}'")
                print(f"Will append slugs to: {base_url}{current_path}")
                
                for slug in slug_patterns:
                    # Clean the slug
                    clean_slug = re.sub(r'[^a-zA-Z0-9\-]', '', slug)
                    if len(clean_slug) >= 5 and '-' in clean_slug:
                        # Intelligently construct URL by appending slug to current path
                        constructed_url = f"{base_url}{current_path}/{clean_slug}"
                        
                        # Remove any fragments if present
                        if '#' in constructed_url:
                            constructed_url = constructed_url.split('#')[0]
                        
                        blog_posts.add(constructed_url)
                        print(f"  ✓ Constructed: {constructed_url}")
                
                print(f"Constructed {len(blog_posts)} blog URLs")
                
                # Step 4: Runtime verification - patch history and test navigation
                print("Step 4: Runtime verification with history patching...")
                
                navigation_logs = []
                
                # Set up history patching and click monitoring
                await page.evaluate('''
                    () => {
                        window.navigationLogs = [];
                        
                        // Patch history.pushState to log SPA navigations
                        const originalPushState = history.pushState;
                        history.pushState = function(...args) {
                            window.navigationLogs.push({
                                type: 'pushState',
                                url: args[2],
                                timestamp: Date.now()
                            });
                            console.log('SPA Navigation:', args);
                            return originalPushState.apply(history, args);
                        };
                        
                        // Also patch replaceState
                        const originalReplaceState = history.replaceState;
                        history.replaceState = function(...args) {
                            window.navigationLogs.push({
                                type: 'replaceState', 
                                url: args[2],
                                timestamp: Date.now()
                            });
                            return originalReplaceState.apply(history, args);
                        };
                        
                        return 'History patching complete';
                    }
                ''')
                
                # Try clicking a few elements to verify navigation patterns
                try:
                    clickable_elements = await page.locator('div[class*="cursor-pointer"], button, [onclick]').all()
                    
                    for i, element in enumerate(clickable_elements[:3]):
                        try:
                            if await element.is_visible():
                                print(f"  Testing click on element {i+1}...")
                                await element.click(timeout=2000)
                                await page.wait_for_timeout(1000)
                                
                                # Check for navigation logs
                                logs = await page.evaluate('window.navigationLogs || []')
                                if logs:
                                    latest_log = logs[-1]
                                    print(f"    ✓ Detected navigation: {latest_log}")
                                    
                                    # Extract any URLs from the navigation that match our current path pattern
                                    nav_url = latest_log.get('url', '')
                                    if nav_url and current_path in str(nav_url):
                                        if nav_url.startswith('/'):
                                            full_nav_url = base_url + nav_url
                                        else:
                                            full_nav_url = nav_url
                                        
                                        # Remove fragments from navigation URL
                                        if '#' in full_nav_url:
                                            full_nav_url = full_nav_url.split('#')[0]
                                        
                                        blog_posts.add(full_nav_url)
                                        print(f"    ✓ Added from navigation: {full_nav_url}")
                                
                                # Return to original page
                                await page.goto(url, wait_until='domcontentloaded', timeout=10000)
                                await page.wait_for_timeout(500)
                                
                        except Exception as click_error:
                            print(f"    ✗ Click test failed: {click_error}")
                            continue
                            
                except Exception as e:
                    print(f"  Runtime verification failed: {e}")
                
            finally:
                await browser.close()
        
        # Combine both href links and constructed slug links
        all_found_links = set()
        current_path = parsed.path.rstrip('/')
        
        # Add regular href links (already same-domain filtered)
        for href_link in href_links:
            all_found_links.add(href_link)
        
        # Add constructed slug links 
        for post_url in blog_posts:
            # Ensure it's not just the base path (avoid duplicating the main page)
            if post_url != base_url + current_path and post_url != base_url + current_path + "/":
                # Ensure it has a slug (more than just the current path)
                if len(post_url) > len(base_url + current_path + "/"):
                    all_found_links.add(post_url)
        
        verified_posts = all_found_links
        
        # Save debug output to JSON file
        import json
        from datetime import datetime
        debug_data = {
            "timestamp": datetime.now().isoformat(),
            "url": url,
            "base_url": base_url,
            "current_path": current_path,
            "scripts_found": len(all_js_content),
            "href_links_found": sorted(list(href_links)),
            "href_links_count": len(href_links),
            "slug_patterns_found": sorted(list(slug_patterns)),
            "slug_patterns_count": len(slug_patterns),
            "constructed_urls": sorted(list(blog_posts)),
            "all_combined_links": sorted(list(verified_posts)),
            "final_count": len(verified_posts),
            "js_content_lengths": [len(content) for content in all_js_content if content]
        }
        
        debug_file = f"data/bundle_debug_{int(datetime.now().timestamp())}.json"
        with open(debug_file, "w") as f:
            json.dump(debug_data, f, indent=2)
        
        print(f"Debug data saved to: {debug_file}")
        
        return {
            "success": True,
            "method": "hybrid_extraction",
            "url": url,
            "links": sorted(list(verified_posts)),
            "count": len(verified_posts),
            "href_links_found": len(href_links),
            "slug_patterns_found": len(slug_patterns),
            "extraction_methods": ["href_parsing", "bundle_slug_construction"],
            "verification_method": "same_hostname_filtering",
            "debug_file": debug_file
        }
        
    except Exception as e:
        return {
            "success": False,
            "method": "bundle_parsing",
            "error": str(e),
            "links": [],
            "count": 0
        }