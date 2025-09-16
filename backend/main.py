from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, HttpUrl
import os
from pathlib import Path
import json
from datetime import datetime
from typing import List, Dict, Any, Optional
from urllib.parse import urlparse
from config import settings
from scraper_bundle import extract_links_from_bundle
import requests as requests_lib

app = FastAPI(
    title="Scrape Web API",
    description="A FastAPI backend for web scraping with file-based storage",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def convert_html_to_markdown(cleaned_html: str, source_url: str) -> Dict[str, Any]:
    """
    Convert cleaned HTML to clean markdown data
    """
    try:
        print(f"🔄 DEBUG: Converting HTML to markdown for {source_url}")
        
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(cleaned_html, 'html.parser')
        
        # Extract title - try to get the actual article title, not navigation
        title_element = None
        # Look for article title (usually the largest h1 or h2)
        for header in ['h1', 'h2']:
            headers = soup.find_all(header)
            for h in headers:
                h_text = h.get_text(strip=True)
                # Skip navigation headers like "Blog", "Product", etc.
                if h_text and len(h_text) > 10 and not h_text in ['Blog', 'Product', 'Docs', 'Jobs', 'Home']:
                    title_element = h
                    break
            if title_element:
                break
        
        title = title_element.get_text(strip=True) if title_element else "Untitled"
        
        # Determine content type from URL
        content_type = "other"
        if "/blog/" in source_url:
            content_type = "blog"
        elif "/podcast/" in source_url:
            content_type = "podcast_transcript"
        elif "transcript" in source_url.lower():
            content_type = "call_transcript"
        elif "linkedin.com" in source_url:
            content_type = "linkedin_post"
        elif "reddit.com" in source_url:
            content_type = "reddit_comment"
        elif "/book/" in source_url:
            content_type = "book"
        
        # Process HTML to markdown in document order
        markdown_lines = []
        
        # Get the main content body
        body = soup.find('body') if soup.find('body') else soup
        
        # Process all text elements in order, avoiding duplicates
        processed_content = set()
        
        for element in body.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'div', 'p']):
            text = element.get_text(strip=True)
            
            # Skip empty, duplicate, or navigation content
            if not text or text in processed_content:
                continue
            if text in ['Blog', 'Product', 'Docs', 'Jobs', 'See Quill', 'Home']:
                continue
                
            # Add markdown formatting based on element type
            if element.name == 'h1':
                markdown_lines.append(f"# {text}")
            elif element.name == 'h2':
                markdown_lines.append(f"## {text}")
            elif element.name == 'h3':
                markdown_lines.append(f"### {text}")
            elif element.name == 'h4':
                markdown_lines.append(f"#### {text}")
            elif element.name == 'h5':
                markdown_lines.append(f"##### {text}")
            elif element.name == 'h6':
                markdown_lines.append(f"###### {text}")
            elif element.name in ['div', 'p']:
                # Only add if it's not just a container for headers
                child_headers = element.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6'])
                if not child_headers:
                    markdown_lines.append(text)
            
            processed_content.add(text)
        
        # Create final markdown content
        content = '\n\n'.join(markdown_lines)
        
        # Create preview from non-header content
        preview_text = ' '.join([line for line in markdown_lines if not line.startswith('#')])
        preview = preview_text[:150] + "..." if len(preview_text) > 150 else preview_text
        
        structured_data = {
            "title": title,
            "content": content,
            "content_type": content_type,
            "source_url": source_url,
            "preview": preview.strip()
        }
        
        print(f"✅ DEBUG: Successfully converted to markdown - {len(content)} chars")
        print(f"🎯 DEBUG: Title: {title}, Content type: {content_type}")
        
        return structured_data
        
    except Exception as e:
        print(f"❌ DEBUG: HTML to markdown conversion failed: {str(e)}")
        return {
            "title": "Conversion Error",
            "content": "Failed to convert HTML to markdown",
            "content_type": "other",
            "source_url": source_url,
            "preview": "Error processing content"
        }


DATA_DIR = Path(settings.data_dir)
DATA_DIR.mkdir(exist_ok=True)
OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

class HealthResponse(BaseModel):
    status: str
    timestamp: str
    version: str

class ScrapeRequest(BaseModel):
    url: str
    options: Optional[Dict[str, Any]] = {}

class ScrapeResponse(BaseModel):
    id: str
    url: str
    status: str
    data: Optional[Dict[str, Any]] = None
    created_at: str
    updated_at: str

class LinkExtractionRequest(BaseModel):
    url: HttpUrl = Field(..., description="URL to scrape and extract links from")

class LinkExtractionResponse(BaseModel):
    success: bool
    url: str
    final_url: Optional[str] = None
    status_code: Optional[int] = None
    links: List[str] = Field(default_factory=list, description="List of extracted links")
    count: int = Field(default=0, description="Total number of links found")
    content_type: Optional[str] = None
    error: Optional[str] = None

class UrlWithTag(BaseModel):
    url: str = Field(..., description="URL to scrape")
    tag: str = Field(default="other", description="Tag to classify the content")


class BasicScrapeRequest(BaseModel):
    urls: List[str] = Field(..., description="List of URLs to scrape")

class BasicContentItem(BaseModel):
    title: str
    description: str
    url: str
    structured_data: Optional[Dict[str, Any]] = None

class BasicScrapeResponse(BaseModel):
    success: bool
    results: List[BasicContentItem]

class ContentDisplayRequest(BaseModel):
    url: str = Field(..., description="URL to get structured data for")

class ContentDisplayResponse(BaseModel):
    success: bool
    url: str
    title: str
    content: str
    content_type: str
    preview: str
    scraped_at: Optional[str] = None
    error: Optional[str] = None

@app.get("/", response_model=HealthResponse)
async def root():
    return HealthResponse(
        status="healthy",
        timestamp=datetime.now().isoformat(),
        version="1.0.0"
    )

@app.get("/health", response_model=HealthResponse)
async def health_check():
    return HealthResponse(
        status="healthy",
        timestamp=datetime.now().isoformat(),
        version="1.0.0"
    )

@app.post("/extract-links-bundle", response_model=LinkExtractionResponse)
async def extract_links_bundle(request: LinkExtractionRequest):
    """
    Extract blog post links by intelligently parsing client bundle and extracting slug data.
    
    Smart approach for /blog pages:
    1. Loads the blog page and captures all JavaScript bundle content
    2. Searches for /blog/ patterns in compiled code (DevTools Sources approach)
    3. Identifies posts array with slug fields from compiled modules  
    4. Intelligently constructs full URLs as https://domain/blog/{slug}
    5. Adds /blog prefix automatically when detecting we're on a blog page
    6. Verifies navigation patterns with runtime router checks
    
    Args:
        request: LinkExtractionRequest containing the URL to scrape
        
    Returns:
        LinkExtractionResponse with list of extracted blog post links and metadata
    """
    url_str = str(request.url)
    
    # Perform the bundle parsing approach
    result = await extract_links_from_bundle(url_str)
    
    # Store the extraction result in a file for persistence
    job_id = f"bundle_{int(datetime.now().timestamp())}"
    job_file = DATA_DIR / f"{job_id}.json"
    
    job_data = {
        "id": job_id,
        "type": "bundle_parsing_extraction",
        "url": url_str,
        "result": result,
        "created_at": datetime.now().isoformat()
    }
    
    with open(job_file, "w") as f:
        json.dump(job_data, f, indent=2)
    
    # Ensure all required fields are present
    if "url" not in result:
        result["url"] = url_str
    
    return LinkExtractionResponse(**result)

@app.post("/extract-links-cached", response_model=LinkExtractionResponse)
async def extract_links_cached(request: LinkExtractionRequest):
    """
    Extract links with caching - checks if hostname folder exists in output directory,
    returns cached data if available, otherwise extracts new data and caches it.
    """
    url_str = str(request.url)
    parsed_url = urlparse(url_str)
    hostname = parsed_url.hostname
    
    if not hostname:
        return LinkExtractionResponse(
            success=False,
            url=url_str,
            error="Invalid URL - cannot extract hostname"
        )
    
    # Create hostname folder path
    hostname_folder = OUTPUT_DIR / hostname
    cache_file = hostname_folder / "links.json"
    
    # Check if cached data exists
    if cache_file.exists():
        try:
            with open(cache_file, "r") as f:
                cached_data = json.load(f)
                return LinkExtractionResponse(**cached_data)
        except (json.JSONDecodeError, KeyError):
            # If cache file is corrupt, continue to fresh extraction
            pass
    
    # Extract fresh data
    result = await extract_links_from_bundle(url_str)
    
    if result["success"]:
        # Create hostname folder and save data
        hostname_folder.mkdir(exist_ok=True)
        
        # Add metadata
        cached_result = {
            **result,
            "hostname": hostname,
            "cached_at": datetime.now().isoformat(),
            "cache_folder": str(hostname_folder)
        }
        
        # Save to cache
        with open(cache_file, "w") as f:
            json.dump(cached_result, f, indent=2)
    
    # Ensure all required fields are present
    if "url" not in result:
        result["url"] = url_str
    
    return LinkExtractionResponse(**result)


@app.post("/scrape-basic", response_model=BasicScrapeResponse)
async def scrape_basic(request: BasicScrapeRequest):
    """
    Enhanced scraping endpoint that extracts, cleans, and converts HTML to structured markdown.
    
    Process:
    1. Fetches HTML content from the provided URLs
    2. Cleans HTML by removing JavaScript, CSS, meta tags, empty elements, and all attributes
    3. Converts cleaned HTML to structured markdown using deterministic parsing:
       - Maps h1-h6 to markdown headers (# ## ###)
       - Converts strong/em to **bold**/*italic*
       - Detects content type from URL patterns
       - Extracts title from first h1 element
    4. Saves both cleaned HTML and structured data to files
    
    Returns cleaned content and structured markdown data instantly (no API calls).
    """
    try:
        import requests
        from bs4 import BeautifulSoup
        import time
        
        results = []
        
        # Store responses for saving HTML content
        url_responses = {}
        
        for url in request.urls:
            try:
                print(f"🔍 DEBUG: Fetching URL: {url}")
                
                # Fetch the HTML content
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
                }
                response = requests.get(url, headers=headers, timeout=10)
                response.raise_for_status()
                
                print(f"✅ DEBUG: Successfully fetched {len(response.text)} characters")
                
                # Parse and clean HTML content
                soup = BeautifulSoup(response.text, 'html.parser')
                
                # Count elements before cleaning
                script_count = len(soup.find_all('script'))
                style_count = len(soup.find_all('style'))
                link_count = len(soup.find_all('link'))
                meta_count = len(soup.find_all('meta'))
                
                print(f"🧹 DEBUG: Found {script_count} script tags, {style_count} style tags, {link_count} link tags, {meta_count} meta tags")
                
                # Remove script tags and their content
                for script in soup.find_all('script'):
                    script.decompose()
                
                # Remove style tags and their content  
                for style in soup.find_all('style'):
                    style.decompose()
                
                # Remove link tags with stylesheet references
                for link in soup.find_all('link', rel='stylesheet'):
                    link.decompose()
                
                # Remove meta tags, link tags (except content links), and other head elements
                for tag in soup.find_all(['meta', 'link', 'noscript']):
                    tag.decompose()
                
                # Remove all attributes from all tags
                attr_removed_count = 0
                for tag in soup.find_all():
                    attr_count = len(tag.attrs)
                    attr_removed_count += attr_count
                    tag.attrs.clear()
                
                print(f"🔧 DEBUG: Removed {attr_removed_count} total attributes")
                
                # Remove empty div tags (and other structural tags)
                empty_tags_removed = 0
                for tag_name in ['div', 'span', 'section', 'article']:
                    for tag in soup.find_all(tag_name):
                        # Check if tag is empty (no text content and no meaningful child tags)
                        text_content = tag.get_text(strip=True)
                        meaningful_children = tag.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'img', 'a', 'button', 'table', 'ul', 'ol', 'li'])
                        
                        if not text_content and not meaningful_children:
                            tag.decompose()
                            empty_tags_removed += 1
                        elif not text_content and not meaningful_children and tag_name in ['div', 'span']:
                            # For empty div/span tags, unwrap them to keep any nested content
                            tag.unwrap()
                
                print(f"🧽 DEBUG: Removed {empty_tags_removed} empty structural tags")
                
                # Get the body content or fallback to full content if no body
                body = soup.find('body')
                if body:
                    cleaned_html = str(body)
                    print(f"📄 DEBUG: Extracted body content: {len(cleaned_html)} characters")
                else:
                    cleaned_html = str(soup)
                    print(f"📄 DEBUG: No body found, using full content: {len(cleaned_html)} characters")
                
                # Show a preview of cleaned content
                preview = cleaned_html[:500] + "..." if len(cleaned_html) > 500 else cleaned_html
                print(f"👀 DEBUG: Preview of cleaned HTML:\n{preview}")
                
                url_responses[url] = cleaned_html
                
                # Process with HTML-to-markdown converter to get structured data
                print(f"🔄 DEBUG: Starting HTML-to-markdown conversion for {url}")
                structured_data = convert_html_to_markdown(cleaned_html, url)
                
                # Set empty title and description as requested
                results.append(BasicContentItem(
                    title="",
                    description="", 
                    url=url,
                    structured_data=structured_data
                ))
                
                # Small delay to be respectful
                time.sleep(0.5)
                
            except Exception as url_error:
                # If one URL fails, continue with others
                parsed_url = urlparse(url)
                path_segments = parsed_url.path.split('/') 
                slug = path_segments[-1] if path_segments[-1] else path_segments[-2] if len(path_segments) > 1 else "home"
                
                results.append(BasicContentItem(
                    title=f"Error loading {slug}",
                    description=f"Failed to scrape content from this URL: {str(url_error)}",
                    url=url
                ))
        
        # Save each scraped content to individual files in hostname folder
        if results:
            first_url = urlparse(request.urls[0])
            hostname = first_url.hostname
            
            if hostname:
                hostname_folder = OUTPUT_DIR / hostname
                hostname_folder.mkdir(exist_ok=True)
                
                # Save each link's content in separate files
                for i, result in enumerate(results):
                    # Create filename from URL slug
                    parsed = urlparse(result.url)
                    path_segments = parsed.path.split('/')
                    slug = path_segments[-1] if path_segments[-1] else path_segments[-2] if len(path_segments) > 1 else "home"
                    
                    # Clean slug for filename
                    clean_slug = "".join(c for c in slug if c.isalnum() or c in ('-', '_')).rstrip()
                    if not clean_slug:
                        clean_slug = f"page_{i}"
                    
                    # Create individual file for this link
                    content_file = hostname_folder / f"{clean_slug}.json"
                    scraped_data = {
                        "scraped_at": datetime.now().isoformat(),
                        "url": result.url,
                        "title": result.title,
                        "description": result.description,
                        "cleaned_html": url_responses.get(result.url, ""),
                        "structured_data": result.structured_data
                    }
                    
                    with open(content_file, "w", encoding='utf-8') as f:
                        json.dump(scraped_data, f, indent=2, ensure_ascii=False)

        return BasicScrapeResponse(
            success=True,
            results=results
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error scraping content: {str(e)}")

@app.post("/get-content", response_model=ContentDisplayResponse)
async def get_content(request: ContentDisplayRequest):
    """
    Get structured content data for display in frontend.
    
    This endpoint looks for previously scraped content and returns the structured
    markdown data for display when user clicks on a content box.
    """
    try:
        print(f"🔍 DEBUG: Getting content for URL: {request.url}")
        
        # Parse URL to get hostname and create file path
        parsed_url = urlparse(request.url)
        hostname = parsed_url.hostname
        
        if not hostname:
            raise HTTPException(status_code=400, detail="Invalid URL - cannot extract hostname")
        
        # Create expected file path
        hostname_folder = OUTPUT_DIR / hostname
        
        # Try to find the file by looking for URL slug
        path_segments = parsed_url.path.split('/')
        slug = path_segments[-1] if path_segments[-1] else path_segments[-2] if len(path_segments) > 1 else "home"
        clean_slug = "".join(c for c in slug if c.isalnum() or c in ('-', '_')).rstrip()
        
        if not clean_slug:
            clean_slug = "page"
            
        content_file = hostname_folder / f"{clean_slug}.json"
        
        print(f"🔍 DEBUG: Looking for file: {content_file}")
        
        # Check if file exists
        if not content_file.exists():
            print(f"❌ DEBUG: File not found: {content_file}")
            # List available files for debugging
            if hostname_folder.exists():
                available_files = list(hostname_folder.glob("*.json"))
                print(f"🔍 DEBUG: Available files: {[f.name for f in available_files]}")
            
            return ContentDisplayResponse(
                success=False,
                url=request.url,
                title="Content Not Found",
                content="This content has not been scraped yet. Please scrape it first using the /scrape-basic endpoint.",
                content_type="other",
                preview="Content not available",
                error="File not found"
            )
        
        # Read and parse the file
        try:
            with open(content_file, "r", encoding='utf-8') as f:
                data = json.load(f)
            
            print(f"✅ DEBUG: Successfully loaded data from file")
            
            # Extract structured data
            structured_data = data.get("structured_data", {})
            
            if not structured_data:
                print(f"❌ DEBUG: No structured data found in file")
                return ContentDisplayResponse(
                    success=False,
                    url=request.url,
                    title="No Structured Data",
                    content="Structured data not found in the saved file.",
                    content_type="other", 
                    preview="Data not available",
                    error="No structured data"
                )
            
            # Return the structured content
            return ContentDisplayResponse(
                success=True,
                url=request.url,
                title=structured_data.get("title", "Untitled"),
                content=structured_data.get("content", "No content available"),
                content_type=structured_data.get("content_type", "other"),
                preview=structured_data.get("preview", "No preview available"),
                scraped_at=data.get("scraped_at", "Unknown")
            )
            
        except (json.JSONDecodeError, KeyError) as e:
            print(f"❌ DEBUG: Error parsing file: {str(e)}")
            return ContentDisplayResponse(
                success=False,
                url=request.url,
                title="Parse Error",
                content="Error reading the saved content file.",
                content_type="other",
                preview="Error reading data",
                error=f"Parse error: {str(e)}"
            )
        
    except Exception as e:
        print(f"❌ DEBUG: Get content failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error getting content: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=settings.host, port=settings.port, reload=settings.debug)