import asyncio
import aiohttp
import aiofiles
import os
from pathlib import Path
from urllib.parse import urljoin, urlparse, urlunparse
from bs4 import BeautifulSoup
import re
from typing import Set, List, Dict, Any
import json
from datetime import datetime

class AdvancedScraper:
    def __init__(self, base_url: str, output_dir: str = "advanced_scraped", max_depth: int = 3):
        self.base_url = base_url.rstrip('/')
        self.parsed_base = urlparse(self.base_url)
        self.output_dir = Path(output_dir)
        self.max_depth = max_depth
        self.visited_urls: Set[str] = set()
        self.discovered_urls: Set[str] = set()
        self.downloaded_files: List[Dict[str, Any]] = []
        self.session = None
        
        # Create output directories
        self.output_dir.mkdir(exist_ok=True)
        (self.output_dir / "css").mkdir(exist_ok=True)
        (self.output_dir / "js").mkdir(exist_ok=True)
        (self.output_dir / "images").mkdir(exist_ok=True)
        
    async def __aenter__(self):
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30),
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
        )
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()

    def is_same_domain(self, url: str) -> bool:
        """Check if URL is from same domain"""
        try:
            parsed = urlparse(url)
            return parsed.netloc == self.parsed_base.netloc
        except:
            return False

    def clean_url(self, url: str) -> str:
        """Clean URL by removing fragments"""
        parsed = urlparse(url)
        return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, parsed.query, ''))

    def get_file_type_and_path(self, url: str) -> tuple:
        """Determine file type and appropriate path"""
        parsed = urlparse(url)
        path = parsed.path.strip('/')
        
        if not path or path.endswith('/'):
            return 'html', 'index.html'
            
        if path.endswith('.css'):
            return 'css', f"css/{os.path.basename(path)}"
        elif path.endswith('.js'):
            return 'js', f"js/{os.path.basename(path)}"
        elif any(path.endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.gif', '.svg', '.ico', '.webp']):
            return 'image', f"images/{os.path.basename(path)}"
        elif '.' not in os.path.basename(path):
            # No extension, assume HTML
            return 'html', f"{path.replace('/', '_')}.html"
        else:
            return 'other', path.replace('/', '_')

    def extract_all_links(self, html_content: str, base_url: str) -> List[str]:
        """Extract ALL types of links from HTML - like node-website-scraper"""
        soup = BeautifulSoup(html_content, 'html.parser')
        links = set()
        
        # 1. All anchor tags with href
        for tag in soup.find_all('a', href=True):
            href = tag['href'].strip()
            if href and not href.startswith('#') and not href.startswith('mailto:') and not href.startswith('tel:'):
                absolute_url = urljoin(base_url, href)
                links.add(self.clean_url(absolute_url))
        
        # 2. All link tags (CSS)
        for tag in soup.find_all('link', href=True):
            href = tag['href'].strip()
            if href:
                absolute_url = urljoin(base_url, href)
                links.add(self.clean_url(absolute_url))
        
        # 3. All script tags (JS)
        for tag in soup.find_all('script', src=True):
            src = tag['src'].strip()
            if src:
                absolute_url = urljoin(base_url, src)
                links.add(self.clean_url(absolute_url))
        
        # 4. All img tags
        for tag in soup.find_all('img', src=True):
            src = tag['src'].strip()
            if src:
                absolute_url = urljoin(base_url, src)
                links.add(self.clean_url(absolute_url))
                
        # 5. Background images in style attributes
        for tag in soup.find_all(attrs={'style': True}):
            style = tag['style']
            urls = re.findall(r'url\(["\']?([^"\']+)["\']?\)', style)
            for url in urls:
                absolute_url = urljoin(base_url, url.strip())
                links.add(self.clean_url(absolute_url))
        
        return list(links)

    def should_download(self, url: str) -> bool:
        """Determine if we should download this URL"""
        # Only same domain
        if not self.is_same_domain(url):
            return False
            
        # Skip if already visited
        if url in self.visited_urls:
            return False
            
        # Skip certain patterns
        parsed = urlparse(url)
        path = parsed.path.lower()
        
        # Skip common non-content files
        skip_patterns = [
            '/_next/static/chunks/webpack',
            '/_next/static/chunks/polyfills',
            '.map', '.xml', '.txt'
        ]
        
        return not any(pattern in path for pattern in skip_patterns)

    def is_html_content(self, url: str, content_type: str) -> bool:
        """Check if content is HTML"""
        if 'html' in content_type.lower():
            return True
        # If no extension and not a known file type, assume HTML
        parsed = urlparse(url)
        path = parsed.path
        return '.' not in os.path.basename(path) or path.endswith('/')

    async def download_single_file(self, url: str, depth: int) -> Dict[str, Any]:
        """Download a single file"""
        if not self.should_download(url) or depth > self.max_depth:
            return {"skipped": True, "url": url, "reason": "filtered_or_max_depth"}
        
        self.visited_urls.add(url)
        
        try:
            print(f"[Depth {depth}] Downloading: {url}")
            
            async with self.session.get(url) as response:
                if response.status != 200:
                    return {"error": f"HTTP {response.status}", "url": url}
                
                content = await response.read()
                content_type = response.headers.get('content-type', '').lower()
                
                # Determine file type and path
                file_type, relative_path = self.get_file_type_and_path(url)
                file_path = self.output_dir / relative_path
                
                # Create directory if needed
                file_path.parent.mkdir(parents=True, exist_ok=True)
                
                # Save file
                async with aiofiles.open(file_path, 'wb') as f:
                    await f.write(content)
                
                result = {
                    "url": url,
                    "filename": relative_path,
                    "file_type": file_type,
                    "size": len(content),
                    "content_type": content_type,
                    "depth": depth,
                    "status": "success"
                }
                
                # If HTML, extract more links for next depth
                new_links = []
                if self.is_html_content(url, content_type) and depth < self.max_depth:
                    try:
                        html_content = content.decode('utf-8', errors='ignore')
                        extracted_links = self.extract_all_links(html_content, url)
                        
                        # Filter and add to discovered URLs
                        for link in extracted_links:
                            if link not in self.visited_urls and link not in self.discovered_urls:
                                self.discovered_urls.add(link)
                                new_links.append(link)
                        
                        result["links_extracted"] = len(new_links)
                        
                    except Exception as e:
                        print(f"Error extracting links from {url}: {e}")
                        result["link_extraction_error"] = str(e)
                
                self.downloaded_files.append(result)
                return result
                
        except Exception as e:
            error_result = {"error": str(e), "url": url, "depth": depth}
            print(f"Error downloading {url}: {e}")
            return error_result

    async def scrape_recursive(self) -> Dict[str, Any]:
        """Main recursive scraping method - like node-website-scraper"""
        print(f"Starting advanced scrape of: {self.base_url}")
        print(f"Output directory: {self.output_dir}")
        print(f"Max depth: {self.max_depth}")
        
        start_time = datetime.now()
        
        # Start with base URL
        self.discovered_urls.add(self.base_url)
        
        # Process URLs by depth level
        for current_depth in range(self.max_depth + 1):
            urls_at_depth = [url for url in self.discovered_urls if url not in self.visited_urls]
            
            if not urls_at_depth:
                break
                
            print(f"\n--- Processing depth {current_depth}: {len(urls_at_depth)} URLs ---")
            
            # Download all URLs at current depth
            tasks = [self.download_single_file(url, current_depth) for url in urls_at_depth[:50]]  # Limit per depth
            await asyncio.gather(*tasks)
        
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        
        # Generate summary
        summary = {
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
            "duration_seconds": duration,
            "base_url": self.base_url,
            "max_depth": self.max_depth,
            "total_files": len(self.downloaded_files),
            "total_discovered": len(self.discovered_urls),
            "output_directory": str(self.output_dir),
            "files_by_type": self._get_files_by_type(),
            "files": self.downloaded_files
        }
        
        # Save summary
        summary_file = self.output_dir / "scrape_summary.json"
        async with aiofiles.open(summary_file, 'w') as f:
            await f.write(json.dumps(summary, indent=2))
        
        print(f"\nScraping completed!")
        print(f"Downloaded: {len(self.downloaded_files)} files")
        print(f"Discovered: {len(self.discovered_urls)} URLs")
        print(f"Duration: {duration:.2f} seconds")
        print(f"Summary saved to: {summary_file}")
        
        return summary

    def _get_files_by_type(self):
        """Get count of files by type"""
        counts = {}
        for file_info in self.downloaded_files:
            file_type = file_info.get('file_type', 'unknown')
            counts[file_type] = counts.get(file_type, 0) + 1
        return counts


# Usage functions
async def advanced_scrape_website(url: str, output_dir: str = "advanced_scraped", max_depth: int = 3):
    """Advanced scraping function like node-website-scraper"""
    async with AdvancedScraper(url, output_dir, max_depth) as scraper:
        return await scraper.scrape_recursive()


async def extract_links_only(url: str) -> Dict[str, Any]:
    """Just extract links without downloading - fast version"""
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url) as response:
                if response.status == 200:
                    content = await response.text()
                    soup = BeautifulSoup(content, 'html.parser')
                    
                    links = set()
                    for tag in soup.find_all(['a', 'link', 'script', 'img'], {'href': True, 'src': True}):
                        link = tag.get('href') or tag.get('src')
                        if link:
                            absolute_url = urljoin(url, link.strip())
                            links.add(absolute_url)
                    
                    return {
                        "success": True,
                        "url": url,
                        "links": sorted(list(links)),
                        "count": len(links)
                    }
        except Exception as e:
            return {"success": False, "error": str(e), "links": [], "count": 0}


# Test function
if __name__ == "__main__":
    async def test():
        result = await advanced_scrape_website("https://quill.co/blog", max_depth=2)
        print(f"Final result: {result['total_files']} files downloaded")
    
    asyncio.run(test())