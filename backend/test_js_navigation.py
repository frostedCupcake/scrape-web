import asyncio
import json
from playwright.async_api import async_playwright

async def test_javascript_navigation_detection():
    """Test script to show all the data we can extract from Playwright for JavaScript navigation"""
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        print("🔍 Testing JavaScript Navigation Detection on http://13.127.180.168:3000/dynamic")
        
        try:
            await page.goto("http://13.127.180.168:3000/dynamic", wait_until='networkidle', timeout=30000)
            await page.wait_for_timeout(3000)
            
            # 1. Extract all buttons and their properties
            print("\n=== 1. BUTTON ANALYSIS ===")
            buttons = await page.eval_on_selector_all(
                'button', 
                '''buttons => buttons.map(btn => ({
                    text: btn.textContent?.trim(),
                    id: btn.id,
                    className: btn.className,
                    onclick: btn.onclick?.toString(),
                    hasClickListener: btn.onclick !== null,
                    dataAttributes: Object.fromEntries([...btn.attributes].filter(attr => attr.name.startsWith('data-')).map(attr => [attr.name, attr.value]))
                }))'''
            )
            
            for i, button in enumerate(buttons):
                print(f"  Button {i+1}:")
                print(f"    Text: {button['text']}")
                print(f"    Has Click Handler: {button['hasClickListener']}")
                print(f"    Class: {button['className']}")
                if button['onclick']:
                    print(f"    OnClick: {button['onclick']}")
            
            # 2. Extract all links (for comparison)
            print("\n=== 2. LINK ANALYSIS ===")
            links = await page.eval_on_selector_all(
                'a[href]', 
                '''links => links.map(link => ({
                    text: link.textContent?.trim(),
                    href: link.href,
                    target: link.target,
                    className: link.className
                }))'''
            )
            
            for i, link in enumerate(links):
                print(f"  Link {i+1}:")
                print(f"    Text: {link['text']}")
                print(f"    Href: {link['href']}")
                print(f"    Target: {link['target']}")
                print(f"    Class: {link['className']}")
            
            # 3. Extract JavaScript code that might contain navigation URLs
            print("\n=== 3. JAVASCRIPT CODE ANALYSIS ===")
            scripts = await page.eval_on_selector_all('script', 'scripts => scripts.map(s => s.textContent)')
            
            router_push_patterns = []
            for script in scripts:
                if script and 'router.push' in script:
                    # Find router.push calls
                    import re
                    matches = re.findall(r'router\.push\([\'"]([^\'"]+)[\'"]', script)
                    router_push_patterns.extend(matches)
            
            print(f"  Found {len(router_push_patterns)} router.push patterns:")
            for pattern in set(router_push_patterns):
                print(f"    • {pattern}")
            
            # 4. Intercept navigation attempts by monkey-patching
            print("\n=== 4. NAVIGATION INTERCEPTION ===")
            navigation_attempts = []
            
            # Set up navigation interception
            await page.evaluate('''
                window.navigationAttempts = [];
                
                // Intercept router.push if Next.js router exists
                if (window.next?.router?.push) {
                    const originalPush = window.next.router.push;
                    window.next.router.push = function(url, ...args) {
                        window.navigationAttempts.push({type: 'router.push', url: url});
                        return originalPush.call(this, url, ...args);
                    };
                }
                
                // Intercept history API
                const originalPushState = history.pushState;
                history.pushState = function(state, title, url) {
                    window.navigationAttempts.push({type: 'history.pushState', url: url});
                    return originalPushState.call(this, state, title, url);
                };
                
                // Intercept window.location changes
                let locationUrl = window.location.href;
                Object.defineProperty(window, 'location', {
                    get: () => ({ 
                        ...window.location,
                        href: locationUrl 
                    }),
                    set: (url) => {
                        window.navigationAttempts.push({type: 'window.location', url: url});
                        locationUrl = url;
                    }
                });
            ''')
            
            # 5. Try clicking the router.push button and capture navigation
            print("\n=== 5. INTERACTIVE CLICKING TEST ===")
            try:
                # Find the router push button
                router_button = page.locator('button:has-text("Router Push to Google")')
                if await router_button.count() > 0:
                    print("  Found Router Push button, clicking...")
                    
                    # Click the button (this should trigger router.push)
                    await router_button.click()
                    await page.wait_for_timeout(2000)
                    
                    # Get captured navigation attempts
                    captured = await page.evaluate('window.navigationAttempts || []')
                    print(f"  Captured {len(captured)} navigation attempts:")
                    for attempt in captured:
                        print(f"    • Type: {attempt['type']}, URL: {attempt['url']}")
                        
                else:
                    print("  Router Push button not found")
                    
            except Exception as e:
                print(f"  Click test failed: {e}")
            
            # 6. Extract React component props (if accessible)
            print("\n=== 6. REACT COMPONENT ANALYSIS ===")
            try:
                # Try to access React internals
                react_data = await page.evaluate('''
                    (() => {
                        const buttons = document.querySelectorAll('button');
                        const reactData = [];
                        buttons.forEach(btn => {
                            // Try to get React fiber data
                            const fiber = btn._reactInternalFiber || btn._reactInternals;
                            if (fiber && fiber.memoizedProps) {
                                reactData.push({
                                    text: btn.textContent?.trim(),
                                    props: fiber.memoizedProps
                                });
                            }
                        });
                        return reactData;
                    })()
                ''')
                
                if react_data:
                    print("  React component data found:")
                    for data in react_data:
                        print(f"    • {data['text']}: {json.dumps(data['props'], default=str)}")
                else:
                    print("  No React component data accessible")
                    
            except Exception as e:
                print(f"  React analysis failed: {e}")
            
            # 7. Network request monitoring
            print("\n=== 7. NETWORK MONITORING ===")
            network_requests = []
            
            def handle_request(request):
                network_requests.append({
                    'url': request.url,
                    'method': request.method,
                    'headers': dict(request.headers)
                })
            
            page.on('request', handle_request)
            
            # Trigger some activity
            await page.reload()
            await page.wait_for_timeout(3000)
            
            print(f"  Captured {len(network_requests)} network requests")
            for req in network_requests[:5]:  # Show first 5
                print(f"    • {req['method']} {req['url']}")
                
        except Exception as e:
            print(f"Error: {e}")
            
        finally:
            await browser.close()

if __name__ == "__main__":
    asyncio.run(test_javascript_navigation_detection())