# FastAPI Backend

A FastAPI backend for web scraping with file-based storage.

## Setup

1. Install Python dependencies:
```bash
pip install -r requirements.txt
```

2. Configure environment variables:
```bash
cp .env.example .env
# Edit .env with your settings
```

3. Run the development server:
```bash
python main.py
```

Or with uvicorn directly:
```bash
uvicorn main:app --host 0.0.0.0 --port 5000 --reload
```

## API Endpoints

### Health Check
- `GET /` - Health check
- `GET /health` - Health check

### Scraping Jobs
- `POST /scrape` - Create a new scrape job
- `GET /scrape/{job_id}` - Get specific scrape job
- `GET /scrape` - List all scrape jobs

### Link Extraction
- `POST /extract-links` - Extract all links from a URL
  - Request body: `{"url": "https://example.com"}`
  - Returns: List of all links found on the page
- `GET /extract-links/history` - Get history of link extractions

## Data Storage

Jobs are stored as JSON files in the `data/` directory. Each job has:
- Unique ID
- URL to scrape
- Status (pending, completed, failed)
- Creation and update timestamps
- Scraped data (when completed)

## Environment Variables

See `.env.example` for all available configuration options.

## Testing

Run the test script to verify the API is working:
```bash
python test_api.py
```

## Example Usage

### Extract Links from a URL
```bash
curl -X POST "http://localhost:5000/extract-links" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.python.org"}'
```

Response:
```json
{
  "success": true,
  "url": "https://www.python.org",
  "final_url": "https://www.python.org",
  "status_code": 200,
  "links": [
    "https://www.python.org/about/",
    "https://www.python.org/downloads/",
    ...
  ],
  "count": 150,
  "content_type": "text/html",
  "error": null
}
```