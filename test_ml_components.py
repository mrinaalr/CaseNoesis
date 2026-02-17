"""
Test ML Processing Layer Components

Evaluates semantic similarity, NER extraction, and content sanitization
on actual case data to assess performance and value.
"""

import sys
from pathlib import Path

# Add paths
sys.path.insert(0, str(Path(__file__).parent / "src" / "Processing Layer" / "ML Processing Layer"))
sys.path.insert(0, str(Path(__file__).parent / "src" / "Storage Layer"))

from ml_models import MLModelManager
from semantic_similarity import SemanticSimilarity
from ner_extraction import NERExtractor
from content_sanitization import ContentSanitizer
from storage import CaseStorage

def test_ml_components():
    """Test all ML components on real case data"""
    
    print("=" * 60)
    print("ML Processing Layer - Component Evaluation")
    print("=" * 60)
    
    # Load cases from database
    print("\n1. Loading cases from database...")
    storage = CaseStorage("caselinker.db")
    cases = storage.get_all_cases()
    print(f"   ✓ Loaded {len(cases)} cases")
    
    if not cases:
        print("   ⚠️  No cases found in database. Run CaseLinker pipeline first.")
        return
    
    # Initialize ML models
    print("\n2. Initializing ML models...")
    ml_manager = MLModelManager(enable_ml=True)
    status = ml_manager.get_status()
    
    print(f"   ML Enabled: {status['ml_enabled']}")
    print(f"   Dependencies: {status['dependencies']}")
    print(f"   Model Status: {status['model_status']}")
    
    # Test Semantic Similarity
    print("\n3. Testing Semantic Similarity...")
    semantic_model = ml_manager.get_model('semantic')
    if semantic_model:
        semantic = SemanticSimilarity(semantic_model)
        print("   ✓ Semantic model loaded")
        
        # Test on first case
        if cases:
            test_case = cases[0]
            case_text = test_case.get('case_text', '') or test_case.get('raw_data', {}).get('case_text', '')
            if case_text:
                embedding = semantic.get_case_embedding(case_text[:500])  # First 500 chars
                if embedding:
                    print(f"   ✓ Generated embedding (dim: {len(embedding)})")
                    
                    # Test similarity with another case
                    if len(cases) > 1:
                        case2 = cases[1]
                        text2 = case2.get('case_text', '') or case2.get('raw_data', {}).get('case_text', '')
                        if text2:
                            similarity = semantic.calculate_similarity(case_text[:500], text2[:500])
                            if similarity:
                                print(f"   ✓ Similarity score: {similarity:.3f}")
    else:
        print("   ⚠️  Semantic model not available")
        print("   Install: pip install sentence-transformers")
    
    # Test NER Extraction
    print("\n4. Testing Named Entity Recognition...")
    ner_model = ml_manager.get_model('ner')
    if ner_model:
        ner = NERExtractor(ner_model)
        print("   ✓ NER model loaded")
        
        # Test on first case
        if cases:
            test_case = cases[0]
            case_text = test_case.get('case_text', '') or test_case.get('raw_data', {}).get('case_text', '')
            if case_text:
                entities = ner.extract_entities(case_text)
                print(f"   ✓ Extracted entities:")
                print(f"     - Organizations: {len(entities['organizations'])}")
                if entities['organizations']:
                    print(f"       {entities['organizations'][:3]}")
                print(f"     - Locations: {len(entities['locations'])}")
                if entities['locations']:
                    print(f"       {entities['locations'][:3]}")
                print(f"     - Dates: {len(entities['dates'])}")
                print(f"     - Ages: {len(entities['ages'])}")
    else:
        print("   ⚠️  NER model not available")
        print("   Install: pip install spacy && python -m spacy download en_core_web_sm")
    
    # Test Content Sanitization
    print("\n5. Testing Content Sanitization...")
    summarization_model = ml_manager.get_model('summarization')
    sanitizer = ContentSanitizer(summarization_model)
    print("   ✓ Sanitizer initialized (works with or without ML model)")
    
    # Test on first case
    if cases:
        test_case = cases[0]
        clean_case = sanitizer.sanitize_case(test_case)
        print(f"   ✓ Generated clean case:")
        print(f"     - Has analytical summary: {bool(clean_case.get('analytical_summary'))}")
        print(f"     - Has key facts: {bool(clean_case.get('key_facts'))}")
        print(f"     - Sanitization method: {clean_case.get('sanitization_metadata', {}).get('sanitization_method')}")
        
        if clean_case.get('analytical_summary'):
            summary = clean_case['analytical_summary']
            print(f"     - Summary length: {len(summary)} chars")
            print(f"     - Preview: {summary[:100]}...")
    
    # Compare NER with regex extraction
    print("\n6. Comparing NER with Regex Extraction...")
    if ner_model and cases:
        ner = NERExtractor(ner_model)
        test_case = cases[0]
        case_text = test_case.get('case_text', '') or test_case.get('raw_data', {}).get('case_text', '')
        
        if case_text:
            # Get regex-extracted agencies
            regex_agencies = test_case.get('agencies_involved', [])
            
            # Get NER-extracted organizations
            entities = ner.extract_entities(case_text)
            ner_orgs = entities.get('organizations', [])
            
            print(f"   Regex agencies: {len(regex_agencies)} - {regex_agencies[:3]}")
            print(f"   NER organizations: {len(ner_orgs)} - {ner_orgs[:3]}")
            
            # Find what NER caught that regex didn't
            new_orgs = set(ner_orgs) - set(regex_agencies)
            if new_orgs:
                print(f"   ✓ NER found {len(new_orgs)} additional organizations: {list(new_orgs)[:3]}")
            else:
                print(f"   - NER didn't find additional organizations beyond regex")
    
    # Batch test semantic similarity
    print("\n7. Batch Testing Semantic Similarity...")
    if semantic_model and len(cases) >= 3:
        semantic = SemanticSimilarity(semantic_model)
        test_cases = cases[:3]
        texts = []
        for case in test_cases:
            text = case.get('case_text', '') or case.get('raw_data', {}).get('case_text', '')
            if text:
                texts.append(text[:500])  # First 500 chars
        
        if len(texts) >= 2:
            embeddings = semantic.get_case_embeddings_batch(texts)
            print(f"   ✓ Generated {len(embeddings)} embeddings in batch")
            
            # Calculate similarity matrix
            if len(embeddings) >= 2 and embeddings[0] and embeddings[1]:
                similarity = semantic.calculate_similarity_from_embeddings(
                    embeddings[0], embeddings[1]
                )
                if similarity:
                    print(f"   ✓ Case 1 vs Case 2 similarity: {similarity:.3f}")
    
    print("\n" + "=" * 60)
    print("Evaluation Complete")
    print("=" * 60)
    print("\nNext steps:")
    print("1. Review results above")
    print("2. Assess whether ML components add value")
    print("3. Wire up components if evaluation is positive")

if __name__ == "__main__":
    test_ml_components()
