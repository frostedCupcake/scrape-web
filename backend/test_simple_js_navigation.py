import asyncio
import json
from playwright.async_api import async_playwright

async def test_simple_js_detection():
    """Simplified test focusing on practical JavaScript navigation detection"""
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        print("🔍 Testing Practical JavaScript Navigation Detection")
        print("Target: http://13.127.180.168:3000/dynamic\n")
        
        try:
            await page.goto("http://13.127.180.168:3000/dynamic", wait_until='networkidle', timeout=30000)
            await page.wait_for_timeout(3000)
            
            # Method 1: Click buttons and track navigation
            print("=== METHOD 1: CLICK AND TRACK NAVIGATION ===")
            original_url = page.url
            print(f"Starting URL: {original_url}")
            
            # Find the router button
            router_button = page.locator('button:has-text("Router Push to Google")')
            if await router_button.count() > 0:
                print("✓ Found Router Push button")
                
                # Set up page navigation listener
                navigation_urls = []
                
                def handle_navigation(frame):
                    navigation_urls.append(frame.url)
                    
                page.on('framenavigated', handle_navigation)
                
                try:
                    # Click and see if navigation occurs
                    await router_button.click()
                    await page.wait_for_timeout(3000)  # Wait for navigation
                    
                    current_url = page.url
                    print(f"After click URL: {current_url}")
                    
                    if current_url != original_url:
                        print(f"✓ Navigation detected: {original_url} → {current_url}")
                    else:
                        print("✗ No navigation detected")
                        
                    if navigation_urls:
                        print(f"✓ Frame navigations: {navigation_urls}")
                        
                except Exception as e:
                    print(f"✗ Click failed: {e}")
            else:
                print("✗ Router Push button not found")
            
            # Method 2: Extract JavaScript event handlers
            print(f"\n=== METHOD 2: JAVASCRIPT EVENT HANDLER ANALYSIS ===")
            
            # Get all buttons with their event info
            button_data = await page.evaluate('''
                () => {
                    const buttons = document.querySelectorAll('button');
                    return Array.from(buttons).map(btn => {
                        const rect = btn.getBoundingClientRect();
                        return {
                            text: btn.textContent?.trim(),
                            hasClickHandler: !!btn.onclick,
                            visible: rect.width > 0 && rect.height > 0,
                            // Try to get React props if available
                            reactKey: btn._reactInternalFiber?.key || btn._reactInternals?.key,
                        };
                    });
                }
            ''')
            
            for i, btn in enumerate(button_data):
                print(f"Button {i+1}: '{btn['text']}'")
                print(f"  Has Click Handler: {btn['hasClickHandler']}")
                print(f"  Visible: {btn['visible']}")
                if btn['reactKey']:
                    print(f"  React Key: {btn['reactKey']}")
            
            # Method 3: Search for URLs in page source/scripts
            print(f"\n=== METHOD 3: URL PATTERN EXTRACTION ===")
            
            # Get page content and search for google.com references
            page_content = await page.content()
            
            import re
            # Search for google.com URLs in various contexts
            patterns = [
                r'["\']https?://[^"\']*google\.com[^"\']*["\']',  # Quoted URLs
                r'router\.push\(["\']([^"\']+)["\']',              # router.push calls
                r'window\.open\(["\']([^"\']+)["\']',              # window.open calls
                r'location\.href\s*=\s*["\']([^"\']+)["\']',      # location.href assignments
            ]
            
            found_urls = set()
            for pattern in patterns:
                matches = re.findall(pattern, page_content, re.IGNORECASE)
                for match in matches:
                    if isinstance(match, tuple):
                        found_urls.update(match)
                    else:
                        found_urls.add(match)
            
            google_urls = [url for url in found_urls if 'google.com' in url.lower()]
            print(f"Found {len(google_urls)} Google URLs in source:")
            for url in google_urls:
                print(f"  • {url}")
            
            # Method 4: Analyze network requests after interactions
            print(f"\n=== METHOD 4: NETWORK REQUEST MONITORING ===")
            
            requests_log = []
            def log_request(request):
                if 'google.com' in request.url:
                    requests_log.append({
                        'url': request.url,
                        'method': request.method
                    })
            
            page.on('request', log_request)
            
            # Try clicking again to see network activity
            if await router_button.count() > 0:
                await page.goto("http://13.127.180.168:3000/dynamic")  # Reset
                await page.wait_for_timeout(2000)
                await router_button.click()
                await page.wait_for_timeout(3000)
                
            print(f"Google-related network requests: {len(requests_log)}")
            for req in requests_log:
                print(f"  • {req['method']} {req['url']}")
            
            # Method 5: JavaScript execution tracing
            print(f"\n=== METHOD 5: JAVASCRIPT EXECUTION TRACING ===")
            
            # Override console.log to capture any debug info
            console_logs = []
            page.on('console', lambda msg: console_logs.append(str(msg.text)))
            
            # Inject tracing script
            await page.evaluate('''
                // Override router methods if they exist
                if (typeof window !== 'undefined') {
                    const originalLog = console.log;
                    console.log = (...args) => {
                        originalLog('TRACED:', ...args);
                    };
                    
                    // Try to intercept Next.js router
                    if (window.next && window.next.router) {
                        const originalPush = window.next.router.push;
                        window.next.router.push = function(url) {
                            console.log('Router push intercepted:', url);
                            return originalPush.call(this, url);
                        };
                    }
                }
            ''')
            
            # Click again with tracing active
            await page.goto("http://13.127.180.168:3000/dynamic")
            await page.wait_for_timeout(2000)
            
            if await router_button.count() > 0:
                await router_button.click()
                await page.wait_for_timeout(2000)
            
            print(f"Console logs captured: {len(console_logs)}")
            for log in console_logs[-5:]:  # Show last 5
                print(f"  • {log}")
                
        except Exception as e:
            print(f"Error: {e}")
            
        finally:
            await browser.close()

if __name__ == "__main__":
    asyncio.run(test_simple_js_detection())