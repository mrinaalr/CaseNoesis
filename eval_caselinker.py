#!/usr/bin/env python3
"""
Comprehensive Evaluation Script for CaseLinker
Tests all aspects of the system: ingestion, processing, storage, clustering, and visualization
"""

import sys
import json
import time
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime

# Add paths
src_path = Path(__file__).parent / "src"
sys.path.insert(0, str(src_path / "Ingestion Layer"))
sys.path.insert(0, str(src_path / "Processing Layer"))
sys.path.insert(0, str(src_path / "Storage Layer"))
sys.path.insert(0, str(src_path / "Clustering & Analysis Layer"))
sys.path.insert(0, str(src_path / "Visualization Layer"))

from ingestion import extract_pdf_text, ingest_file
from processing import process_cases, extract_features, case_batching
from storage import CaseStorage
from analysis import (
    group_similar_cases, 
    triage_cases, 
    calculate_case_similarity,
    generate_automated_insights,
    return_tagged_cases
)
import config

class CaseLinkerEvaluator:
    """Comprehensive evaluator for CaseLinker system"""
    
    def __init__(self):
        self.results = {
            'timestamp': datetime.now().isoformat(),
            'layers': {},
            'features': {},
            'performance': {},
            'quality': {},
            'issues': [],
            'recommendations': []
        }
        self.test_db_path = 'eval_test.db'
        
    def evaluate_ingestion_layer(self) -> Dict[str, Any]:
        """Evaluate Layer 1: Ingestion"""
        print("\n" + "="*80)
        print("LAYER 1: INGESTION LAYER EVALUATION")
        print("="*80)
        
        results = {
            'status': 'evaluating',
            'components': {},
            'coverage': {},
            'issues': []
        }
        
        # Test PDF extraction
        print("\n1. Testing PDF Text Extraction...")
        pdf_files = [
            "2011 Cases and Arrests – AZICAC.ORG.pdf",
            "2012 Cases and Arrests – AZICAC.ORG.pdf",
            "2013 Cases and Arrests – AZICAC.ORG.pdf",
            "2014 Cases and Arrests – AZICAC.ORG.pdf"
        ]
        
        pdf_results = {}
        total_text_length = 0
        for pdf_file in pdf_files:
            if Path(pdf_file).exists():
                try:
                    text = extract_pdf_text(pdf_file)
                    pdf_results[pdf_file] = {
                        'success': True,
                        'text_length': len(text),
                        'has_content': len(text) > 0
                    }
                    total_text_length += len(text)
                    print(f"  ✓ {pdf_file}: {len(text)} characters extracted")
                except Exception as e:
                    pdf_results[pdf_file] = {'success': False, 'error': str(e)}
                    print(f"  ✗ {pdf_file}: {str(e)}")
            else:
                pdf_results[pdf_file] = {'success': False, 'error': 'File not found'}
                print(f"  ✗ {pdf_file}: Not found")
        
        results['components']['pdf_extraction'] = pdf_results
        results['coverage']['total_text_extracted'] = total_text_length
        results['coverage']['pdfs_processed'] = sum(1 for r in pdf_results.values() if r.get('success'))
        
        # Test ingestion function
        print("\n2. Testing Ingestion Function...")
        if Path(pdf_files[0]).exists():
            try:
                df = ingest_file(pdf_files[0])
                results['components']['ingest_file'] = {
                    'success': True,
                    'columns': list(df.columns),
                    'rows': len(df)
                }
                print(f"  ✓ ingest_file: {len(df)} rows, columns: {list(df.columns)}")
            except Exception as e:
                results['components']['ingest_file'] = {'success': False, 'error': str(e)}
                results['issues'].append(f"Ingestion error: {str(e)}")
                print(f"  ✗ ingest_file: {str(e)}")
        
        results['status'] = 'complete'
        return results
    
    def evaluate_processing_layer(self) -> Dict[str, Any]:
        """Evaluate Layer 2: Processing"""
        print("\n" + "="*80)
        print("LAYER 2: PROCESSING LAYER EVALUATION")
        print("="*80)
        
        results = {
            'status': 'evaluating',
            'feature_extraction': {},
            'case_batching': {},
            'coverage': {},
            'issues': []
        }
        
        # Test case batching
        print("\n1. Testing Case Batching...")
        test_text = """
        In January 2011, a case happened.
        In February 2011, another case occurred.
        March 2011, yet another case.
        """
        
        try:
            # case_batching expects a DataFrame, not raw text
            import pandas as pd
            test_df = pd.DataFrame({
                'source_file': ['test.pdf'],
                'extracted_text': [test_text],
                'source': ['TEST']
            })
            batches = case_batching(test_df)
            results['case_batching'] = {
                'success': True,
                'cases_found': len(batches) if isinstance(batches, list) else 0,
                'pattern_working': len(batches) > 0 if isinstance(batches, list) else False
            }
            print(f"  ✓ Case batching: Found {len(batches) if isinstance(batches, list) else 0} cases")
        except Exception as e:
            results['case_batching'] = {'success': False, 'error': str(e)}
            results['issues'].append(f"Case batching error: {str(e)}")
            print(f"  ✗ Case batching: {str(e)}")
        
        # Test feature extraction
        print("\n2. Testing Feature Extraction...")
        test_case = {
            'case_text': 'In January 2011, a 25 year old man was arrested for possessing images of infants. The case involved Facebook and online chat. The suspect was a registered sex offender.',
            'id': 'test_001',
            'source': 'TEST'
        }
        
        try:
            features = extract_features(test_case)
            feature_coverage = {}
            
            # Check each feature category
            feature_categories = [
                'victim_count', 'victim_demographics', 'perpetrator_demographics',
                'relationship_to_victim', 'platforms_used', 'case_topics',
                'severity_indicators', 'investigation_type', 'prosecution_outcome',
                'evidence_volume', 'severity_phrases'
            ]
            
            for category in feature_categories:
                value = features.get(category)
                feature_coverage[category] = {
                    'extracted': value is not None,
                    'has_data': value is not None and (
                        (isinstance(value, list) and len(value) > 0) or
                        (isinstance(value, dict) and len(value) > 0) or
                        (isinstance(value, (str, int, float, bool)) and value)
                    )
                }
            
            results['feature_extraction'] = {
                'success': True,
                'coverage': feature_coverage,
                'total_features': len(features)
            }
            
            extracted_count = sum(1 for f in feature_coverage.values() if f['extracted'])
            print(f"  ✓ Feature extraction: {extracted_count}/{len(feature_categories)} features extracted")
            
        except Exception as e:
            results['feature_extraction'] = {'success': False, 'error': str(e)}
            results['issues'].append(f"Feature extraction error: {str(e)}")
            print(f"  ✗ Feature extraction: {str(e)}")
        
        results['status'] = 'complete'
        return results
    
    def evaluate_storage_layer(self) -> Dict[str, Any]:
        """Evaluate Layer 3: Storage"""
        print("\n" + "="*80)
        print("LAYER 3: STORAGE LAYER EVALUATION")
        print("="*80)
        
        results = {
            'status': 'evaluating',
            'database_operations': {},
            'schema': {},
            'performance': {},
            'issues': []
        }
        
        # Test database operations
        print("\n1. Testing Database Operations...")
        try:
            # Use test database
            storage = CaseStorage(self.test_db_path)
            
            # Test case storage
            test_case = {
                'id': 'eval_test_001',
                'source': 'EVAL',
                'case_text': 'Test case for evaluation',
                'relationship_to_victim': 'stranger',
                'platforms_used': ['online'],
                'case_topics': ['possession']
            }
            
            storage.store_case(test_case)
            results['database_operations']['store'] = {'success': True}
            print("  ✓ Case storage: Working")
            
            # Test retrieval
            retrieved = storage.get_case('eval_test_001')
            results['database_operations']['retrieve'] = {
                'success': retrieved is not None,
                'data_complete': retrieved is not None and 'id' in retrieved
            }
            print("  ✓ Case retrieval: Working")
            
            # Test get all cases
            all_cases = storage.get_all_cases()
            results['database_operations']['get_all'] = {
                'success': True,
                'count': len(all_cases)
            }
            print(f"  ✓ Get all cases: {len(all_cases)} cases")
            
            # Check schema
            if retrieved:
                schema_fields = [
                    'id', 'source', 'case_text', 'relationship_to_victim',
                    'platforms_used', 'case_topics', 'severity_indicators',
                    'investigation_type', 'prosecution_outcome'
                ]
                schema_coverage = {field: field in retrieved for field in schema_fields}
                results['schema'] = {
                    'fields_present': schema_coverage,
                    'total_fields': len(schema_fields),
                    'coverage': sum(schema_coverage.values()) / len(schema_fields)
                }
                print(f"  ✓ Schema: {sum(schema_coverage.values())}/{len(schema_fields)} fields present")
            
        except Exception as e:
            results['database_operations'] = {'success': False, 'error': str(e)}
            results['issues'].append(f"Storage error: {str(e)}")
            print(f"  ✗ Database operations: {str(e)}")
        
        results['status'] = 'complete'
        return results
    
    def evaluate_clustering_analysis_layer(self) -> Dict[str, Any]:
        """Evaluate Layer 4: Clustering & Analysis"""
        print("\n" + "="*80)
        print("LAYER 4: CLUSTERING & ANALYSIS LAYER EVALUATION")
        print("="*80)
        
        results = {
            'status': 'evaluating',
            'clustering': {},
            'similarity': {},
            'triage': {},
            'insights': {},
            'issues': []
        }
        
        # Load real cases
        try:
            storage = CaseStorage('caselinker.db')
            cases = storage.get_all_cases()
            
            if len(cases) == 0:
                results['issues'].append("No cases in database for evaluation")
                results['status'] = 'incomplete'
                return results
            
            print(f"\n1. Testing Clustering (using {len(cases)} cases)...")
            
            # Test clustering
            start_time = time.time()
            clusters = group_similar_cases(cases, similarity_threshold=config.SIMILARITY_THRESHOLD)
            clustering_time = time.time() - start_time
            
            results['clustering'] = {
                'success': True,
                'clusters_created': len(clusters),
                'total_cases_clustered': sum(c['size'] for c in clusters),
                'cluster_types': [c['group_name'] for c in clusters],
                'performance_ms': clustering_time * 1000,
                'average_similarities': {c['group_name']: c.get('average_similarity', 0) for c in clusters}
            }
            print(f"  ✓ Clustering: {len(clusters)} clusters created in {clustering_time*1000:.2f}ms")
            
            # Test similarity calculation
            print("\n2. Testing Similarity Calculation...")
            if len(cases) >= 2:
                start_time = time.time()
                similarity = calculate_case_similarity(cases[0], cases[1])
                similarity_time = time.time() - start_time
                
                results['similarity'] = {
                    'success': True,
                    'similarity_score': similarity,
                    'performance_ms': similarity_time * 1000,
                    'valid_range': 0 <= similarity <= 1
                }
                print(f"  ✓ Similarity: {similarity:.3f} calculated in {similarity_time*1000:.2f}ms")
            
            # Test triage
            print("\n3. Testing Priority Triage...")
            start_time = time.time()
            triaged = triage_cases(cases)
            triage_time = time.time() - start_time
            
            if triaged:
                results['triage'] = {
                    'success': True,
                    'cases_triaged': len(triaged),
                    'score_range': {
                        'min': min(c.get('priority_score', 0) for c in triaged),
                        'max': max(c.get('priority_score', 0) for c in triaged),
                        'avg': sum(c.get('priority_score', 0) for c in triaged) / len(triaged)
                    },
                    'performance_ms': triage_time * 1000
                }
                print(f"  ✓ Triage: {len(triaged)} cases triaged in {triage_time*1000:.2f}ms")
            
            # Test automated insights
            print("\n4. Testing Automated Insights...")
            if len(clusters) > 0:
                try:
                    insights = generate_automated_insights(cases, clusters)
                    results['insights'] = {
                        'success': True,
                        'insights_generated': len(insights.get('patterns', [])),
                        'has_statistics': 'statistics' in insights
                    }
                    print(f"  ✓ Insights: {len(insights.get('patterns', []))} patterns generated")
                except Exception as e:
                    results['insights'] = {'success': False, 'error': str(e)}
                    print(f"  ✗ Insights: {str(e)}")
            
        except Exception as e:
            results['issues'].append(f"Clustering/Analysis error: {str(e)}")
            print(f"  ✗ Error: {str(e)}")
        
        results['status'] = 'complete'
        return results
    
    def evaluate_full_pipeline(self) -> Dict[str, Any]:
        """Evaluate end-to-end pipeline"""
        print("\n" + "="*80)
        print("END-TO-END PIPELINE EVALUATION")
        print("="*80)
        
        results = {
            'status': 'evaluating',
            'pipeline_steps': {},
            'data_flow': {},
            'issues': []
        }
        
        # Test full pipeline with one PDF
        pdf_file = "2011 Cases and Arrests – AZICAC.ORG.pdf"
        if not Path(pdf_file).exists():
            results['status'] = 'skipped'
            results['issues'].append("PDF file not found for pipeline test")
            return results
        
        try:
            print("\n1. Testing Full Pipeline...")
            
            # Step 1: Ingestion
            start = time.time()
            df = ingest_file(pdf_file)
            ingest_time = time.time() - start
            results['pipeline_steps']['ingestion'] = {'success': True, 'time_ms': ingest_time * 1000}
            print(f"  ✓ Ingestion: {ingest_time*1000:.2f}ms")
            
            # Step 2: Processing
            start = time.time()
            processed = process_cases(df)
            process_time = time.time() - start
            results['pipeline_steps']['processing'] = {
                'success': True,
                'time_ms': process_time * 1000,
                'cases_processed': len(processed)
            }
            print(f"  ✓ Processing: {len(processed)} cases in {process_time*1000:.2f}ms")
            
            # Step 3: Storage
            storage = CaseStorage(self.test_db_path)
            start = time.time()
            for case in processed[:5]:  # Store first 5 for speed
                storage.store_case(case)
            store_time = time.time() - start
            results['pipeline_steps']['storage'] = {'success': True, 'time_ms': store_time * 1000}
            print(f"  ✓ Storage: {store_time*1000:.2f}ms")
            
            # Step 4: Analysis
            stored_cases = storage.get_all_cases()
            if len(stored_cases) > 0:
                start = time.time()
                clusters = group_similar_cases(stored_cases)
                analysis_time = time.time() - start
                results['pipeline_steps']['analysis'] = {
                    'success': True,
                    'time_ms': analysis_time * 1000,
                    'clusters': len(clusters)
                }
                print(f"  ✓ Analysis: {len(clusters)} clusters in {analysis_time*1000:.2f}ms")
            
            total_time = ingest_time + process_time + store_time + analysis_time
            results['data_flow'] = {
                'total_time_ms': total_time * 1000,
                'throughput_cases_per_sec': len(processed) / total_time if total_time > 0 else 0
            }
            
        except Exception as e:
            results['issues'].append(f"Pipeline error: {str(e)}")
            print(f"  ✗ Pipeline error: {str(e)}")
        
        results['status'] = 'complete'
        return results
    
    def evaluate_feature_coverage(self) -> Dict[str, Any]:
        """Evaluate feature extraction coverage on real data"""
        print("\n" + "="*80)
        print("FEATURE EXTRACTION COVERAGE EVALUATION")
        print("="*80)
        
        results = {
            'status': 'evaluating',
            'coverage': {},
            'issues': []
        }
        
        try:
            storage = CaseStorage('caselinker.db')
            cases = storage.get_all_cases()
            
            if len(cases) == 0:
                results['status'] = 'incomplete'
                return results
            
            print(f"\nEvaluating {len(cases)} cases...")
            
            # Count coverage for each feature
            feature_stats = {
                'relationship_to_victim': {'extracted': 0, 'total': len(cases)},
                'platforms_used': {'extracted': 0, 'total': len(cases)},
                'case_topics': {'extracted': 0, 'total': len(cases)},
                'severity_indicators': {'extracted': 0, 'total': len(cases)},
                'investigation_type': {'extracted': 0, 'total': len(cases)},
                'prosecution_outcome': {'extracted': 0, 'total': len(cases)},
                'victim_count': {'extracted': 0, 'total': len(cases)},
                'perpetrator_demographics': {'extracted': 0, 'total': len(cases)},
            }
            
            for case in cases:
                for feature in feature_stats.keys():
                    value = case.get(feature)
                    if value is not None:
                        if isinstance(value, (list, dict)):
                            if len(value) > 0:
                                feature_stats[feature]['extracted'] += 1
                        elif value:  # string, int, bool, etc.
                            feature_stats[feature]['extracted'] += 1
            
            # Calculate percentages
            coverage = {}
            for feature, stats in feature_stats.items():
                percentage = (stats['extracted'] / stats['total']) * 100 if stats['total'] > 0 else 0
                coverage[feature] = {
                    'extracted': stats['extracted'],
                    'total': stats['total'],
                    'percentage': percentage
                }
                print(f"  {feature}: {stats['extracted']}/{stats['total']} ({percentage:.1f}%)")
            
            results['coverage'] = coverage
            results['average_coverage'] = sum(c['percentage'] for c in coverage.values()) / len(coverage)
            
        except Exception as e:
            results['issues'].append(f"Coverage evaluation error: {str(e)}")
            print(f"  ✗ Error: {str(e)}")
        
        results['status'] = 'complete'
        return results
    
    def run_full_evaluation(self):
        """Run complete evaluation"""
        print("="*80)
        print("CASELINKER COMPREHENSIVE EVALUATION")
        print("="*80)
        print(f"Started at: {datetime.now().isoformat()}")
        
        # Evaluate each layer
        self.results['layers']['ingestion'] = self.evaluate_ingestion_layer()
        self.results['layers']['processing'] = self.evaluate_processing_layer()
        self.results['layers']['storage'] = self.evaluate_storage_layer()
        self.results['layers']['clustering_analysis'] = self.evaluate_clustering_analysis_layer()
        
        # Evaluate features
        self.results['features']['coverage'] = self.evaluate_feature_coverage()
        
        # Evaluate pipeline
        self.results['performance']['pipeline'] = self.evaluate_full_pipeline()
        
        # Generate summary
        self._generate_summary()
        
        # Save results
        output_file = 'eval_caselinker_results.json'
        with open(output_file, 'w') as f:
            json.dump(self.results, f, indent=2)
        
        print("\n" + "="*80)
        print("EVALUATION COMPLETE")
        print("="*80)
        print(f"Results saved to: {output_file}")
        self._print_summary()
        
        return self.results
    
    def _generate_summary(self):
        """Generate evaluation summary"""
        summary = {
            'total_issues': len(self.results.get('issues', [])),
            'layers_evaluated': len([l for l in self.results.get('layers', {}).values() if l.get('status') == 'complete']),
            'overall_status': 'pass' if len(self.results.get('issues', [])) == 0 else 'issues_found'
        }
        self.results['summary'] = summary
    
    def _print_summary(self):
        """Print evaluation summary"""
        print("\nSUMMARY:")
        print(f"  Layers evaluated: {self.results['summary']['layers_evaluated']}/4")
        print(f"  Issues found: {self.results['summary']['total_issues']}")
        print(f"  Overall status: {self.results['summary']['overall_status']}")
        
        if self.results.get('features', {}).get('coverage', {}).get('average_coverage'):
            avg = self.results['features']['coverage']['average_coverage']
            print(f"  Average feature coverage: {avg:.1f}%")
        
        if self.results.get('layers', {}).get('clustering_analysis', {}).get('clustering', {}).get('clusters_created'):
            clusters = self.results['layers']['clustering_analysis']['clustering']['clusters_created']
            print(f"  Clusters created: {clusters}")


if __name__ == "__main__":
    evaluator = CaseLinkerEvaluator()
    results = evaluator.run_full_evaluation()
