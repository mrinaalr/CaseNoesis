#!/bin/bash

# CaseLinker Setup Script
# Creates virtual environment and installs all dependencies

set -e  # Exit on error

echo "============================================================"
echo "CaseLinker - Environment Setup"
echo "============================================================"

# Check if Python 3 is available
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is not installed. Please install Python 3 first."
    exit 1
fi

echo "✓ Python 3 found: $(python3 --version)"

# Create virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    echo ""
    echo "Creating virtual environment..."
    python3 -m venv venv
    echo "✓ Virtual environment created"
else
    echo ""
    echo "✓ Virtual environment already exists"
fi

# Activate virtual environment
echo ""
echo "Activating virtual environment..."
source venv/bin/activate

# Upgrade pip
echo ""
echo "Upgrading pip..."
pip install --upgrade pip --quiet

# Install dependencies
echo ""
echo "Installing dependencies from requirements.txt..."
pip install -r requirements.txt

# Download spaCy English model (required for NER)
echo ""
echo "Downloading spaCy English model (en_core_web_sm)..."
python3 -m spacy download en_core_web_sm || echo "⚠️  Warning: Could not download spaCy model. NER will not work until you run: python -m spacy download en_core_web_sm"

echo ""
echo "============================================================"
echo "✓ Setup Complete!"
echo "============================================================"
echo ""
echo "To activate the virtual environment, run:"
echo "  source venv/bin/activate"
echo ""
echo ""
echo "Then you can run:"
echo "  python3 -m src.main          # Process PDF and store cases"
echo "  python3 run/main.py          # Start API server for visualization"
echo ""
echo "API Server:"
echo "  - Backend: http://localhost:8000"
echo "  - Visualization: http://localhost:8000/visualization"
echo "  - API Docs: http://localhost:8000/docs"
echo ""
echo "To deactivate, run:"
echo "  deactivate"
echo ""
