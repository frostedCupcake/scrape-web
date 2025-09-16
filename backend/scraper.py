import re
import requests
import html
from typing import List, Set
from urllib.parse import urljoin, urlparse, parse_qs, urlencode, urlunparse
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

def extract_links_from_html(html_content: str, base_url: str) -> List[str]:
    """
    Extract only href links from HTML content that belong to the same domain.
    
    Args:
        html_content: The HTML content as string
        base_url: The base URL for resolving relative links
        
    Returns:
        List of unique absolute URLs found in href attributes from the same domain
    """
    # Use a set to store normalized URLs for deduplication
    normalized_links: Set[str] = set()
    
    # Get the domain from base_url
    base_parsed = urlparse(base_url)
    base_domain = base_parsed.netloc.lower()
    # Remove www. prefix if present for matching
    base_domain_clean = base_domain.replace('www.', '')
    
    # Regex patterns for href links only
    patterns = [
        # Standard href links with quotes
        r'href\s*=\s*["\']([^"\']+)["\']',
        # href links without quotes
        r'href\s*=\s*([^\s>]+)',
    ]
    
    for pattern in patterns:
        matches = re.finditer(pattern, html_content, re.IGNORECASE)
        for match in matches:
            url = match.group(1)
            
            # Unescape HTML entities (e.g., &amp; -> &)
            url = html.unescape(url)
            
            # Skip empty URLs, anchors, and javascript/mailto links
            if not url or url.startswith('#') or url.startswith('javascript:') or url.startswith('mailto:'):
                continue
            
            # Skip URLs with hash fragments
            if '#' in url:
                continue
            
            # Convert relative URLs to absolute
            absolute_url = urljoin(base_url, url)
            
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
            
            url_lower = absolute_url.lower()
            if any(pattern in url_lower for pattern in unwanted_patterns):
                continue
            
            # Validate URL format and check if it's from the same domain
            try:
                parsed = urlparse(absolute_url)
                if parsed.scheme in ['http', 'https']:
                    # Check if the URL belongs to the same domain
                    url_domain = parsed.netloc.lower()
                    url_domain_clean = url_domain.replace('www.', '')
                    
                    # Only add URLs from the same domain
                    if url_domain_clean == base_domain_clean:
                        # Clean up any malformed URLs with extra quotes
                        clean_url = absolute_url.split('"')[0]
                        # Normalize the URL to remove tracking parameters
                        normalized_url = normalize_url(clean_url)
                        normalized_links.add(normalized_url)
            except Exception:
                continue
    
    return sorted(list(normalized_links))

def scrape_url(url: str) -> dict:
    """
    Scrape a URL and extract all links from it.
    
    Args:
        url: The URL to scrape
        
    Returns:
        Dictionary containing status, links, and metadata
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
        
        # Make the request with timeout and headers
        headers = {
            'User-Agent': settings.user_agent,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1'
        }
        
        response = requests.get(
            url, 
            headers=headers,
            timeout=settings.default_timeout,
            allow_redirects=True
        )
        response.raise_for_status()
        
        # Extract links from HTML content
        links = extract_links_from_html(response.text, url)
        
        return {
            "success": True,
            "url": url,
            "final_url": response.url,  # After redirects
            "status_code": response.status_code,
            "links": links,
            "count": len(links),
            "content_type": response.headers.get('content-type', ''),
        }
        
    except requests.exceptions.Timeout:
        return {
            "success": False,
            "error": f"Request timed out after {settings.default_timeout} seconds",
            "links": [],
            "count": 0
        }
    except requests.exceptions.RequestException as e:
        return {
            "success": False,
            "error": f"Request failed: {str(e)}",
            "links": [],
            "count": 0
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Unexpected error: {str(e)}",
            "links": [],
            "count": 0
        }