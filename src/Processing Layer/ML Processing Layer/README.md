# ML Processing Layer

## Overview

The ML Processing Layer provides ML/NLP enhancements for case processing. These components are designed to **complement** (not replace) the existing regex-based extraction in `processing.py`.

## Components

### 1. `ml_models.py` - Model Management
Centralized management of ML models with lazy loading and graceful degradation.

**Features:**
- Lazy loading: Models loaded on first use
- Graceful degradation: System works without ML models
- Model caching: Models loaded once and reused

### 2. `semantic_similarity.py` - Semantic Similarity
Generate semantic embeddings and calculate similarity between cases using transformer-based sentence embeddings.

**Features:**
- Generate embeddings for case text
- Calculate cosine similarity between cases
- Find similar cases using semantic search
- Batch processing for multiple cases

### 3. `ner_extraction.py` - Named Entity Recognition
Extract named entities (organizations, locations, persons, dates) using spaCy NER.

**Features:**
- Extract entities that regex might miss
- Merge with regex results intelligently
- Filter false positives
- Extract ages with context awareness

### 4. `content_sanitization.py` - Clean Case Generation
Generate "clean case" representations that preserve analytical value while removing harmful details.

**Features:**
- Generate analytical summaries
- Extract key facts (structured data only)
- Identify harmful content spans
- Create sanitized case text

## Installation

### Required Dependencies

```bash
# For semantic similarity
pip install sentence-transformers

# For NER extraction
pip install spacy
python -m spacy download en_core_web_sm

# For content sanitization (optional - has fallback)
pip install transformers torch
```

### Optional Dependencies

```bash
# For better summarization
pip install transformers[torch]
```

## Quick Start

### Basic Usage

```python
from ml_models import MLModelManager
from semantic_similarity import SemanticSimilarity
from ner_extraction import NERExtractor
from content_sanitization import ContentSanitizer

# Initialize ML manager
ml_manager = MLModelManager(enable_ml=True)

# Get models
semantic_model = ml_manager.get_model('semantic')
ner_model = ml_manager.get_model('ner')
summarization_model = ml_manager.get_model('summarization')

# Create components
semantic = SemanticSimilarity(semantic_model) if semantic_model else None
ner = NERExtractor(ner_model) if ner_model else None
sanitizer = ContentSanitizer(summarization_model)

# Use components
if semantic:
    embedding = semantic.get_case_embedding(case_text)
    similarity = semantic.calculate_similarity(text1, text2)

if ner:
    entities = ner.extract_entities(case_text)
    enhanced_case = ner.enhance_case_with_entities(case)

clean_case = sanitizer.sanitize_case(case_dict)
```

## Integration Guide

### Step 1: Evaluate Components

Before integrating, evaluate each component on your case data:

```python
# See example_usage.py for detailed examples
from example_usage import example_semantic_similarity, example_ner_extraction, example_content_sanitization

# Test each component
example_semantic_similarity()
example_ner_extraction()
example_content_sanitization()
```

### Step 2: Wire Up Components

Integrate into your existing processing pipeline:

```python
# In your processing code (after regex extraction)
from ml_models import MLModelManager
from semantic_similarity import SemanticSimilarity
from ner_extraction import NERExtractor
from content_sanitization import ContentSanitizer

def process_cases_with_ml(df, ml_manager=None):
    # Your existing regex processing
    cases = process_cases(df)  # Existing function
    
    # ML enhancement (optional)
    if ml_manager:
        semantic_model = ml_manager.get_model('semantic')
        ner_model = ml_manager.get_model('ner')
        summarization_model = ml_manager.get_model('summarization')
        
        semantic = SemanticSimilarity(semantic_model) if semantic_model else None
        ner = NERExtractor(ner_model) if ner_model else None
        sanitizer = ContentSanitizer(summarization_model)
        
        # Enhance each case
        enhanced_cases = []
        for case in cases:
            enhanced = case.copy()
            
            if semantic:
                enhanced = semantic.enhance_case_with_semantic_features(enhanced)
            
            if ner:
                enhanced = ner.enhance_case_with_entities(enhanced)
            
            enhanced = sanitizer.enhance_case_with_clean_data(enhanced)
            
            enhanced_cases.append(enhanced)
        
        return enhanced_cases
    
    return cases
```

### Step 3: Use in Clustering & Visualization

Use ML features in other layers:

```python
# In clustering layer - use semantic embeddings
semantic_embedding = case.get('ml_features', {}).get('semantic_embedding')
if semantic_embedding:
    # Use for semantic similarity clustering
    pass

# In visualization layer - use clean case
clean_case = case.get('clean_case', {})
if clean_case:
    # Display analytical_summary instead of raw case_text
    display_text = clean_case.get('analytical_summary')
```

## Component Details

### Semantic Similarity

**Use Cases:**
- Better case similarity calculation
- Semantic search ("find cases like this")
- Case clustering based on meaning

**Output:**
- `ml_features['semantic_embedding']`: Embedding vector (list of floats)
- Can be used for cosine similarity calculation

### NER Extraction

**Use Cases:**
- Extract organizations regex might miss
- Extract locations and dates
- Supplement regex extraction

**Output:**
- `ml_features['ner_entities']`: Dictionary of extracted entities
- Merged with regex results in `agencies_involved`

### Content Sanitization

**Use Cases:**
- Generate clean case views for training/demos
- Create analytical summaries
- Reduce emotional impact of case review

**Output:**
- `clean_case['analytical_summary']`: High-level summary
- `clean_case['key_facts']`: Structured facts only
- `clean_case['clean_text']`: Sanitized full text

## Performance Considerations

### Model Loading
- Models are lazy-loaded (loaded on first use)
- Models are cached after first load
- Use `MLModelManager.clear_cache()` to free memory

### Batch Processing
- Use `get_case_embeddings_batch()` for multiple cases
- More efficient than individual calls

### Fallbacks
- Content sanitization works without ML model (uses extractive summarization)
- System gracefully degrades if models unavailable

## Evaluation

Before full integration, evaluate:

1. **Semantic Similarity**: Do embeddings capture meaningful similarity?
2. **NER Extraction**: Does NER catch entities regex misses?
3. **Content Sanitization**: Are summaries useful? Do they preserve analytical value?

See `example_usage.py` for evaluation examples.

## Future Enhancements

- Fine-tuned models for case-specific tasks
- Custom harmful content detection classifier
- Advanced redaction logic
- Multi-language support

## Notes

- ML components are **optional** - system works without them
- ML features stored separately in `ml_features` dict
- Original case data preserved
- Regex extraction remains primary method
