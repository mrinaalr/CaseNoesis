#!/usr/bin/env python3
"""
Comprehensive Evaluation Data Extraction for CaseLinker

This script performs comprehensive testing and evaluation of CaseLinker's capabilities,
generating detailed metrics suitable for academic research and system performance analysis.

Output: evaluation_results.json - Comprehensive evaluation data for academic sharing
"""

import sys
import json
from pathlib import Path
from collections import Counter, defaultdict
from typing import Dict, List, Any, Tuple
import statistics
from datetime import datetime

# Add paths
src_path = Path(__file__).parent / "src"
sys.path.insert(0, str(src_path / "Storage Layer"))
sys.path.insert(0, str(src_path / "Clustering & Analysis Layer"))

from storage import CaseStorage
from analysis import (
    group_similar_cases,
    triage_cases,
    generate_automated_insights,
    calculate_case_similarity,
    calculate_group_similarity_metrics,
    return_tagged_cases,
    run_automated_analysis
)

def load_all_cases(db_path: str = "caselinker.db") -> List[Dict[str, Any]]:
    """Load all cases from database"""
    storage = CaseStorage(db_path)
    all_cases = storage.get_all_cases()
    print(f"✓ Loaded {len(all_cases)} cases from database")
    return all_cases

def parse_json_field(field_value: Any) -> Any:
    """Safely parse JSON string fields"""
    if isinstance(field_value, str):
        try:
            return json.loads(field_value)
        except:
            return []
    return field_value if field_value else []

def evaluate_extraction_coverage(all_cases: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Comprehensive extraction coverage analysis"""
    total = len(all_cases)
    
    coverage = {
        'case_topics': {'extracted': 0, 'total': total, 'details': {}},
        'severity_indicators': {'extracted': 0, 'total': total, 'details': {}},
        'prosecution_outcome': {'extracted': 0, 'total': total, 'details': {}},
        'relationship_to_victim': {'extracted': 0, 'total': total, 'details': {}},
        'platforms_used': {'extracted': 0, 'total': total, 'details': {}},
        'investigation_type': {'extracted': 0, 'total': total, 'details': {}},
        'victim_count': {'extracted': 0, 'total': total, 'details': {}},
        'perpetrator_demographics': {'extracted': 0, 'total': total, 'details': {}},
        'evidence_volume': {'extracted': 0, 'total': total, 'details': {}},
        'agencies_involved': {'extracted': 0, 'total': total, 'details': {}},
        'date_range': {'extracted': 0, 'total': total, 'details': {}},
    }
    
    topic_counter = Counter()
    severity_counter = Counter()
    platform_counter = Counter()
    relationship_counter = Counter()
    investigation_counter = Counter()
    agency_counter = Counter()
    rso_count = 0
    age_distribution = []
    
    for case in all_cases:
        # Case topics
        topics = parse_json_field(case.get('case_topics', []))
        if topics and len(topics) > 0:
            coverage['case_topics']['extracted'] += 1
            topic_counter.update(topics)
        
        # Severity indicators
        severity = parse_json_field(case.get('severity_indicators', []))
        if severity and len(severity) > 0:
            coverage['severity_indicators']['extracted'] += 1
            severity_counter.update(severity)
        
        # Prosecution outcome
        prosecution = case.get('prosecution_outcome') or case.get('prosecution_outcomes')
        if prosecution:
            coverage['prosecution_outcome']['extracted'] += 1
        
        # Relationship
        relationship = case.get('relationship_to_victim')
        if relationship:
            coverage['relationship_to_victim']['extracted'] += 1
            relationship_counter[relationship] += 1
        
        # Platforms
        platforms = parse_json_field(case.get('platforms_used', []))
        if platforms and len(platforms) > 0:
            coverage['platforms_used']['extracted'] += 1
            platform_counter.update(platforms)
        
        # Investigation type
        inv_type = case.get('investigation_type')
        if inv_type:
            coverage['investigation_type']['extracted'] += 1
            investigation_counter[inv_type] += 1
        
        # Victim count
        victim_count = case.get('victim_count')
        if victim_count is not None:
            coverage['victim_count']['extracted'] += 1
        
        # Perpetrator demographics
        perp_age = case.get('perpetrator_age')
        rso = case.get('perpetrator_registered_sex_offender')
        if perp_age is not None or rso is not None:
            coverage['perpetrator_demographics']['extracted'] += 1
            if perp_age is not None:
                age_distribution.append(perp_age)
            if rso is True:
                rso_count += 1
        
        # Evidence volume
        evidence = case.get('evidence_volume', {})
        if evidence and isinstance(evidence, dict) and any(evidence.values()):
            coverage['evidence_volume']['extracted'] += 1
        
        # Agencies
        agencies = parse_json_field(case.get('agencies_involved', []))
        if agencies and len(agencies) > 0:
            coverage['agencies_involved']['extracted'] += 1
            agency_counter.update(agencies)
        
        # Date range
        if case.get('date_start') or case.get('date_range'):
            coverage['date_range']['extracted'] += 1
    
    # Calculate percentages and add details
    for key in coverage:
        extracted = coverage[key]['extracted']
        total_cases = coverage[key]['total']
        coverage[key]['percentage'] = (extracted / total_cases * 100) if total_cases > 0 else 0
    
    coverage['case_topics']['details'] = dict(topic_counter.most_common(20))
    coverage['severity_indicators']['details'] = dict(severity_counter.most_common(20))
    coverage['platforms_used']['details'] = dict(platform_counter.most_common(20))
    coverage['relationship_to_victim']['details'] = dict(relationship_counter)
    coverage['investigation_type']['details'] = dict(investigation_counter)
    coverage['agencies_involved']['details'] = dict(agency_counter.most_common(20))
    coverage['perpetrator_demographics']['details'] = {
        'registered_sex_offenders': rso_count,
        'age_distribution': {
            'mean': statistics.mean(age_distribution) if age_distribution else None,
            'median': statistics.median(age_distribution) if age_distribution else None,
            'min': min(age_distribution) if age_distribution else None,
            'max': max(age_distribution) if age_distribution else None,
            'count': len(age_distribution)
        }
    }
    
    return coverage

def evaluate_clustering(all_cases: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Comprehensive clustering evaluation"""
    print("  Running clustering analysis...")
    groups = group_similar_cases(all_cases, similarity_threshold=0.45)
    
    cluster_info = []
    all_similarities = []
    
    for group in groups:
        similarities = []
        cases_in_group = group.get('cases', [])
        
        # Calculate pairwise similarities within group
        for i, case1 in enumerate(cases_in_group):
            for case2 in cases_in_group[i+1:]:
                sim = calculate_case_similarity(case1, case2)
                similarities.append(sim)
                all_similarities.append(sim)
        
        cluster_info.append({
            'name': group.get('group_name', 'Unknown'),
            'size': group.get('size', 0),
            'average_similarity': group.get('average_similarity', 0.0),
            'min_similarity': group.get('min_similarity', 0.0),
            'max_similarity': group.get('max_similarity', 0.0),
            'description': group.get('description', ''),
            'internal_pairwise_similarities': {
                'mean': statistics.mean(similarities) if similarities else 0.0,
                'std': statistics.stdev(similarities) if len(similarities) > 1 else 0.0,
                'min': min(similarities) if similarities else 0.0,
                'max': max(similarities) if similarities else 0.0,
                'count': len(similarities)
            },
            'statistics': group.get('statistics', {})
        })
    
    return {
        'total_groups': len(groups),
        'groups': cluster_info,
        'overall_similarity_metrics': {
            'mean': statistics.mean(all_similarities) if all_similarities else 0.0,
            'std': statistics.stdev(all_similarities) if len(all_similarities) > 1 else 0.0,
            'min': min(all_similarities) if all_similarities else 0.0,
            'max': max(all_similarities) if all_similarities else 0.0,
            'total_pairs': len(all_similarities)
        },
        'cluster_size_distribution': {
            'mean': statistics.mean([g['size'] for g in cluster_info]) if cluster_info else 0.0,
            'median': statistics.median([g['size'] for g in cluster_info]) if cluster_info else 0.0,
            'min': min([g['size'] for g in cluster_info]) if cluster_info else 0,
            'max': max([g['size'] for g in cluster_info]) if cluster_info else 0
        }
    }

def evaluate_triage(all_cases: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Comprehensive priority triage evaluation"""
    print("  Running priority triage analysis...")
    triage_results = triage_cases(all_cases)
    
    scores = [case.get('priority_score', 0) for case in triage_results if case.get('priority_score') is not None]
    
    if not scores:
        return {
            'total_cases': len(all_cases),
            'score_range': {'min': 0, 'max': 0, 'mean': 0, 'std': 0, 'median': 0},
            'high_priority_count': 0,
            'high_priority_threshold': 8.0,
            'score_distribution': {}
        }
    
    high_priority = [s for s in scores if s >= 8.0]
    medium_priority = [s for s in scores if 6.0 <= s < 8.0]
    low_priority = [s for s in scores if s < 6.0]
    
    # Analyze high-priority cases
    high_priority_cases = [case for case in triage_results if case.get('priority_score', 0) >= 8.0]
    high_priority_characteristics = {
        'with_production': sum(1 for c in high_priority_cases if 'production' in parse_json_field(c.get('case_topics', []))),
        'with_infant': sum(1 for c in high_priority_cases if 'infant' in parse_json_field(c.get('severity_indicators', []))),
        'with_multiple_victims': sum(1 for c in high_priority_cases if (c.get('victim_count') or 0) > 1),
        'with_rso': sum(1 for c in high_priority_cases if c.get('perpetrator_registered_sex_offender') is True),
        'with_hands_on': sum(1 for c in high_priority_cases if 'hands_on' in parse_json_field(c.get('case_topics', [])))
    }
    
    return {
        'total_cases': len(triage_results),
        'score_range': {
            'min': min(scores),
            'max': max(scores),
            'mean': statistics.mean(scores),
            'median': statistics.median(scores),
            'std': statistics.stdev(scores) if len(scores) > 1 else 0,
            'q1': statistics.quantiles(scores, n=4)[0] if len(scores) > 1 else 0,
            'q3': statistics.quantiles(scores, n=4)[2] if len(scores) > 1 else 0
        },
        'high_priority_count': len(high_priority),
        'medium_priority_count': len(medium_priority),
        'low_priority_count': len(low_priority),
        'high_priority_threshold': 8.0,
        'high_priority_characteristics': high_priority_characteristics,
        'score_distribution': {
            'high_priority': {'count': len(high_priority), 'percentage': len(high_priority)/len(scores)*100},
            'medium_priority': {'count': len(medium_priority), 'percentage': len(medium_priority)/len(scores)*100},
            'low_priority': {'count': len(low_priority), 'percentage': len(low_priority)/len(scores)*100}
        },
        'top_10_priority_cases': [
            {
                'case_id': case.get('id'),
                'priority_score': case.get('priority_score'),
                'severity_indicators': parse_json_field(case.get('severity_indicators', [])),
                'victim_count': case.get('victim_count'),
                'case_topics': parse_json_field(case.get('case_topics', []))
            }
            for case in sorted(triage_results, key=lambda x: x.get('priority_score', 0), reverse=True)[:10]
        ]
    }

def evaluate_tag_based_filtering(all_cases: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Evaluate tag-based filtering capabilities"""
    print("  Testing tag-based filtering...")
    
    test_queries = [
        {'tags': [{'tag': 'possession', 'category': 'case_topics'}], 'description': 'Single tag: possession'},
        {'tags': [{'tag': 'production', 'category': 'case_topics'}], 'description': 'Single tag: production'},
        {'tags': [{'tag': 'infant', 'category': 'severity_indicators'}], 'description': 'Single tag: infant'},
        {'tags': [{'tag': 'possession', 'category': 'case_topics'}, {'tag': 'registered_sex_offender', 'category': 'registered_sex_offender'}], 'description': 'Multi-tag: possession AND RSO'},
        {'tags': [{'tag': 'production', 'category': 'case_topics'}, {'tag': 'hands_on', 'category': 'case_topics'}], 'description': 'Multi-tag: production AND hands_on'},
        {'tags': [{'tag': 'family', 'category': 'case_topics'}, {'tag': 'very_young', 'category': 'severity_indicators'}], 'description': 'Multi-tag: family AND very_young'},
    ]
    
    query_results = []
    for query in test_queries:
        matching = return_tagged_cases(all_cases, query['tags'])
        query_results.append({
            'query': query['description'],
            'tags': query['tags'],
            'matches': len(matching),
            'percentage': (len(matching) / len(all_cases) * 100) if all_cases else 0
        })
    
    return {
        'total_test_queries': len(test_queries),
        'query_results': query_results,
        'filtering_capabilities': {
            'supports_single_tag': True,
            'supports_multi_tag_intersection': True,
            'supports_cross_category_filtering': True
        }
    }

def evaluate_similarity_calculation(all_cases: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Evaluate similarity calculation performance"""
    print("  Analyzing similarity calculations...")
    
    # Sample cases for similarity analysis
    sample_size = min(50, len(all_cases))
    sample_cases = all_cases[:sample_size]
    
    similarities = []
    for i, case1 in enumerate(sample_cases):
        for case2 in sample_cases[i+1:]:
            sim = calculate_case_similarity(case1, case2)
            similarities.append(sim)
    
    # Analyze similarity distribution
    similarity_ranges = {
        'very_high': [s for s in similarities if s >= 0.7],
        'high': [s for s in similarities if 0.5 <= s < 0.7],
        'medium': [s for s in similarities if 0.3 <= s < 0.5],
        'low': [s for s in similarities if s < 0.3]
    }
    
    return {
        'sample_size': sample_size,
        'total_pairs_analyzed': len(similarities),
        'similarity_statistics': {
            'mean': statistics.mean(similarities) if similarities else 0.0,
            'median': statistics.median(similarities) if similarities else 0.0,
            'std': statistics.stdev(similarities) if len(similarities) > 1 else 0.0,
            'min': min(similarities) if similarities else 0.0,
            'max': max(similarities) if similarities else 0.0
        },
        'similarity_distribution': {
            'very_high_0.7+': {'count': len(similarity_ranges['very_high']), 'percentage': len(similarity_ranges['very_high'])/len(similarities)*100 if similarities else 0},
            'high_0.5-0.7': {'count': len(similarity_ranges['high']), 'percentage': len(similarity_ranges['high'])/len(similarities)*100 if similarities else 0},
            'medium_0.3-0.5': {'count': len(similarity_ranges['medium']), 'percentage': len(similarity_ranges['medium'])/len(similarities)*100 if similarities else 0},
            'low_<0.3': {'count': len(similarity_ranges['low']), 'percentage': len(similarity_ranges['low'])/len(similarities)*100 if similarities else 0}
        }
    }

def evaluate_insights(all_cases: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Comprehensive automated insights evaluation"""
    print("  Generating automated insights...")
    insights = generate_automated_insights(all_cases)
    
    # Platform analysis
    all_platforms = []
    platform_counts = Counter()
    for case in all_cases:
        platforms = parse_json_field(case.get('platforms_used', []))
        if platforms:
            all_platforms.extend(platforms)
            platform_counts.update(platforms)
    
    # Severity distribution
    all_severity = []
    severity_counts = Counter()
    for case in all_cases:
        severity = parse_json_field(case.get('severity_indicators', []))
        if severity:
            all_severity.extend(severity)
            severity_counts.update(severity)
    
    # Case topics
    all_topics = []
    topic_counts = Counter()
    for case in all_cases:
        topics = parse_json_field(case.get('case_topics', []))
        if topics:
            all_topics.extend(topics)
            topic_counts.update(topics)
    
    # Relationship analysis
    relationship_counts = Counter()
    for case in all_cases:
        rel = case.get('relationship_to_victim')
        if rel:
            relationship_counts[rel] += 1
    
    # RSO count
    rso_count = sum(1 for case in all_cases if case.get('perpetrator_registered_sex_offender') is True)
    
    # Family vs stranger
    family_count = sum(1 for case in all_cases 
                      if 'family' in parse_json_field(case.get('case_topics', [])))
    stranger_count = len(all_cases) - family_count
    
    # Production vs possession
    production_count = sum(1 for case in all_cases 
                          if 'production' in parse_json_field(case.get('case_topics', [])))
    possession_count = sum(1 for case in all_cases 
                          if 'possession' in parse_json_field(case.get('case_topics', [])))
    
    # Hands-on
    hands_on_count = sum(1 for case in all_cases 
                         if 'hands_on' in parse_json_field(case.get('case_topics', [])))
    
    # Multi-state
    multi_state_count = sum(1 for case in all_cases 
                           if 'multi_state' in parse_json_field(case.get('case_topics', [])))
    
    # Investigation type distribution
    investigation_dist = Counter()
    for case in all_cases:
        inv_type = case.get('investigation_type')
        if inv_type:
            investigation_dist[inv_type] += 1
    
    # Very young and infant
    very_young_count = severity_counts.get('very_young', 0)
    infant_count = severity_counts.get('infant', 0)
    sexual_assault_count = severity_counts.get('sexual_assault', 0)
    under_10_count = severity_counts.get('under_10', 0)
    
    total = len(all_cases)
    
    return {
        'platform_analysis': {
            'top_platforms': dict(platform_counts.most_common(10)),
            'total_platform_mentions': len(all_platforms),
            'unique_platforms': len(platform_counts),
            'cases_with_platforms': sum(1 for case in all_cases if parse_json_field(case.get('platforms_used', [])))
        },
        'severity_distribution': {
            'production': production_count,
            'very_young': very_young_count,
            'infant': infant_count,
            'sexual_assault': sexual_assault_count,
            'under_10': under_10_count,
            'total_cases': total,
            'all_severity_indicators': dict(severity_counts)
        },
        'case_topics': {
            'family': family_count,
            'stranger': stranger_count,
            'production': production_count,
            'possession': possession_count,
            'hands_on': hands_on_count,
            'multi_state': multi_state_count,
            'total_cases': total,
            'all_topics': dict(topic_counts)
        },
        'relationship_analysis': {
            'distribution': dict(relationship_counts),
            'family_vs_stranger': {
                'family': family_count,
                'stranger': stranger_count,
                'family_percentage': (family_count / total * 100) if total > 0 else 0,
                'stranger_percentage': (stranger_count / total * 100) if total > 0 else 0
            }
        },
        'pattern_detection': {
            'registered_sex_offenders': rso_count,
            'rso_percentage': (rso_count / total * 100) if total > 0 else 0,
            'total_cases': total
        },
        'investigation_analysis': {
            'distribution': dict(investigation_dist),
            'total_with_investigation_type': sum(investigation_dist.values())
        },
        'automated_insights': insights
    }

def extract_keywords(all_cases: List[Dict[str, Any]], top_n: int = 20) -> Dict[str, Any]:
    """Extract and analyze keywords from case text"""
    from analysis import extract_keywords_semantic
    
    all_keywords = []
    case_keyword_counts = []
    
    for case in all_cases:
        case_text = case.get('case_text', '') or (case.get('raw_data', {}) if isinstance(case.get('raw_data'), dict) else {}).get('case_text', '')
        if not case_text and isinstance(case.get('raw_data'), str):
            try:
                raw_data = json.loads(case['raw_data'])
                case_text = raw_data.get('case_text', '')
            except:
                pass
        
        if case_text:
            keywords = extract_keywords_semantic(case_text, top_n=top_n)
            all_keywords.extend(keywords)
            case_keyword_counts.append(len(keywords))
    
    keyword_counts = Counter(all_keywords)
    
    return {
        'top_keywords': [word for word, count in keyword_counts.most_common(top_n)],
        'keyword_frequencies': dict(keyword_counts.most_common(top_n)),
        'total_keywords_extracted': len(all_keywords),
        'unique_keywords': len(keyword_counts),
        'average_keywords_per_case': statistics.mean(case_keyword_counts) if case_keyword_counts else 0,
        'cases_with_text': len(case_keyword_counts)
    }

def evaluate_data_quality(all_cases: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Evaluate overall data quality and completeness"""
    total = len(all_cases)
    
    completeness_scores = []
    for case in all_cases:
        score = 0
        max_score = 10
        
        if parse_json_field(case.get('case_topics', [])): score += 1
        if parse_json_field(case.get('severity_indicators', [])): score += 1
        if case.get('prosecution_outcome'): score += 1
        if case.get('relationship_to_victim'): score += 1
        if parse_json_field(case.get('platforms_used', [])): score += 1
        if case.get('investigation_type'): score += 1
        if case.get('victim_count') is not None: score += 1
        if case.get('perpetrator_age') is not None or case.get('perpetrator_registered_sex_offender') is not None: score += 1
        if case.get('evidence_volume'): score += 1
        if case.get('date_start') or case.get('date_range'): score += 1
        
        completeness_scores.append(score / max_score * 100)
    
    return {
        'average_completeness': statistics.mean(completeness_scores) if completeness_scores else 0,
        'completeness_distribution': {
            'high_80-100': sum(1 for s in completeness_scores if s >= 80),
            'medium_50-80': sum(1 for s in completeness_scores if 50 <= s < 80),
            'low_<50': sum(1 for s in completeness_scores if s < 50)
        },
        'total_cases': total
    }

def evaluate_system_performance(all_cases: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Evaluate system performance metrics"""
    import time
    
    performance = {}
    
    # Clustering performance
    start = time.time()
    groups = group_similar_cases(all_cases)
    performance['clustering_time'] = time.time() - start
    performance['clustering_cases_per_second'] = len(all_cases) / performance['clustering_time'] if performance['clustering_time'] > 0 else 0
    
    # Triage performance
    start = time.time()
    triage_cases(all_cases)
    performance['triage_time'] = time.time() - start
    performance['triage_cases_per_second'] = len(all_cases) / performance['triage_time'] if performance['triage_time'] > 0 else 0
    
    # Insights performance
    start = time.time()
    generate_automated_insights(all_cases)
    performance['insights_time'] = time.time() - start
    performance['insights_cases_per_second'] = len(all_cases) / performance['insights_time'] if performance['insights_time'] > 0 else 0
    
    # Full analysis performance
    start = time.time()
    run_automated_analysis(all_cases)
    performance['full_analysis_time'] = time.time() - start
    performance['full_analysis_cases_per_second'] = len(all_cases) / performance['full_analysis_time'] if performance['full_analysis_time'] > 0 else 0
    
    return performance

def generate_use_case_examples(all_cases: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Generate example use cases demonstrating system capabilities"""
    
    # Example 1: Find high-priority cases
    triage_results = triage_cases(all_cases)
    high_priority = [c for c in triage_results if c.get('priority_score', 0) >= 8.0][:3]
    
    # Example 2: Find cases with specific tag combinations
    possession_rso = return_tagged_cases(all_cases, [
        {'tag': 'possession', 'category': 'case_topics'},
        {'tag': 'registered_sex_offender', 'category': 'registered_sex_offender'}
    ])
    
    # Example 3: Find production cases
    production_cases = return_tagged_cases(all_cases, [
        {'tag': 'production', 'category': 'case_topics'}
    ])
    
    return {
        'use_case_1_high_priority_triage': {
            'description': 'Identify highest priority cases requiring immediate attention',
            'query': 'Priority score >= 8.0',
            'results_count': len(high_priority),
            'example_cases': [
                {
                    'case_id': c.get('id'),
                    'priority_score': c.get('priority_score'),
                    'key_characteristics': {
                        'severity': parse_json_field(c.get('severity_indicators', [])),
                        'victim_count': c.get('victim_count'),
                        'topics': parse_json_field(c.get('case_topics', []))
                    }
                }
                for c in high_priority[:3]
            ]
        },
        'use_case_2_tag_combination_filtering': {
            'description': 'Find cases matching multiple criteria (possession AND registered sex offender)',
            'query': 'possession AND registered_sex_offender',
            'results_count': len(possession_rso),
            'example_cases': [
                {
                    'case_id': c.get('id'),
                    'relationship': c.get('relationship_to_victim'),
                    'platforms': parse_json_field(c.get('platforms_used', []))
                }
                for c in possession_rso[:3]
            ]
        },
        'use_case_3_production_case_analysis': {
            'description': 'Analyze all production cases',
            'query': 'production',
            'results_count': len(production_cases),
            'statistics': {
                'with_hands_on': sum(1 for c in production_cases if 'hands_on' in parse_json_field(c.get('case_topics', []))),
                'with_infant': sum(1 for c in production_cases if 'infant' in parse_json_field(c.get('severity_indicators', []))),
                'with_multiple_victims': sum(1 for c in production_cases if (c.get('victim_count') or 0) > 1)
            }
        }
    }

def main():
    print("="*80)
    print("CaseLinker Comprehensive Evaluation")
    print("="*80)
    print(f"Evaluation Date: {datetime.now().isoformat()}")
    print()
    
    # Load cases
    db_path = "caselinker.db"
    if not Path(db_path).exists():
        print(f"ERROR: Database {db_path} not found!")
        return
    
    all_cases = load_all_cases(db_path)
    
    if not all_cases:
        print("ERROR: No cases found in database!")
        return
    
    print(f"\nTotal cases in database: {len(all_cases)}")
    print()
    
    # Run comprehensive evaluations
    results = {
        'metadata': {
            'evaluation_date': datetime.now().isoformat(),
            'total_cases': len(all_cases),
            'database_path': db_path,
            'system_version': 'CaseLinker v1.0'
        },
        'extraction_coverage': {},
        'clustering': {},
        'triage': {},
        'tag_based_filtering': {},
        'similarity_calculation': {},
        'insights': {},
        'keywords': {},
        'data_quality': {},
        'system_performance': {},
        'use_case_examples': {}
    }
    
    print("="*80)
    print("1. Extraction Coverage Evaluation")
    print("="*80)
    results['extraction_coverage'] = evaluate_extraction_coverage(all_cases)
    for key, data in results['extraction_coverage'].items():
        if isinstance(data, dict) and 'percentage' in data:
            print(f"  {key}: {data['extracted']}/{data['total']} ({data['percentage']:.1f}%)")
    
    print("\n" + "="*80)
    print("2. Clustering Evaluation")
    print("="*80)
    results['clustering'] = evaluate_clustering(all_cases)
    print(f"  Total groups: {results['clustering']['total_groups']}")
    for group in results['clustering']['groups']:
        print(f"    - {group['name']}: {group['size']} cases, avg similarity: {group['average_similarity']:.3f}")
    
    print("\n" + "="*80)
    print("3. Priority Triage Evaluation")
    print("="*80)
    results['triage'] = evaluate_triage(all_cases)
    print(f"  Total cases: {results['triage']['total_cases']}")
    print(f"  Score range: {results['triage']['score_range']['min']:.1f} - {results['triage']['score_range']['max']:.1f}")
    print(f"  Mean: {results['triage']['score_range']['mean']:.2f}, Std: {results['triage']['score_range']['std']:.2f}")
    print(f"  High-priority cases (≥8.0): {results['triage']['high_priority_count']}")
    
    print("\n" + "="*80)
    print("4. Tag-Based Filtering Evaluation")
    print("="*80)
    results['tag_based_filtering'] = evaluate_tag_based_filtering(all_cases)
    print(f"  Test queries: {results['tag_based_filtering']['total_test_queries']}")
    for query in results['tag_based_filtering']['query_results']:
        print(f"    - {query['query']}: {query['matches']} matches ({query['percentage']:.1f}%)")
    
    print("\n" + "="*80)
    print("5. Similarity Calculation Evaluation")
    print("="*80)
    results['similarity_calculation'] = evaluate_similarity_calculation(all_cases)
    print(f"  Sample size: {results['similarity_calculation']['sample_size']}")
    print(f"  Mean similarity: {results['similarity_calculation']['similarity_statistics']['mean']:.3f}")
    
    print("\n" + "="*80)
    print("6. Automated Insights Evaluation")
    print("="*80)
    results['insights'] = evaluate_insights(all_cases)
    print(f"  Top platform: {list(results['insights']['platform_analysis']['top_platforms'].keys())[0] if results['insights']['platform_analysis']['top_platforms'] else 'N/A'}")
    print(f"  Registered sex offenders: {results['insights']['pattern_detection']['registered_sex_offenders']} cases")
    
    print("\n" + "="*80)
    print("7. Keyword Extraction")
    print("="*80)
    results['keywords'] = extract_keywords(all_cases, top_n=20)
    print(f"  Top keywords: {', '.join(results['keywords']['top_keywords'][:10])}")
    
    print("\n" + "="*80)
    print("8. Data Quality Evaluation")
    print("="*80)
    results['data_quality'] = evaluate_data_quality(all_cases)
    print(f"  Average completeness: {results['data_quality']['average_completeness']:.1f}%")
    
    print("\n" + "="*80)
    print("9. System Performance Evaluation")
    print("="*80)
    results['system_performance'] = evaluate_system_performance(all_cases)
    print(f"  Clustering time: {results['system_performance']['clustering_time']:.2f}s")
    print(f"  Full analysis time: {results['system_performance']['full_analysis_time']:.2f}s")
    
    print("\n" + "="*80)
    print("10. Use Case Examples")
    print("="*80)
    results['use_case_examples'] = generate_use_case_examples(all_cases)
    print(f"  Generated {len(results['use_case_examples'])} use case examples")
    
    # Save comprehensive results
    output_file = 'evaluation_results.json'
    with open(output_file, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    
    print("\n" + "="*80)
    print(f"✓ Comprehensive evaluation results saved to {output_file}")
    print("="*80)
    print(f"\nFile size: {Path(output_file).stat().st_size / 1024:.1f} KB")
    print(f"Total evaluation metrics: {sum(1 for _ in _flatten_dict(results))} data points")
    print("="*80)

def _flatten_dict(d, parent_key='', sep='.'):
    """Helper to count nested dict items"""
    items = []
    for k, v in d.items():
        new_key = f"{parent_key}{sep}{k}" if parent_key else k
        if isinstance(v, dict):
            items.extend(_flatten_dict(v, new_key, sep=sep))
        else:
            items.append(new_key)
    return items

if __name__ == "__main__":
    main()
