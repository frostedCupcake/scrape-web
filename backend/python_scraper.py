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

class PythonScraper:
    def __init__(self, base_url: str, output_dir: str = "scraped_output", max_depth: int = 2):
        self.base_url = base_url.rstrip('/')
        self.output_dir = Path(output_dir)
        self.max_depth = max_depth
        self.visited_urls: Set[str] = set()
        self.downloaded_files: List[Dict[str, Any]] = []
        self.session = None
        
        # Create output directory
        self.output_dir.mkdir(exist_ok=True)
        
    async def __aenter__(self):
        """Async context manager entry"""
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30),
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
        )
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        if self.session:
            await self.session.close()

    def is_same_domain(self, url: str) -> bool:
        """Check if URL is from the same domain as base_url"""
        base_domain = urlparse(self.base_url).netloc
        url_domain = urlparse(url).netloc
        return base_domain == url_domain

    def clean_url(self, url: str) -> str:
        """Clean URL by removing fragments and unnecessary parts"""
        parsed = urlparse(url)
        return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, parsed.query, ''))

    def get_filename_from_url(self, url: str) -> str:
        """Generate filename from URL"""
        parsed = urlparse(url)
        path = parsed.path.strip('/')
        
        if not path or path.endswith('/'):
            return 'index.html'
            
        # If no extension, assume HTML
        if '.' not in os.path.basename(path):
            return f"{path.replace('/', '_')}.html"
            
        return path.replace('/', '_')

    async def download_file(self, url: str, depth: int = 0) -> Dict[str, Any]:
        """Download a single file"""
        if url in self.visited_urls or depth > self.max_depth:
            return {"skipped": True, "reason": "already_visited_or_max_depth"}
            
        self.visited_urls.add(url)
        
        try:
            print(f"Downloading (depth {depth}): {url}")
            
            async with self.session.get(url) as response:
                if response.status != 200:
                    return {"error": f"HTTP {response.status}", "url": url}
                
                content = await response.read()
                content_type = response.headers.get('content-type', '').lower()
                
                # Generate filename
                filename = self.get_filename_from_url(url)
                file_path = self.output_dir / filename
                
                # Save file
                async with aiofiles.open(file_path, 'wb') as f:
                    await f.write(content)
                
                result = {
                    "url": url,
                    "filename": filename,
                    "size": len(content),
                    "content_type": content_type,
                    "depth": depth,
                    "status": "success"
                }
                
                # If it's HTML, extract more links
                if 'html' in content_type and depth < self.max_depth:
                    html_content = content.decode('utf-8', errors='ignore')
                    links = await self.extract_links_from_html(html_content, url)
                    result["links_found"] = len(links)
                    
                    # Download linked resources (next depth)
                    for link in links[:20]:  # Limit to prevent explosion
                        if self.is_same_domain(link):
                            await self.download_file(link, depth + 1)
                
                self.downloaded_files.append(result)
                return result
                
        except Exception as e:
            error_result = {"error": str(e), "url": url, "depth": depth}
            print(f"Error downloading {url}: {e}")
            return error_result

    async def extract_links_from_html(self, html_content: str, base_url: str) -> List[str]:
        """Extract links from HTML content"""
        soup = BeautifulSoup(html_content, 'html.parser')
        links = set()
        
        # Extract href links
        for tag in soup.find_all(['a', 'link'], href=True):
            href = tag['href'].strip()
            if href and not href.startswith('#') and not href.startswith('mailto:'):
                absolute_url = urljoin(base_url, href)
                links.add(self.clean_url(absolute_url))
        
        # Extract src links (images, scripts, etc.)
        for tag in soup.find_all(['img', 'script'], src=True):
            src = tag['src'].strip() 
            if src:
                absolute_url = urljoin(base_url, src)
                links.add(self.clean_url(absolute_url))
                
        return list(links)

    async def scrape(self) -> Dict[str, Any]:
        """Main scraping method"""
        print(f"Starting scrape of: {self.base_url}")
        print(f"Output directory: {self.output_dir}")
        
        start_time = datetime.now()
        
        # Start with the base URL
        await self.download_file(self.base_url, depth=0)
        
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        
        # Save results summary
        summary = {
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(), 
            "duration_seconds": duration,
            "base_url": self.base_url,
            "total_files": len(self.downloaded_files),
            "output_directory": str(self.output_dir),
            "files": self.downloaded_files
        }
        
        # Save summary to JSON
        summary_file = self.output_dir / "scrape_summary.json"
        async with aiofiles.open(summary_file, 'w') as f:
            await f.write(json.dumps(summary, indent=2))
            
        print(f"Scraping completed! Downloaded {len(self.downloaded_files)} files in {duration:.2f} seconds")
        print(f"Summary saved to: {summary_file}")
        
        return summary


# Usage function
async def scrape_website(url: str, output_dir: str = "scraped_output", max_depth: int = 2):
    """Simple function to scrape a website"""
    async with PythonScraper(url, output_dir, max_depth) as scraper:
        return await scraper.scrape()


# Test function
async def test_scraper():
    """Test the scraper"""
    result = await scrape_website(
        url="https://quill.co/blog", 
        output_dir="python_scraped",
        max_depth=1
    )
    
    print(f"Scraped {result['total_files']} files")
    return result

if __name__ == "__main__":
    # Run test
    asyncio.run(test_scraper())