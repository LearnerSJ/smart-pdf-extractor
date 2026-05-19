#!/bin/bash
# Quick setup script for PDF Ingestion Layer
# Usage: ./setup.sh

set -e

echo "═══════════════════════════════════════════════════"
echo "  PDF Ingestion Layer — Setup"
echo "═══════════════════════════════════════════════════"
echo ""

# Check prerequisites
echo "Checking prerequisites..."

if ! command -v python3 &> /dev/null; then
    echo "✗ Python 3 not found. Install Python 3.11+ from https://python.org"
    exit 1
fi

PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo "  ✓ Python $PYTHON_VERSION"

if ! command -v node &> /dev/null; then
    echo "✗ Node.js not found. Install from https://nodejs.org"
    exit 1
fi
echo "  ✓ Node.js $(node --version)"

if ! command -v tesseract &> /dev/null; then
    echo "  ⚠ Tesseract OCR not found (optional — needed for scanned PDFs)"
    echo "    Install: brew install tesseract (macOS) or apt-get install tesseract-ocr (Linux)"
else
    echo "  ✓ Tesseract $(tesseract --version 2>&1 | head -1)"
fi

echo ""

# Backend setup
echo "Setting up Python backend..."
cd pdf_ingestion

if [ ! -d ".venv" ]; then
    python3 -m venv .venv
    echo "  ✓ Virtual environment created"
fi

source .venv/bin/activate
pip install --upgrade pip -q
pip install -e ".[dev]" -q
echo "  ✓ Dependencies installed"

if [ ! -f ".env" ]; then
    cp .env.example .env
    echo "  ✓ Created .env from template"
    echo "  ⚠ Edit pdf_ingestion/.env with your AWS credentials before running"
fi

cd ..

# Frontend setup
echo ""
echo "Setting up React frontend..."
cd pdf_ingestion/frontend
npm install --silent
echo "  ✓ Frontend dependencies installed"
cd ../..

echo ""
echo "═══════════════════════════════════════════════════"
echo "  ✓ Setup complete!"
echo "═══════════════════════════════════════════════════"
echo ""
echo "To start the application:"
echo ""
echo "  Terminal 1 (Backend):"
echo "    cd pdf_ingestion"
echo "    source .venv/bin/activate"
echo "    uvicorn api.main:app --port 8000 --reload"
echo ""
echo "  Terminal 2 (Frontend):"
echo "    cd pdf_ingestion/frontend"
echo "    npm run dev"
echo ""
echo "  Then open http://localhost:3001"
echo ""
echo "  Or use: make backend / make frontend"
echo ""
