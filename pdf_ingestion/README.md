# PDF Ingestion Layer

Production-ready PDF extraction service for the reconciliation product. Processes bank/custody statements and SWIFT/broker trade confirmations, extracting structured data with full provenance tracking.

## Architecture

```
POST /v1/extract → Ingestion → Classifier → Extractor → Triangulation
    → Assembler → Schema Extractor → VLM Fallback → Validator → Packager → Delivery
```

**Key design principles:**
- Pipeline pattern with discrete stages
- Ports & adapters — all external dependencies behind interfaces
- Abstention over fabrication — missing values preferred over wrong values
- Full provenance on every extracted field (page, bbox, source, rule)
- Dual-rail table triangulation (pdfplumber vs camelot-py)
- Per-tenant VLM consent with Presidio redaction

**Pipeline stages:**

| Stage | Module | Purpose |
|-------|--------|---------|
| Ingestion | `pipeline/ingestion.py` | Validate, dedup (SHA-256), repair (pikepdf) |
| Classifier | `pipeline/classifier.py` | Per-page DIGITAL/SCANNED (threshold 0.80) |
| Digital Extractor | `pipeline/extractors/digital.py` | pdfplumber text + tables |
| Camelot Extractor | `pipeline/extractors/camelot_extractor.py` | Second-rail table extraction |
| OCR Extractor | `pipeline/extractors/ocr.py` | PaddleOCR for scanned pages |
| Triangulation | `pipeline/triangulation.py` | Cell-by-cell table comparison |
| Assembler | `pipeline/assembler.py` | XY-cut reading order, table stitching |
| Schema Extractor | `pipeline/schemas/` | Rule-based field extraction per doc type |
| VLM Fallback | `pipeline/vlm/` | Claude 3.5 Sonnet on Bedrock (gated) |
| Validator | `pipeline/validator.py` | Domain constraint checks |
| Packager | `pipeline/packager.py` | Assemble FinalOutput with confidence |
| Delivery | `pipeline/delivery.py` | Webhook push with retry |

## Setup

### Prerequisites

- Python 3.11+
- Docker & Docker Compose
- AWS credentials (for Bedrock VLM fallback)

### Local Development

```bash
cd pdf_ingestion

# Create virtual environment
python -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -e ".[dev]"

# Copy environment config
cp .env.example .env
# Edit .env with your settings

# Run database migrations
alembic upgrade head

# Start the service
uvicorn api.main:app --reload --port 8000
```

### Docker Compose

```bash
cd pdf_ingestion

# Start all services
docker compose up -d

# Check health
curl http://localhost:8000/v1/healthz

# View logs
docker compose logs -f api
```

Services:
- **api** — FastAPI service on port 8000
- **postgres** — PostgreSQL 16 on port 5432
- **paddleocr** — PaddleOCR service on port 8080

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `AWS_REGION` | `eu-west-1` | AWS region for Bedrock |
| `BEDROCK_MODEL_ID` | `anthropic.claude-3-5-sonnet-20241022-v2:0` | Bedrock model ID |
| `VLM_CONFIDENCE_THRESHOLD` | `0.80` | Minimum VLM confidence |
| `TRIANGULATION_SOFT_FLAG_THRESHOLD` | `0.10` | Soft flag threshold |
| `TRIANGULATION_HARD_FLAG_THRESHOLD` | `0.40` | Hard flag threshold |
| `PADDLEOCR_ENDPOINT` | `http://paddleocr:8080` | PaddleOCR service URL |
| `DATABASE_URL` | `postgresql+asyncpg://...` | PostgreSQL connection string |
| `DIGITAL_PAGE_THRESHOLD` | `0.80` | Digital page classification threshold |
| `VLM_VERIFIER_FUZZY_THRESHOLD` | `0.85` | VLM verification fuzzy match threshold |
| `MAX_FILE_SIZE_MB` | `50` | Maximum upload file size in MB |

## API Endpoints

All routes are prefixed `/v1/`. Protected routes require `Authorization: Bearer <api_key>`.

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/extract` | Upload PDF for extraction |
| `GET` | `/v1/jobs/{id}` | Get job status |
| `GET` | `/v1/results/{id}` | Get extraction result |
| `GET` | `/v1/batches/{batch_id}` | Get batch status |
| `POST` | `/v1/feedback/{job_id}` | Submit correction |
| `GET` | `/v1/tenants/{id}/redaction-config` | Get redaction settings |
| `PUT` | `/v1/tenants/{id}/redaction-config` | Update redaction settings |
| `GET` | `/v1/healthz` | Liveness probe |
| `GET` | `/v1/readyz` | Readiness probe |

### Example: Extract a document

```bash
curl -X POST http://localhost:8000/v1/extract \
  -H "Authorization: Bearer your-api-key" \
  -F "file=@statement.pdf" \
  -F "schema_type=bank_statement"
```

Response (HTTP 202):
```json
{
  "data": {"job_id": "...", "trace_id": "..."},
  "meta": {"request_id": "...", "timestamp": "2024-01-15T10:00:00Z"},
  "error": null
}
```

## Adding a New Schema Extractor

1. Create `pipeline/schemas/your_schema.py`:

```python
from pipeline.schemas.base import BaseSchemaExtractor
from pipeline.models import AssembledDocument

class YourSchemaExtractor(BaseSchemaExtractor):
    SCHEMA_TYPE = "your_schema"

    FIELD_PATTERNS = {
        "field_name": [
            r"pattern_1:\s*(.+)",
            r"pattern_2:\s*(.+)",
        ],
    }

    def extract(self, doc: AssembledDocument) -> dict:
        fields = {}
        abstentions = []

        for field_name, patterns in self.FIELD_PATTERNS.items():
            result = self.find_field(doc, field_name, patterns)
            if result:
                fields[field_name] = result
            else:
                abstentions.append(self._make_abstention(field_name))

        return {"fields": fields, "tables": [], "abstentions": abstentions}
```

2. Register in `pipeline/schemas/router.py`:
   - Add keywords to the detection logic
   - Add the extractor to `get_extractor()`

3. Add test fixtures in `tests/fixtures/`

## Running Tests

```bash
cd pdf_ingestion

# Run all tests
pytest

# Run with verbose output
pytest -v

# Run specific test file
pytest tests/test_ingestion.py

# Run with coverage
pytest --cov=. --cov-report=term-missing
```

## Bedrock IAM Setup

The VLM fallback requires AWS Bedrock access. Configure IAM with:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel"
      ],
      "Resource": [
        "arn:aws:bedrock:eu-west-1::foundation-model/anthropic.claude-3-5-sonnet-20241022-v2:0"
      ]
    }
  ]
}
```

Ensure the service has credentials available via:
- IAM instance profile (EC2/ECS)
- Environment variables (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`)
- AWS credentials file (`~/.aws/credentials`)

The VLM fallback is opt-in per tenant (`vlm_enabled: true`). If disabled, the pipeline abstains on fields that rule-based extraction cannot resolve.

## Project Structure

```
pdf_ingestion/
├── api/                    # FastAPI application layer
│   ├── main.py            # App factory, lifespan, router registration
│   ├── config.py          # Settings (BaseSettings)
│   ├── errors.py          # ErrorCode registry
│   ├── middleware/        # Auth middleware
│   ├── models/            # Pydantic request/response models
│   └── routes/            # Route handlers
├── pipeline/              # Core extraction pipeline
│   ├── runner.py          # End-to-end orchestration
│   ├── ingestion.py       # Validation, dedup, repair
│   ├── classifier.py      # Per-page DIGITAL/SCANNED
│   ├── assembler.py       # Document assembly
│   ├── triangulation.py   # Table comparison engine
│   ├── validator.py       # Domain constraint validators
│   ├── packager.py        # Output assembly
│   ├── delivery.py        # Webhook delivery with retry
│   ├── ports.py           # Port interfaces (ABCs)
│   ├── models.py          # Internal pipeline dataclasses
│   ├── extractors/        # Digital + OCR extractors
│   ├── schemas/           # Per-document-type extractors
│   └── vlm/               # VLM client, redactor, verifier
├── db/                    # Database models and migrations
├── frontend/              # Companion UI components
├── tests/                 # Test suite
│   └── fixtures/          # Test data files
├── Dockerfile             # Multi-stage production build
├── docker-compose.yml     # Local development stack
├── pyproject.toml         # Dependencies and tool config
└── .env.example           # Environment variable template
```
