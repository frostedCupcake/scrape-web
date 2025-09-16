# Web Scraper

Web scraper application with Next.js frontend and FastAPI backend.

## How to Start

### Frontend
```bash
npm install
npm run dev
```
Open [http://localhost:3000](http://localhost:3000)

### Backend
```bash
cd backend
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8050 --reload
```
Backend runs on [http://localhost:8050](http://localhost:8050)
