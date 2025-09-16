import re
import html
import asyncio
from typing import List, Set
from urllib.parse import urljoin, urlparse, parse_qs, urlencode, urlunparse
from playwright.async_api import async_playwright
from config import settings

def normalize_url(url: str) -> str:
    """
    Normalize URL by removing tracking parameters while keeping functional ones.
    
    Args:
        url: The URL to normalize
        
    Returns:
        Normalized URL without tracking parameters
    """
    # List of tracking parameters to remove
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


async def extract_links_with_playwright(url: str) -> dict:
    """
    Extract all links from a URL using Playwright for JavaScript rendering.
    
    Args:
        url: The URL to scrape
        
    Returns:
        Dictionary containing status, links, metadata, and site type information
    """
    try:
        # Validate URL format
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            return {
                "success": False,
                "error": "Invalid URL format",
                "links": [],
                "count": 0
            }
        
        # Get the domain from URL
        base_domain = parsed.netloc.lower()
        base_domain_clean = base_domain.replace('www.', '')
        
        # Use a set to store normalized URLs for deduplication
        normalized_links: Set[str] = set()
        
        async with async_playwright() as p:
            # Launch browser with proxy and realistic configuration
            browser = await p.chromium.launch(
                headless=True,
                proxy={
                    "server": settings.proxy_server,
                    "username": settings.proxy_username,
                    "password": settings.proxy_password
                },
                args=[
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-blink-features=AutomationControlled',
                    '--disable-features=VizDisplayCompositor',
                    '--disable-dev-shm-usage',
                    '--no-first-run',
                    '--disable-default-apps'
                ]
            )
            
            # Create context with realistic device profile
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                viewport={'width': 1440, 'height': 900},
                device_scale_factor=2,
                has_touch=False,
                is_mobile=False,
                locale='en-US',
                timezone_id='America/New_York',
                permissions=['geolocation'],
                geolocation={'latitude': 40.7128, 'longitude': -74.0060},  # New York
                extra_http_headers={
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
                    'Accept-Language': 'en-US,en;q=0.9',
                    'Accept-Encoding': 'gzip, deflate, br',
                    'Sec-Fetch-Dest': 'document',
                    'Sec-Fetch-Mode': 'navigate',
                    'Sec-Fetch-Site': 'none',
                    'Sec-Fetch-User': '?1',
                    'Upgrade-Insecure-Requests': '1'
                }
            )
            
            # Create a new page from context
            page = await context.new_page()
            
            # Add stealth measures to avoid detection
            await page.add_init_script("""
                // Override navigator.webdriver
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                
                // Mock chrome object
                window.chrome = {runtime: {}};
                
                // Override permissions query
                const originalQuery = window.navigator.permissions.query;
                window.navigator.permissions.query = (parameters) => (
                    parameters.name === 'notifications' ?
                    Promise.resolve({ state: Notification.permission }) :
                    originalQuery(parameters)
                );
            """)
            
            # Navigate to the URL and wait for network to be idle
            try:
                response = await page.goto(url, wait_until='networkidle', timeout=settings.default_timeout * 1000)
                status_code = response.status if response else None
                
                # Wait for content to load and try to scroll to trigger lazy loading
                await page.wait_for_timeout(5000)  # Increased timeout
                
                # Scroll down to trigger any lazy-loaded content
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(1000)
                
                # Extract navigation targets from all clickable elements
                discovered_urls = set()
                
                # Strategy 1: Use multiple approaches to find ALL clickable elements deterministically
                try:
                    # Approach 1: Look for all clickable elements and try clicking them
                    clickable_selectors = [
                        'button:not([disabled])',
                        '[role="button"]:not([disabled])',
                        '[role="link"]',
                        'article',
                        'div[class*="card"]:not([disabled])',
                        'div[class*="post"]',
                        'div[class*="blog"]',
                        'div[class*="item"]',
                        '[onclick]',
                        '[data-href]',
                        '[data-url]'
                    ]
                    
                    for selector in clickable_selectors:
                        try:
                            elements = await page.locator(selector).all()
                            for element in elements[:5]:  # Limit per selector to avoid timeout
                                try:
                                    before_url = page.url
                                    await element.click(timeout=300)
                                    await page.wait_for_timeout(500)
                                    after_url = page.url
                                    
                                    if after_url != before_url and after_url != url:
                                        discovered_urls.add(after_url)
                                        await page.go_back(wait_until='domcontentloaded', timeout=3000)
                                        await page.wait_for_timeout(300)
                                except:
                                    continue
                        except:
                            continue
                            
                    # Approach 2: Look for elements containing specific blog-related text
                    blog_text_selectors = [
                        ':has-text("Read more")',
                        ':has-text("Continue reading")', 
                        ':has-text("Learn more")',
                        ':has-text("View post")',
                        ':has-text("Read full")',
                        'h1 a', 'h2 a', 'h3 a'  # Headlines with links
                    ]
                    
                    for selector in blog_text_selectors:
                        try:
                            elements = await page.locator(selector).all()
                            for element in elements[:3]:  # Limit to avoid timeout
                                try:
                                    before_url = page.url
                                    await element.click(timeout=300)
                                    await page.wait_for_timeout(500)
                                    after_url = page.url
                                    
                                    if after_url != before_url and after_url != url:
                                        discovered_urls.add(after_url)
                                        await page.go_back(wait_until='domcontentloaded', timeout=3000)
                                        await page.wait_for_timeout(300)
                                except:
                                    continue
                        except:
                            continue
                            
                except Exception as e:
                    pass
                
                # Strategy 2: Extract router.push and navigation handlers from onClick attributes
                try:
                    onclick_urls = await page.evaluate("""
                        () => {
                            const urls = new Set();
                            
                            // Find all elements with onClick handlers
                            const allElements = document.querySelectorAll('*');
                            allElements.forEach(el => {
                                // Check for React props in the element
                                const reactProps = Object.keys(el).find(key => key.startsWith('__reactProps'));
                                if (reactProps && el[reactProps]) {
                                    const props = el[reactProps];
                                    // Check for onClick with router.push
                                    if (props.onClick && typeof props.onClick === 'function') {
                                        const funcStr = props.onClick.toString();
                                        // Look for router.push patterns
                                        const patterns = [
                                            /router\\.push\\(['"]([^'"]+)['"]/g,
                                            /navigate\\(['"]([^'"]+)['"]/g,
                                            /href=['"]([^'"]+)['"]/g,
                                            /to=['"]([^'"]+)['"]/g
                                        ];
                                        patterns.forEach(pattern => {
                                            let match;
                                            while ((match = pattern.exec(funcStr)) !== null) {
                                                if (match[1]) {
                                                    try {
                                                        const absoluteUrl = new URL(match[1], window.location.href).href;
                                                        urls.add(absoluteUrl);
                                                    } catch {
                                                        if (match[1].startsWith('/')) {
                                                            urls.add(window.location.origin + match[1]);
                                                        }
                                                    }
                                                }
                                            }
                                        });
                                    }
                                }
                                
                                // Check onclick attribute
                                const onclick = el.getAttribute('onclick');
                                if (onclick) {
                                    const patterns = [
                                        /location\\.href\\s*=\\s*['"]([^'"]+)['"]/,
                                        /window\\.location\\s*=\\s*['"]([^'"]+)['"]/,
                                        /router\\.push\\(['"]([^'"]+)['"]/,
                                        /navigate\\(['"]([^'"]+)['"]/
                                    ];
                                    patterns.forEach(pattern => {
                                        const match = onclick.match(pattern);
                                        if (match && match[1]) {
                                            try {
                                                const absoluteUrl = new URL(match[1], window.location.href).href;
                                                urls.add(absoluteUrl);
                                            } catch {
                                                if (match[1].startsWith('/')) {
                                                    urls.add(window.location.origin + match[1]);
                                                }
                                            }
                                        }
                                    });
                                }
                            });
                            
                            return Array.from(urls);
                        }
                    """)
                    for url in onclick_urls:
                        discovered_urls.add(url)
                except:
                    pass
                
                # Strategy 2: Extract from Next.js hydration data more aggressively
                try:
                    hydration_urls = await page.evaluate("""
                        () => {
                            const urls = new Set();
                            
                            // Look for __NEXT_DATA__
                            const nextDataEl = document.getElementById('__NEXT_DATA__');
                            if (nextDataEl) {
                                try {
                                    const nextData = JSON.parse(nextDataEl.textContent);
                                    
                                    // Recursively find all URL-like strings
                                    const findUrls = (obj, depth = 0) => {
                                        if (depth > 10) return; // Prevent infinite recursion
                                        if (!obj) return;
                                        
                                        if (typeof obj === 'string') {
                                            // Check if it's a path starting with /
                                            if (obj.startsWith('/') && obj.length > 1 && !obj.includes(' ')) {
                                                // Skip static assets
                                                if (!obj.match(/\\.(js|css|png|jpg|jpeg|gif|svg|ico|woff|woff2|ttf|eot)$/i)) {
                                                    urls.add(window.location.origin + obj);
                                                }
                                            }
                                            // Check if it's a full URL
                                            else if (obj.startsWith('http')) {
                                                urls.add(obj);
                                            }
                                        } else if (Array.isArray(obj)) {
                                            obj.forEach(item => findUrls(item, depth + 1));
                                        } else if (typeof obj === 'object') {
                                            Object.values(obj).forEach(val => findUrls(val, depth + 1));
                                        }
                                    };
                                    
                                    findUrls(nextData);
                                } catch {}
                            }
                            
                            // Look for self.__next_f.push() calls (Next.js 13+)
                            document.querySelectorAll('script').forEach(script => {
                                const text = script.textContent;
                                if (text && text.includes('self.__next_f.push')) {
                                    // Extract JSON from push calls
                                    const matches = text.matchAll(/self\\.__next_f\\.push\\(\\[\\d+,"(.+?)"\\]\\)/g);
                                    for (const match of matches) {
                                        try {
                                            const jsonStr = match[1].replace(/\\\\"/g, '"');
                                            const data = JSON.parse(jsonStr);
                                            // Recursively find URLs in this data
                                            const findUrls = (obj) => {
                                                if (!obj) return;
                                                if (typeof obj === 'string' && obj.startsWith('/')) {
                                                    urls.add(window.location.origin + obj);
                                                } else if (typeof obj === 'object') {
                                                    Object.values(obj).forEach(findUrls);
                                                }
                                            };
                                            findUrls(data);
                                        } catch {}
                                    }
                                }
                            });
                            
                            return Array.from(urls);
                        }
                    """)
                    for url in hydration_urls:
                        discovered_urls.add(url)
                except:
                    pass
                
                # Extract links using multiple strategies to handle modern JavaScript apps
                links = await page.evaluate("""
                    () => {
                        const extractedLinks = new Set();
                        
                        // 1. Traditional anchor tags with href
                        document.querySelectorAll('a[href]').forEach(a => {
                            if (a.href) extractedLinks.add(a.href);
                        });
                        
                        // 2. Elements with data attributes containing URLs
                        const dataAttrs = ['data-href', 'data-url', 'data-link', 'data-path', 'data-route'];
                        dataAttrs.forEach(attr => {
                            document.querySelectorAll(`[${attr}]`).forEach(el => {
                                const url = el.getAttribute(attr);
                                if (url) {
                                    // Convert relative URLs to absolute
                                    try {
                                        const absoluteUrl = new URL(url, window.location.href).href;
                                        extractedLinks.add(absoluteUrl);
                                    } catch {
                                        // If it's already absolute or invalid, try adding as-is
                                        if (url.startsWith('http')) extractedLinks.add(url);
                                    }
                                }
                            });
                        });
                        
                        // 3. Look for onclick handlers with navigation patterns
                        document.querySelectorAll('[onclick]').forEach(el => {
                            const onclick = el.getAttribute('onclick');
                            // Match patterns like: location.href='...', window.location='...', router.push('...')
                            const patterns = [
                                /location\.href\s*=\s*['"]([^'"]+)['"]/,
                                /window\.location\s*=\s*['"]([^'"]+)['"]/,
                                /router\.push\(['"]([^'"]+)['"]/,
                                /navigate\(['"]([^'"]+)['"]/
                            ];
                            patterns.forEach(pattern => {
                                const match = onclick.match(pattern);
                                if (match && match[1]) {
                                    try {
                                        const absoluteUrl = new URL(match[1], window.location.href).href;
                                        extractedLinks.add(absoluteUrl);
                                    } catch {
                                        if (match[1].startsWith('http')) extractedLinks.add(match[1]);
                                    }
                                }
                            });
                        });
                        
                        // 4. Look for Next.js __NEXT_DATA__ if available
                        const nextDataEl = document.getElementById('__NEXT_DATA__');
                        if (nextDataEl) {
                            try {
                                const nextData = JSON.parse(nextDataEl.textContent);
                                // Recursively search for URL-like strings in the data
                                const findUrls = (obj, baseUrl) => {
                                    if (!obj) return;
                                    if (typeof obj === 'string') {
                                        // Check if it looks like a path or slug
                                        if (obj.startsWith('/') && obj.length > 1 && !obj.includes(' ')) {
                                            // Check if it might be a blog post URL
                                            if (obj.includes('blog/') || obj.includes('post/') || obj.includes('article/')) {
                                                try {
                                                    const absoluteUrl = new URL(obj, baseUrl).href;
                                                    extractedLinks.add(absoluteUrl);
                                                } catch {}
                                            }
                                        }
                                    } else if (Array.isArray(obj)) {
                                        obj.forEach(item => findUrls(item, baseUrl));
                                    } else if (typeof obj === 'object') {
                                        // Look for specific keys that often contain URLs/slugs
                                        const urlKeys = ['href', 'url', 'slug', 'path', 'route', 'link', 'permalink', 'canonicalUrl'];
                                        Object.keys(obj).forEach(key => {
                                            if (urlKeys.includes(key.toLowerCase()) && typeof obj[key] === 'string') {
                                                const val = obj[key];
                                                if (val.includes('blog/') || val.includes('post/') || val.includes('article/')) {
                                                    try {
                                                        const absoluteUrl = new URL(val, baseUrl).href;
                                                        extractedLinks.add(absoluteUrl);
                                                    } catch {
                                                        if (val.startsWith('http')) extractedLinks.add(val);
                                                    }
                                                }
                                            }
                                            findUrls(obj[key], baseUrl);
                                        });
                                    }
                                };
                                findUrls(nextData, window.location.origin);
                            } catch {}
                        }
                        
                        // 5. Look for elements with navigation-related classes or roles
                        const navSelectors = [
                            '[role="link"]',
                            '[class*="link-card"]',
                            '[class*="blog-card"]',
                            '[class*="post-link"]',
                            '[class*="article-link"]',
                            'button[class*="read-more"]',
                            'article a',
                            '[class*="post-item"]',
                            '[class*="blog-item"]',
                            '[class*="article-item"]',
                            'h2 a',
                            'h3 a',
                            '[class*="title"] a',
                            '[class*="heading"] a'
                        ];
                        navSelectors.forEach(selector => {
                            document.querySelectorAll(selector).forEach(el => {
                                // Check for data attributes on these elements
                                dataAttrs.forEach(attr => {
                                    const url = el.getAttribute(attr);
                                    if (url) {
                                        try {
                                            const absoluteUrl = new URL(url, window.location.href).href;
                                            extractedLinks.add(absoluteUrl);
                                        } catch {}
                                    }
                                });
                            });
                        });
                        
                        return Array.from(extractedLinks);
                    }
                """)
                
                # Add discovered URLs from button clicks
                for url in discovered_urls:
                    normalized_url = normalize_url(url)
                    normalized_links.add(normalized_url)
                
                # Process each link
                for link in links:
                    # Skip empty URLs, anchors, and javascript/mailto links
                    if not link or link.startswith('#') or link.startswith('javascript:') or link.startswith('mailto:'):
                        continue
                    
                    # Skip URLs with hash fragments
                    if '#' in link:
                        continue
                    
                    # Skip URLs containing unwanted patterns
                    unwanted_patterns = [
                        'cdn',
                        '.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp',  # images
                        'assets',
                        'static',
                        '.js',  # JavaScript files
                        '.css',  # CSS files
                        '(', ')', '{', '}', '[', ']',  # brackets
                    ]
                    
                    link_lower = link.lower()
                    if any(pattern in link_lower for pattern in unwanted_patterns):
                        continue
                    
                    # Validate URL format and check if it's from the same domain
                    try:
                        link_parsed = urlparse(link)
                        if link_parsed.scheme in ['http', 'https']:
                            # Check if the URL belongs to the same domain
                            link_domain = link_parsed.netloc.lower()
                            link_domain_clean = link_domain.replace('www.', '')
                            
                            # Only add URLs from the same domain
                            if link_domain_clean == base_domain_clean:
                                # Normalize the URL to remove tracking parameters
                                normalized_url = normalize_url(link)
                                normalized_links.add(normalized_url)
                    except Exception:
                        continue
                
                # Get the final URL after any redirects
                final_url = page.url
                
            finally:
                await context.close()
                await browser.close()
        
        return {
            "success": True,
            "url": url,
            "final_url": final_url,
            "status_code": status_code,
            "links": sorted(list(normalized_links)),
            "count": len(normalized_links),
            "content_type": "text/html",
        }
        
    except asyncio.TimeoutError:
        return {
            "success": False,
            "error": f"Request timed out after {settings.default_timeout} seconds",
            "links": [],
            "count": 0
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Error: {str(e)}",
            "links": [],
            "count": 0
        }

def scrape_url(url: str) -> dict:
    """
    Synchronous wrapper for the async Playwright scraping function.
    
    Args:
        url: The URL to scrape
        
    Returns:
        Dictionary containing status, links, and metadata
    """
    # Run the async function in a new event loop
    return asyncio.run(extract_links_with_playwright(url))