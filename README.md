# Smart PDF

A back-office document extraction service for financial reconciliation. Processes bank statements, custody statements, SWIFT confirmations, and settlement reports — extracting structured data from any PDF format (digital or scanned).

## Features

- **Schema-agnostic extraction** — handles any table structure without hardcoded column definitions
- **Two-phase LLM architecture** — metadata extraction + per-window transaction extraction (never hits output token limits)
- **Multi-section document support** — splits composite PDFs by schema type, processes sections in parallel
- **OCR for scanned documents** — Tesseract with parallel page processing
- **Real-time progress tracking** — pages processed, current stage, ETA
- **Validation checks** — balance reconciliation, running balance, column type consistency, completeness
- **Professional operational frontend** — dark navy UI with job queue, results viewer, and integration guide

## Architecture

```
PDF Upload → Ingestion → Classification → OCR/Digital Extraction
    → Section Segmentation → Schema Detection → Rule-based Extraction
    → VLM Fallback (Bedrock Claude) → Validation → Packaging → Delivery
```

## Quick Start

### Backend

```bash
cd pdf_ingestion

# Create virtual environment
python -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -e .

# Copy environment config
cp .env.example .env
# Edit .env with your AWS credentials

# Run the server
uvicorn api.main:app --port 8000
```

### Frontend

```bash
cd pdf_ingestion/frontend

# Install dependencies
npm install

# Run dev server (proxies API to localhost:8000)
npm run dev
```

Open http://localhost:3001 in your browser.

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/v1/extract` | Submit a PDF for extraction |
| GET | `/v1/jobs/{id}` | Check job status |
| GET | `/v1/jobs/{id}/progress` | Real-time progress |
| GET | `/v1/results/{id}` | Get extraction results |
| POST | `/v1/jobs/{id}/cancel` | Cancel a processing job |
| POST | `/v1/feedback/{id}` | Submit a correction |

## Configuration

Key environment variables (`.env`):

```
AWS_REGION=us-east-1
BEDROCK_MODEL_ID=us.anthropic.claude-sonnet-4-6
VLM_MAX_TOKENS_PER_JOB=500000
VLM_MAX_CONCURRENT_WINDOWS=10
MAX_FILE_SIZE_MB=100
```

## Tech Stack

- **Backend**: Python, FastAPI, pdfplumber, Tesseract OCR, AWS Bedrock (Claude)
- **Frontend**: React 18, Vite, React Router v6
- **Testing**: pytest (backend), Vitest + fast-check (frontend)

## Project Structure

```
pdf_ingestion/
├── api/              # FastAPI routes, middleware, models
├── pipeline/         # Extraction pipeline stages
│   ├── vlm/          # LLM extraction (Bedrock client, chunked extractor)
│   ├── extractors/   # OCR and digital extractors
│   ├── schemas/      # Schema-specific regex extractors
│   └── alerts/       # Alert engine
├── frontend/         # React + Vite operational UI
│   └── src/
│       ├── components/   # Reusable UI components
│       └── screens/      # Page-level screens
├── db/               # Database models and migrations
└── tests/            # Test suite
```

## License

Proprietary — internal use only.
