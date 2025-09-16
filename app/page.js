'use client';

import { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import toast from 'react-hot-toast';

export default function Home() {
  const [url, setUrl] = useState('');
  const [links, setLinks] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [stats, setStats] = useState(null);
  const [cacheInfo, setCacheInfo] = useState(null);
  const [viewMode, setViewMode] = useState('links'); // 'links' or 'content'
  const [scrapingGroups, setScrapingGroups] = useState({});
  const [scrapedContent, setScrapedContent] = useState({});
  const [selectedContent, setSelectedContent] = useState(null);
  const [showModal, setShowModal] = useState(false);

  const groupLinks = (links) => {
    const groups = {};
    const ungrouped = [];

    links.forEach(link => {
      try {
        const url = new URL(link);
        const pathSegments = url.pathname.split('/').filter(segment => segment.length > 0);
        
        if (pathSegments.length === 0) {
          // Root domain
          const groupName = 'Home';
          if (!groups[groupName]) groups[groupName] = [];
          groups[groupName].push(link);
        } else if (pathSegments.length >= 1) {
          // Use first path segment as group name
          const firstSegment = pathSegments[0];
          const groupName = firstSegment.charAt(0).toUpperCase() + firstSegment.slice(1);
          
          // Only group if there will be multiple items in this category
          const sameGroupLinks = links.filter(l => {
            try {
              const testUrl = new URL(l);
              const testSegments = testUrl.pathname.split('/').filter(s => s.length > 0);
              return testSegments.length > 0 && testSegments[0] === firstSegment;
            } catch {
              return false;
            }
          });
          
          if (sameGroupLinks.length > 1) {
            if (!groups[groupName]) groups[groupName] = [];
            groups[groupName].push(link);
          } else {
            ungrouped.push(link);
          }
        } else {
          ungrouped.push(link);
        }
      } catch {
        ungrouped.push(link);
      }
    });

    // Add ungrouped links as "Other" if there are any
    if (ungrouped.length > 0) {
      groups['Other'] = ungrouped;
    }

    return groups;
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    
    if (!url) {
      setError('Please enter a URL');
      return;
    }

    setLoading(true);
    setError('');
    setLinks([]);
    setStats(null);
    setScrapedContent({}); // Clear previous scraped content
    
    // Show progress toast
    const toastId = toast.loading('Scraping in progress, please wait...');

    try {
      const response = await fetch('http://13.127.180.168:8050/extract-links-cached', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ url }),
      });

      const data = await response.json();

      if (data.success) {
        setLinks(data.links);
        setStats({
          count: data.count,
          domain: new URL(data.url).hostname,
        });
        setCacheInfo({
          hostname: data.hostname,
          cached: !!data.cached_at,
          cachedAt: data.cached_at
        });

        // Auto-trigger scraping for all links
        await autoScrapeAllLinks(data.links);
        
        // Update toast to success
        toast.success('Scraping completed successfully!', { id: toastId });
      } else {
        toast.error(data.error || 'Failed to extract links', { id: toastId });
        setError(data.error || 'Failed to extract links');
      }
    } catch (err) {
      toast.error('Connection failed', { id: toastId });
      setError('Connection failed');
    } finally {
      setLoading(false);
    }
  };

  const autoScrapeAllLinks = async (links) => {
    // Group links by their base path (same logic as in the UI)
    const groupedByBase = {};
    links.forEach(link => {
      const url = new URL(link);
      const pathSegments = url.pathname.split('/').filter(Boolean);
      const basePath = pathSegments.length > 1 ? `${url.origin}/${pathSegments[0]}/` : `${url.origin}/`;
      
      if (!groupedByBase[basePath]) {
        groupedByBase[basePath] = [];
      }
      groupedByBase[basePath].push(link);
    });

    // First, try to load cached content for all groups
    const cachedResults = {};
    const uncachedGroups = {};
    
    for (const [basePath, groupLinks] of Object.entries(groupedByBase)) {
      try {
        // Check for cached content using the get-content API
        const cachedContent = [];
        const uncachedLinks = [];
        
        for (const link of groupLinks) {
          try {
            const response = await fetch('http://13.127.180.168:8050/get-content', {
              method: 'POST',
              headers: {
                'Content-Type': 'application/json',
              },
              body: JSON.stringify({ url: link }),
            });
            
            if (response.ok) {
              const data = await response.json();
              console.log(`Cache check for ${link}:`, data); // Debug log
              
              if (data.success && (data.title || data.content)) {
                // The API returns data directly, not nested under 'content'
                const cacheData = data;
                
                // Additional validation for cache data
                if (!cacheData || ((!cacheData.title || cacheData.title.trim() === '') && (!cacheData.content || cacheData.content.trim() === ''))) {
                  console.log(`Empty cache data for ${link}, treating as uncached`);
                  uncachedLinks.push(link);
                } else {
                  const transformedContent = {
                    url: link, // Use the original link URL
                    title: cacheData.title && cacheData.title.trim() !== '' ? cacheData.title.trim() : 'Untitled',
                    description: cacheData.preview && cacheData.preview.trim() !== '' 
                      ? cacheData.preview.trim()
                      : cacheData.content && cacheData.content.trim() !== '' 
                        ? cacheData.content.trim().substring(0, 200) + '...' 
                        : 'No description available',
                    content: cacheData.content || '',
                    content_type: cacheData.content_type || 'other'
                  };
                  
                  console.log(`Transformed cache content for ${link}:`, transformedContent);
                  cachedContent.push(transformedContent);
                }
              } else {
                console.log(`No valid cache content for ${link}`);
                uncachedLinks.push(link);
              }
            } else {
              console.log(`Cache API failed for ${link}, status:`, response.status);
              uncachedLinks.push(link);
            }
          } catch (err) {
            // If individual link check fails, add to uncached
            uncachedLinks.push(link);
          }
        }
        
        // If we found cached content, set it immediately
        if (cachedContent.length > 0) {
          setScrapedContent(prev => ({
            ...prev,
            [basePath]: cachedContent
          }));
          cachedResults[basePath] = cachedContent;
        }
        
        // Keep track of uncached links for background processing
        if (uncachedLinks.length > 0) {
          uncachedGroups[basePath] = uncachedLinks;
        }
        
      } catch (err) {
        console.error(`Failed to check cache for ${basePath}:`, err);
        // If cache check fails, treat all as uncached
        uncachedGroups[basePath] = groupLinks;
      }
    }

    // Now scrape uncached groups in the background
    for (const [basePath, uncachedLinks] of Object.entries(uncachedGroups)) {
      if (uncachedLinks.length > 0) {
        // Set loading state only for uncached items
        setScrapingGroups(prev => ({ ...prev, [basePath]: true }));
        
        try {
          const controller = new AbortController();
          const timeoutId = setTimeout(() => controller.abort(), 45000);
          
          const response = await fetch('http://13.127.180.168:8050/scrape-basic', {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
            },
            body: JSON.stringify({ urls: uncachedLinks }),
            signal: controller.signal
          });

          clearTimeout(timeoutId);
          
          if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
          }

          const data = await response.json();

          if (data.success && data.results) {
            const transformedResults = data.results.map(result => {
              if (result.structured_data) {
                return {
                  url: result.structured_data.source_url || result.url,
                  title: result.structured_data.title || 'Untitled',
                  description: result.structured_data.preview || result.structured_data.content?.substring(0, 200) + '...' || 'No description available',
                  content: result.structured_data.content || '',
                  content_type: result.structured_data.content_type || 'other'
                };
              }
              return {
                url: result.url || '',
                title: result.title || 'Untitled',
                description: result.description || 'No description available',
                content: result.content || '',
                content_type: result.content_type || 'other'
              };
            });

            // Merge with any existing cached content for this group
            setScrapedContent(prev => ({
              ...prev,
              [basePath]: [
                ...(cachedResults[basePath] || []),
                ...transformedResults
              ]
            }));
          }
        } catch (err) {
          console.error(`Failed to scrape uncached group ${basePath}:`, err);
        } finally {
          setScrapingGroups(prev => ({ ...prev, [basePath]: false }));
        }
      }
    }
  };

  const copyToClipboard = (text) => {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(() => {
        toast.success('Copied to clipboard!');
      }).catch(err => {
        console.error('Failed to copy with clipboard API: ', err);
        fallbackCopyTextToClipboard(text);
      });
    } else {
      fallbackCopyTextToClipboard(text);
    }
  };

  const fallbackCopyTextToClipboard = (text) => {
    const textArea = document.createElement("textarea");
    textArea.value = text;
    
    // Avoid scrolling to bottom
    textArea.style.top = "0";
    textArea.style.left = "0";
    textArea.style.position = "fixed";
    textArea.style.opacity = "0";
    
    document.body.appendChild(textArea);
    textArea.focus();
    textArea.select();
    
    try {
      const successful = document.execCommand('copy');
      if (successful) {
        toast.success('Copied to clipboard!');
      } else {
        toast.error('Failed to copy to clipboard');
      }
    } catch (err) {
      console.error('Fallback: Oops, unable to copy', err);
      toast.error('Failed to copy to clipboard');
    }
    
    document.body.removeChild(textArea);
  };

  const handleBoxClick = (contentItem) => {
    setSelectedContent(contentItem);
    setShowModal(true);
  };

  const closeModal = () => {
    setShowModal(false);
    setSelectedContent(null);
  };

  const handleScrapeGroup = async (basePath, groupLinks) => {
    setScrapingGroups(prev => ({ ...prev, [basePath]: true }));
    setError('');
    
    try {
      // Add timeout for long-running requests (45 seconds)
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 45000);
      
      const response = await fetch('http://13.127.180.168:8050/scrape-basic', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ urls: groupLinks }),
        signal: controller.signal
      });

      clearTimeout(timeoutId);
      
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }

      const data = await response.json();
      console.log('Scrape response:', data); // Debug logging

      if (data.success && data.results) {
        // Transform the data to match frontend expectations
        const transformedResults = data.results.map(result => {
          if (result.structured_data) {
            return {
              url: result.structured_data.source_url || result.url,
              title: result.structured_data.title || 'Untitled',
              description: result.structured_data.preview || result.structured_data.content?.substring(0, 200) + '...' || 'No description available',
              content: result.structured_data.content || '',
              content_type: result.structured_data.content_type || 'other'
            };
          }
          // Fallback for entries without structured_data
          return {
            url: result.url || '',
            title: result.title || 'Untitled',
            description: result.description || 'No description available',
            content: result.content || '',
            content_type: result.content_type || 'other'
          };
        });

        setScrapedContent(prev => ({
          ...prev,
          [basePath]: transformedResults
        }));
      } else {
        setError(data.error || 'Failed to scrape content - no results returned');
      }
    } catch (err) {
      if (err.name === 'AbortError') {
        setError('Scraping timed out after 45 seconds. Please try with fewer URLs.');
      } else {
        setError('Error scraping content: ' + err.message);
        console.error('Scraping error:', err);
      }
    } finally {
      setScrapingGroups(prev => ({ ...prev, [basePath]: false }));
    }
  };

  return (
    <div className="h-screen bg-gray-950 flex flex-col">
      {/* Header */}
      <div className="border-b border-gray-800">
        <div className="px-8 py-5">
          <div className="text-xl font-medium text-white">WebScraper</div>
        </div>
      </div>

      {/* Main Content */}
      <div className="flex-1 flex flex-col lg:flex-row overflow-hidden">
        {/* Left Panel - Input (Fixed) */}
        <div className="lg:w-1/2 w-full flex flex-col justify-center px-6 md:px-12 py-8 lg:py-0 overflow-hidden">
          <div className="max-w-md mx-auto w-full">
            <h1 className="text-4xl md:text-5xl lg:text-6xl font-light text-white mb-8 md:mb-12 tracking-tight">
              Scrape any website.
            </h1>

            <form onSubmit={handleSubmit} className="mb-8">
              <div className="relative">
                <input
                  type="url"
                  value={url}
                  onChange={(e) => setUrl(e.target.value)}
                  placeholder="Enter website URL"
                  className="w-full px-4 md:px-6 py-4 md:py-5 text-base md:text-lg text-white placeholder-gray-500 bg-gray-800 border border-gray-700 rounded-2xl focus:outline-none focus:ring-2 focus:ring-green-400 focus:border-transparent transition-all"
                  disabled={loading}
                />
                <button
                  type="submit"
                  disabled={loading || !url}
                  className="absolute right-2 md:right-3 top-2 md:top-3 px-4 md:px-8 py-2 bg-green-400 text-white text-sm md:text-base rounded-xl hover:bg-green-500 disabled:bg-gray-600 disabled:cursor-not-allowed transition-colors font-medium"
                >
                  {loading ? 'Extracting...' : 'Extract'}
                </button>
              </div>
            </form>

            {error && (
              <div className="p-4 bg-red-900/20 border border-red-800 rounded-xl text-red-300 text-center">
                {error}
              </div>
            )}

            {stats && (
              <div className="bg-gray-800 rounded-2xl p-6">
                <div className="text-center">
                  <div className="text-lg font-light text-white">{url}</div>
                </div>
              </div>
            )}

          </div>
        </div>

        {/* Right Panel - Results (Scrollable) */}
        <div className="lg:w-1/2 w-full lg:border-l lg:border-t-0 border-t border-gray-800 flex flex-col min-h-0">
          {loading ? (
            /* Shimmer Loading State */
            <>
              <div className="px-8 py-6 border-b border-gray-800">
                <div className="flex justify-between items-center">
                  <div className="h-6 bg-gray-700 rounded animate-pulse w-20"></div>
                  <div className="h-8 bg-gray-700 rounded animate-pulse w-32"></div>
                </div>
              </div>
              
              <div className="flex-1 overflow-y-auto p-8 space-y-6">
                {/* Group Header Shimmer */}
                {[1, 2, 3].map((groupIndex) => (
                  <div key={groupIndex}>
                    <div className="bg-gray-800 rounded-lg p-4 mb-3">
                      <div className="flex items-center justify-between mb-4">
                        <div className="h-4 bg-gray-700 rounded animate-pulse w-24"></div>
                        <div className="h-6 bg-gray-700 rounded animate-pulse w-16"></div>
                      </div>
                    </div>
                    
                    {/* Link Items Shimmer */}
                    {[1, 2, 3, 4].map((linkIndex) => (
                      <div key={linkIndex} className="mb-4">
                        <div className="flex items-center justify-between p-4 bg-gray-800/50 rounded-lg">
                          <div className="h-4 bg-gray-700 rounded animate-pulse flex-1 mr-4"></div>
                          <div className="h-6 bg-gray-700 rounded animate-pulse w-16"></div>
                        </div>
                      </div>
                    ))}
                  </div>
                ))}
              </div>
            </>
          ) : links.length > 0 ? (
            <>
              <div className="px-4 md:px-8 py-4 md:py-6 border-b border-gray-800">
                <div className="flex flex-col sm:flex-row sm:justify-between sm:items-center gap-4">
                  <h2 className="text-lg md:text-xl font-light text-white">Results</h2>
                  <div className="flex flex-col sm:flex-row sm:items-center gap-3 sm:gap-4">
                    <button
                      onClick={() => {
                        // Format data in the required structure
                        const formattedData = {
                          site: url,
                          items: Object.values(scrapedContent).flat().map(item => ({
                            title: item.title,
                            content: item.content,
                            content_type: item.content_type,
                            source_url: item.url
                          }))
                        };
                        copyToClipboard(JSON.stringify(formattedData, null, 2));
                      }}
                      className="px-3 py-2 text-sm text-green-400 border border-green-400 rounded-md hover:bg-green-900/20 transition-colors"
                    >
                      Copy JSON
                    </button>
                    <div className="flex bg-gray-800 rounded-lg p-1">
                      <button
                        onClick={() => setViewMode('links')}
                        className={`px-4 py-2 text-sm font-medium rounded-md transition-colors ${
                          viewMode === 'links'
                            ? 'bg-green-400 text-white'
                            : 'text-gray-400 hover:text-white hover:bg-gray-700'
                        }`}
                      >
                        Links
                      </button>
                      <button
                        onClick={() => setViewMode('content')}
                        className={`px-4 py-2 text-sm font-medium rounded-md transition-colors ${
                          viewMode === 'content'
                            ? 'bg-green-400 text-white'
                            : 'text-gray-400 hover:text-white hover:bg-gray-700'
                        }`}
                      >
                        Content
                      </button>
                    </div>
                  </div>
                </div>
              </div>
              
              <div className="flex-1 overflow-y-auto scrollbar-thin scrollbar-track-gray-900 scrollbar-thumb-gray-700 hover:scrollbar-thumb-gray-600">
                <style jsx>{`
                  /* Custom scrollbar styles */
                  .scrollbar-thin::-webkit-scrollbar {
                    width: 8px;
                  }
                  .scrollbar-track-gray-900::-webkit-scrollbar-track {
                    background: #111827;
                    border-radius: 4px;
                  }
                  .scrollbar-thumb-gray-700::-webkit-scrollbar-thumb {
                    background: #374151;
                    border-radius: 4px;
                  }
                  .hover\\:scrollbar-thumb-gray-600::-webkit-scrollbar-thumb:hover {
                    background: #4b5563;
                  }
                  /* Firefox */
                  .scrollbar-thin {
                    scrollbar-width: thin;
                    scrollbar-color: #374151 #111827;
                  }
                `}</style>
                <div className="p-4 md:p-8">
                  {viewMode === 'links' ? (
                    // Links View - Group by actual base paths
                    (() => {
                      // Group links by their actual base path
                      const groupedByBase = {};
                      links.forEach(link => {
                        const url = new URL(link);
                        const pathSegments = url.pathname.split('/').filter(Boolean);
                        const basePath = pathSegments.length > 1 ? `${url.origin}/${pathSegments[0]}/` : `${url.origin}/`;
                        
                        if (!groupedByBase[basePath]) {
                          groupedByBase[basePath] = [];
                        }
                        groupedByBase[basePath].push(link);
                      });
                      
                      return Object.entries(groupedByBase).map(([basePath, groupLinks]) => (
                        <div key={basePath} className="mb-8">
                          {/* Section Header */}
                          <div className="mb-4">
                            <div className="flex items-center space-x-3">
                              <span className="text-sm text-gray-500 bg-gray-700 px-2 py-1 rounded">
                                {groupLinks.length} links
                              </span>
                              <div className="text-lg text-gray-300">
                                {basePath}
                              </div>
                            </div>
                          </div>
                          
                          {/* Links in this group */}
                          <div className="space-y-2">
                            {groupLinks.map((link, linkIndex) => (
                              <div 
                                key={link} 
                                className="flex items-center justify-between p-3 bg-gray-800/50 rounded-lg hover:bg-gray-800/70 transition-colors group"
                              >
                                <a
                                  href={link}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  className="text-blue-400 hover:text-blue-300 text-sm truncate flex-1 mr-4"
                                >
                                  {(() => {
                                    const url = new URL(link);
                                    const pathSegments = url.pathname.split('/').filter(Boolean);
                                    if (pathSegments.length === 0) return '/';
                                    if (pathSegments.length === 1) return pathSegments[0];
                                    return pathSegments.slice(1).join('/');
                                  })()}
                                </a>
                                <button
                                  onClick={() => copyToClipboard(link)}
                                  className="opacity-0 group-hover:opacity-100 px-2 py-1 text-xs text-gray-400 hover:text-green-400 transition-all"
                                  title="Copy link"
                                >
                                  Copy
                                </button>
                              </div>
                            ))}
                          </div>
                        </div>
                      ));
                    })()
                  ) : (
                    // Content View - Group by actual base paths with scrape buttons
                    (() => {
                      // Group links by their actual base path
                      const groupedByBase = {};
                      links.forEach(link => {
                        const url = new URL(link);
                        const pathSegments = url.pathname.split('/').filter(Boolean);
                        const basePath = pathSegments.length > 1 ? `${url.origin}/${pathSegments[0]}/` : `${url.origin}/`;
                        
                        if (!groupedByBase[basePath]) {
                          groupedByBase[basePath] = [];
                        }
                        groupedByBase[basePath].push(link);
                      });
                      
                      return Object.entries(groupedByBase).map(([basePath, groupLinks]) => (
                        <div key={basePath} className="mb-8">
                          {/* Section Header */}
                          <div className="mb-4 p-4 bg-gray-800 rounded-lg">
                            <div className="flex items-center space-x-3">
                              <span className="text-sm text-gray-500 bg-gray-700 px-2 py-1 rounded">
                                {groupLinks.length} links
                              </span>
                              <div className="text-lg text-gray-300">
                                {basePath}
                              </div>
                              {scrapingGroups[basePath] && (
                                <div className="flex items-center space-x-2 text-sm text-green-400">
                                  <div className="w-3 h-3 border border-green-400 border-t-transparent rounded-full animate-spin"></div>
                                  <span>Processing...</span>
                                </div>
                              )}
                            </div>
                          </div>
                          
                          {/* Links Grid - Responsive Columns */}
                          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                            {groupLinks.map((link, linkIndex) => {
                              const scrapedData = scrapedContent[basePath]?.find(item => item.url === link);
                              const slug = (() => {
                                const url = new URL(link);
                                const pathSegments = url.pathname.split('/').filter(Boolean);
                                if (pathSegments.length === 0) return '/';
                                if (pathSegments.length === 1) return pathSegments[0];
                                return pathSegments.slice(1).join('/');
                              })();
                              
                              return (
                                <div key={linkIndex} className="text-center">
                                  <div 
                                    className={`bg-gray-800 border border-gray-600 rounded-lg p-4 hover:bg-gray-700 hover:border-gray-500 transition-colors mb-3 h-[140px] flex flex-col justify-between ${scrapedData ? 'cursor-pointer' : ''}`}
                                    onClick={() => scrapedData && handleBoxClick(scrapedData)}
                                  >
                                    {scrapedData ? (
                                      <div className="text-left flex flex-col h-full">
                                        <h4 className="text-sm font-medium text-white mb-2 line-clamp-2 flex-shrink-0">{scrapedData.title}</h4>
                                        <p className="text-xs text-gray-300 line-clamp-3 flex-grow">{scrapedData.description}</p>
                                        <div className="mt-2 text-xs text-green-400 flex-shrink-0">Click to view full content</div>
                                      </div>
                                    ) : (
                                      <div className="flex items-center justify-center h-full text-gray-500">
                                        {scrapingGroups[basePath] ? (
                                          <div className="w-4 h-4 border border-gray-400 border-t-transparent rounded-full animate-spin"></div>
                                        ) : (
                                          <span className="text-xs text-center">Content will load automatically</span>
                                        )}
                                      </div>
                                    )}
                                  </div>
                                  <div className="text-sm text-gray-300 break-words">
                                    {slug}
                                  </div>
                                </div>
                              );
                            })}
                          </div>
                        </div>
                      ));
                    })()
                  )}
                </div>
              </div>
            </>
          ) : (
            <div className="flex-1 flex items-center justify-center text-gray-500">
              <div className="text-center">
                <div className="w-16 h-16 mx-auto mb-4 rounded-full bg-gray-800 flex items-center justify-center">
                  <svg className="w-8 h-8 text-gray-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
                  </svg>
                </div>
                <p className="text-sm font-light">Links will appear here</p>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Modal for showing full content */}
      {showModal && selectedContent && (
        <div className="fixed inset-0 bg-black bg-opacity-75 flex items-center justify-center z-50 p-2 md:p-4">
          <div className="bg-gray-900 border border-gray-700 rounded-xl max-w-4xl w-full max-h-[95vh] md:max-h-[90vh] overflow-hidden">
            {/* Modal Header */}
            <div className="flex flex-col sm:flex-row sm:items-center justify-between p-4 md:p-6 border-b border-gray-700 gap-4">
              <div className="min-w-0 flex-1">
                <h2 className="text-lg md:text-xl font-semibold text-white truncate">{selectedContent.title}</h2>
                <p className="text-xs md:text-sm text-gray-400 mt-1 truncate">{selectedContent.url}</p>
              </div>
              <button
                onClick={closeModal}
                className="text-gray-400 hover:text-white transition-colors p-2"
              >
                <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
            
            {/* Modal Content */}
            <div className="p-4 md:p-6 overflow-y-auto max-h-[calc(95vh-140px)] md:max-h-[calc(90vh-140px)]">
              <div className="bg-gray-800 rounded-lg p-4 md:p-6">
                <div className="flex flex-col sm:flex-row sm:items-center justify-between mb-4 md:mb-6 gap-3">
                  <h3 className="text-base md:text-lg font-medium text-white">Article Content</h3>
                  <button
                    onClick={() => copyToClipboard(selectedContent.content)}
                    className="px-3 py-1 text-sm text-green-400 border border-green-400 rounded hover:bg-green-900/20 transition-colors"
                  >
                    Copy Markdown
                  </button>
                </div>
                <div className="prose prose-invert prose-sm md:prose-base max-w-none">
                  <ReactMarkdown
                    components={{
                      h1: ({children}) => <h1 className="text-2xl font-bold text-white mb-4 mt-6">{children}</h1>,
                      h2: ({children}) => <h2 className="text-xl font-semibold text-white mb-3 mt-5">{children}</h2>,
                      h3: ({children}) => <h3 className="text-lg font-semibold text-white mb-3 mt-4">{children}</h3>,
                      h4: ({children}) => <h4 className="text-base font-semibold text-white mb-2 mt-4">{children}</h4>,
                      h5: ({children}) => <h5 className="text-sm font-semibold text-white mb-2 mt-3">{children}</h5>,
                      h6: ({children}) => <h6 className="text-sm font-semibold text-gray-300 mb-2 mt-3">{children}</h6>,
                      p: ({children}) => <p className="text-gray-300 mb-4 leading-relaxed">{children}</p>,
                      strong: ({children}) => <strong className="font-semibold text-white">{children}</strong>,
                      em: ({children}) => <em className="italic text-gray-200">{children}</em>,
                      a: ({href, children}) => <a href={href} className="text-green-400 hover:text-green-300 underline" target="_blank" rel="noopener noreferrer">{children}</a>,
                      ul: ({children}) => <ul className="list-disc list-inside text-gray-300 mb-4 space-y-1">{children}</ul>,
                      ol: ({children}) => <ol className="list-decimal list-inside text-gray-300 mb-4 space-y-1">{children}</ol>,
                      li: ({children}) => <li className="text-gray-300">{children}</li>,
                      blockquote: ({children}) => <blockquote className="border-l-4 border-green-400 pl-4 italic text-gray-400 mb-4">{children}</blockquote>,
                      code: ({children}) => <code className="bg-gray-700 text-green-300 px-1 py-0.5 rounded text-sm font-mono">{children}</code>,
                      pre: ({children}) => <pre className="bg-gray-900 text-gray-300 p-3 rounded overflow-x-auto text-sm font-mono mb-4">{children}</pre>
                    }}
                  >
                    {selectedContent.content}
                  </ReactMarkdown>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

    </div>
  );
}