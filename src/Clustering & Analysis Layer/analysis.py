"""
Clustering & Analysis Layer

Simple tag-based case filtering and retrieval.
Automated analysis with case grouping, triage, and insights.
"""

from typing import List, Dict, Any, Tuple
import json
from collections import Counter, defaultdict
from datetime import datetime


def return_tagged_cases(all_cases: List[Dict[str, Any]], selected_tags: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    """
    Query database and return all cases matching the selected tags.
    
    Args:
        all_cases: List of all cases from database
        selected_tags: List of dictionaries with 'tag' and 'category' keys
            Example: [{'tag': 'production', 'category': 'case_topics'}, {'tag': 'infant', 'category': 'severity_indicators'}]
        
    Returns:
        List of case dictionaries matching ALL selected tags (intersection)
    """
    if not selected_tags:
        return []
    
    matching_cases = []
    for case in all_cases:
        # Case must match ALL selected tags (intersection logic)
        matches_all = True
        
        for tag_info in selected_tags:
            tag = tag_info['tag']
            category = tag_info['category']
            
            matches = False
            
            if category == 'case_topics':
                topics = case.get('case_topics', [])
                matches = isinstance(topics, list) and tag in topics
                
            elif category == 'severity_indicators':
                severity = case.get('severity_indicators', [])
                matches = isinstance(severity, list) and tag in severity
                
            elif category == 'platforms_used':
                platforms = case.get('platforms_used', [])
                matches = isinstance(platforms, list) and any(
                    p and p.lower() == tag.lower() for p in platforms
                )
                
            elif category == 'investigation_type':
                inv_type = case.get('investigation_type', '')
                matches = inv_type and inv_type.lower() == tag.lower()
                
            elif category == 'relationship_to_victim':
                relationship = case.get('relationship_to_victim', '')
                matches = relationship and relationship.lower() == tag.lower()
                
            elif category == 'registered_sex_offender':
                matches = tag == 'registered_sex_offender' and case.get('perpetrator_registered_sex_offender') is True
                
            elif category == 'custom':
                # Search in case text for custom topics
                case_text = (case.get('raw_data', {}).get('case_text', '') or 
                           case.get('case_text', '') or '').lower()
                matches = tag.lower() in case_text
            
            if not matches:
                matches_all = False
                break
        
        if matches_all:
            matching_cases.append(case)
    
    return matching_cases


def tag_threader(all_cases: List[Dict[str, Any]], selected_tags: List[Dict[str, str]]) -> Dict[str, Any]:
    """
    Query database for cases matching selected tags and create threaded tag links.
    
    Args:
        all_cases: List of all cases from database
        selected_tags: List of dictionaries with 'tag' and 'category' keys
        
    Returns:
        Dictionary with:
            - 'intersection_cases': List of case IDs matching ALL tags
            - 'tag_results': List of dictionaries with tag counts
    """
    if not selected_tags:
        return {
            'intersection_cases': [],
            'tag_results': []
        }
    
    # Find cases matching ALL selected tags (intersection)
    intersection_cases = []
    for case in all_cases:
        matches_all = True
        for tag_info in selected_tags:
            tag = tag_info['tag']
            category = tag_info['category']
            
            matches = False
            if category == 'case_topics':
                topics = case.get('case_topics', [])
                matches = isinstance(topics, list) and tag in topics
            elif category == 'severity_indicators':
                severity = case.get('severity_indicators', [])
                matches = isinstance(severity, list) and tag in severity
            elif category == 'platforms_used':
                platforms = case.get('platforms_used', [])
                matches = isinstance(platforms, list) and any(
                    p and p.lower() == tag.lower() for p in platforms
                )
            elif category == 'investigation_type':
                inv_type = case.get('investigation_type', '')
                matches = inv_type and inv_type.lower() == tag.lower()
            elif category == 'relationship_to_victim':
                relationship = case.get('relationship_to_victim', '')
                matches = relationship and relationship.lower() == tag.lower()
            elif category == 'registered_sex_offender':
                matches = tag == 'registered_sex_offender' and case.get('perpetrator_registered_sex_offender') is True
            elif category == 'custom':
                case_text = (case.get('raw_data', {}).get('case_text', '') or 
                           case.get('case_text', '') or '').lower()
                matches = tag.lower() in case_text
            
            if not matches:
                matches_all = False
                break
        
        if matches_all:
            intersection_cases.append(case)
    
    # For each tag, find cases matching that specific tag
    tag_results = []
    for tag_info in selected_tags:
        tag = tag_info['tag']
        category = tag_info['category']
        
        matching_case_ids = []
        for case in all_cases:
            matches = False
            if category == 'case_topics':
                topics = case.get('case_topics', [])
                matches = isinstance(topics, list) and tag in topics
            elif category == 'severity_indicators':
                severity = case.get('severity_indicators', [])
                matches = isinstance(severity, list) and tag in severity
            elif category == 'platforms_used':
                platforms = case.get('platforms_used', [])
                matches = isinstance(platforms, list) and any(
                    p and p.lower() == tag.lower() for p in platforms
                )
            elif category == 'investigation_type':
                inv_type = case.get('investigation_type', '')
                matches = inv_type and inv_type.lower() == tag.lower()
            elif category == 'relationship_to_victim':
                relationship = case.get('relationship_to_victim', '')
                matches = relationship and relationship.lower() == tag.lower()
            elif category == 'registered_sex_offender':
                matches = tag == 'registered_sex_offender' and case.get('perpetrator_registered_sex_offender') is True
            elif category == 'custom':
                case_text = (case.get('raw_data', {}).get('case_text', '') or 
                           case.get('case_text', '') or '').lower()
                matches = tag.lower() in case_text
            
            if matches:
                matching_case_ids.append(case.get('id', ''))
        
        tag_results.append({
            'tag': tag,
            'category': category,
            'count': len(matching_case_ids),
            'cases': matching_case_ids
        })
    
    return {
        'intersection_cases': [c.get('id', '') for c in intersection_cases],
        'tag_results': tag_results
    }


def calculate_case_similarity(case1: Dict[str, Any], case2: Dict[str, Any]) -> float:
    """
    Calculate similarity score between two cases using comparison values.
    Returns a score between 0.0 and 1.0.
    """
    comp1 = case1.get('comparison_values', {})
    comp2 = case2.get('comparison_values', {})
    
    if not comp1 or not comp2:
        return 0.0
    
    similarity_score = 0.0
    weight_sum = 0.0
    
    # Platform similarity (weight: 0.15)
    platforms1 = comp1.get('platform_vector') or []
    platforms2 = comp2.get('platform_vector') or []
    platforms1 = set(platforms1) if isinstance(platforms1, (list, tuple, set)) else set()
    platforms2 = set(platforms2) if isinstance(platforms2, (list, tuple, set)) else set()
    if platforms1 or platforms2:
        platform_sim = len(platforms1 & platforms2) / max(len(platforms1 | platforms2), 1)
        similarity_score += platform_sim * 0.15
        weight_sum += 0.15
    
    # Demographic similarity (weight: 0.20)
    demo1 = comp1.get('demographic_vector', {})
    demo2 = comp2.get('demographic_vector', {})
    demo_sim = 0.0
    demo_count = 0
    
    # Victim age range similarity
    age_range1 = demo1.get('victim_age_range')
    age_range2 = demo2.get('victim_age_range')
    if age_range1 and age_range2:
        overlap = min(age_range1.get('max', 0), age_range2.get('max', 0)) - max(age_range1.get('min', 0), age_range2.get('min', 0))
        range1_size = age_range1.get('max', 0) - age_range1.get('min', 0)
        range2_size = age_range2.get('max', 0) - age_range2.get('min', 0)
        if overlap > 0 and (range1_size + range2_size) > 0:
            demo_sim += overlap / max(range1_size, range2_size)
            demo_count += 1
    
    # Victim count similarity
    vc1 = demo1.get('victim_count')
    vc2 = demo2.get('victim_count')
    if vc1 is not None and vc2 is not None:
        if vc1 == vc2:
            demo_sim += 1.0
        elif max(vc1, vc2) > 0:
            demo_sim += min(vc1, vc2) / max(vc1, vc2)
        demo_count += 1
    
    # Perpetrator age similarity
    pa1 = demo1.get('perpetrator_age')
    pa2 = demo2.get('perpetrator_age')
    if pa1 is not None and pa2 is not None:
        age_diff = abs(pa1 - pa2)
        demo_sim += max(0, 1.0 - age_diff / 20.0)  # Normalize by 20 year difference
        demo_count += 1
    
    # Registered sex offender match
    rso1 = demo1.get('perpetrator_registered', False)
    rso2 = demo2.get('perpetrator_registered', False)
    if rso1 == rso2:
        demo_sim += 1.0
        demo_count += 1
    
    if demo_count > 0:
        similarity_score += (demo_sim / demo_count) * 0.20
        weight_sum += 0.20
    
    # Relationship similarity (weight: 0.10)
    rel1 = comp1.get('relationship_vector') or []
    rel2 = comp2.get('relationship_vector') or []
    rel1 = set(rel1) if isinstance(rel1, (list, tuple, set)) else set()
    rel2 = set(rel2) if isinstance(rel2, (list, tuple, set)) else set()
    if rel1 or rel2:
        rel_sim = 1.0 if rel1 == rel2 else (0.5 if rel1 & rel2 else 0.0)
        similarity_score += rel_sim * 0.10
        weight_sum += 0.10
    
    # Investigation similarity (weight: 0.15)
    inv1 = comp1.get('investigation_vector', {})
    inv2 = comp2.get('investigation_vector', {})
    inv_sim = 0.0
    inv_count = 0
    
    if inv1.get('type') and inv2.get('type'):
        inv_sim += 1.0 if inv1['type'] == inv2['type'] else 0.0
        inv_count += 1
    
    agencies1 = inv1.get('agencies') or []
    agencies2 = inv2.get('agencies') or []
    agencies1 = set(agencies1) if isinstance(agencies1, (list, tuple, set)) else set()
    agencies2 = set(agencies2) if isinstance(agencies2, (list, tuple, set)) else set()
    if agencies1 or agencies2:
        agency_sim = len(agencies1 & agencies2) / max(len(agencies1 | agencies2), 1)
        inv_sim += agency_sim
        inv_count += 1
    
    if inv_count > 0:
        similarity_score += (inv_sim / inv_count) * 0.15
        weight_sum += 0.15
    
    # Topic similarity (weight: 0.25)
    topics1 = comp1.get('topic_vector') or []
    topics2 = comp2.get('topic_vector') or []
    topics1 = set(topics1) if isinstance(topics1, (list, tuple, set)) else set()
    topics2 = set(topics2) if isinstance(topics2, (list, tuple, set)) else set()
    if topics1 or topics2:
        topic_sim = len(topics1 & topics2) / max(len(topics1 | topics2), 1)
        similarity_score += topic_sim * 0.25
        weight_sum += 0.25
    
    # Severity similarity (weight: 0.15)
    severity1 = comp1.get('severity_vector') or []
    severity2 = comp2.get('severity_vector') or []
    severity1 = set(severity1) if isinstance(severity1, (list, tuple, set)) else set()
    severity2 = set(severity2) if isinstance(severity2, (list, tuple, set)) else set()
    if severity1 or severity2:
        severity_sim = len(severity1 & severity2) / max(len(severity1 | severity2), 1)
        similarity_score += severity_sim * 0.15
        weight_sum += 0.15
    
    # Normalize by weight sum
    if weight_sum > 0:
        return similarity_score / weight_sum
    return 0.0


def extract_keywords_semantic(case_text: str, top_n: int = 10) -> List[str]:
    """
    Extract keywords from case text using simple frequency-based approach.
    (KeyBERT alternative - simple but effective for this use case)
    """
    if not case_text:
        return []
    
    # Common stop words to filter
    stop_words = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by', 'from', 'as', 'is', 'was', 'were', 'been', 'be', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could', 'should', 'may', 'might', 'must', 'can', 'this', 'that', 'these', 'those', 'i', 'you', 'he', 'she', 'it', 'we', 'they', 'his', 'her', 'its', 'our', 'their', 'who', 'what', 'where', 'when', 'why', 'how', 'which', 'whom', 'whose'}
    
    # Extract words (3+ characters, alphanumeric)
    words = [w.lower() for w in case_text.split() if len(w) >= 3 and w.isalnum() and w.lower() not in stop_words]
    
    # Count frequencies
    word_counts = Counter(words)
    
    # Return top N keywords
    return [word for word, count in word_counts.most_common(top_n)]


def group_similar_cases(all_cases: List[Dict[str, Any]], similarity_threshold: float = 0.4) -> List[Dict[str, Any]]:
    """
    Group cases by similarity using comparison values.
    Returns list of case groups, each containing similar cases.
    """
    if not all_cases:
        return []
    
    # Parse comparison_values if stored as JSON strings
    for case in all_cases:
        if isinstance(case.get('comparison_values'), str):
            try:
                case['comparison_values'] = json.loads(case['comparison_values'])
            except:
                case['comparison_values'] = {}
        elif not case.get('comparison_values'):
            # Try to reconstruct from extracted_features
            extracted = case.get('extracted_features', {})
            if isinstance(extracted, str):
                try:
                    extracted = json.loads(extracted)
                except:
                    extracted = {}
            
            # Reconstruct comparison_values from extracted features
            # Note: comparison_values should ideally be stored in DB, but if missing, we'll use defaults
            case['comparison_values'] = {}
    
    groups = []
    used_cases = set()
    
    for i, case1 in enumerate(all_cases):
        case1_id = case1.get('id')
        if not case1_id or case1_id in used_cases:
            continue
        
        group = [case1]
        used_cases.add(case1_id)
        
        for j, case2 in enumerate(all_cases[i+1:], start=i+1):
            case2_id = case2.get('id')
            if not case2_id or case2_id in used_cases:
                continue
            
            similarity = calculate_case_similarity(case1, case2)
            if similarity >= similarity_threshold:
                group.append(case2)
                used_cases.add(case2.get('id'))
        
        if len(group) > 1:  # Only return groups with multiple cases
            groups.append({
                'group_id': f"group_{len(groups) + 1}",
                'cases': group,
                'size': len(group),
                'representative_case': group[0]  # First case as representative
            })
    
    return sorted(groups, key=lambda g: g['size'], reverse=True)


def triage_cases(all_cases: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Prioritize cases based on severity indicators, evidence volume, and urgency.
    Returns cases sorted by priority (highest first).
    """
    if not all_cases:
        return []
    
    def calculate_priority_score(case: Dict[str, Any]) -> float:
        score = 0.0
        
        # Severity indicators (weight: 0.35) - Increased to better reflect severity
        severity = case.get('severity_indicators') or []
        if isinstance(severity, str):
            try:
                severity = json.loads(severity)
            except:
                severity = []
        if not isinstance(severity, (list, tuple)):
            severity = []
        
        # Infant cases should be highest priority - but not so high that they override multi-victim cases
        has_infant = 'infant' in severity or any('infant' in str(s).lower() for s in severity)
        has_production_severity = 'production' in severity
        has_very_young = 'very_young' in severity
        
        severity_weights = {
            'infant': 15.0,  # High weight but not excessive
            'rape': 18.0,  # Very high weight - rape is extremely severe
            'very_young': 10.0,  # Increased - very young is also critical
            'under_10': 7.0,  # Increased
            'under_5': 8.0,  # Keep for backward compatibility
            'under_9': 6.0,  # Keep for backward compatibility
            'under_7': 6.0,  # Keep for backward compatibility
            'production': 12.0,  # Increased - production severity is very serious
        }
        
        # Calculate base severity score
        severity_base = 0.0
        for sev in severity:
            severity_base += severity_weights.get(sev, 3.0)
        
        # Bonus for multiple severity indicators (compound severity)
        if len(severity) >= 2:
            severity_base += 5.0  # Bonus for multiple indicators
        if len(severity) >= 3:
            severity_base += 3.0  # Additional bonus for 3+ indicators
        
        # Special boost for infant cases (but not excessive)
        if has_infant:
            severity_base += 8.0  # Reduced from 15.0 - still high but not excessive
        
        score += severity_base * 0.35  # Increased weight from 0.30
        
        # Evidence volume (weight: 0.10) - Reduced further
        evidence = case.get('evidence_volume') or {}
        if isinstance(evidence, str):
            try:
                evidence = json.loads(evidence)
            except:
                evidence = {}
        if not isinstance(evidence, dict):
            evidence = {}
        
        if evidence:
            images = evidence.get('images') or 0
            videos = evidence.get('videos') or 0
            storage = evidence.get('storage_size') or ''
            
            # Normalize evidence score
            evidence_score = min(images / 100.0, 1.0) * 5.0 + min(videos / 10.0, 1.0) * 5.0
            if storage and ('TB' in storage or 'terabyte' in storage.lower()):
                evidence_score += 5.0
            elif storage and ('GB' in storage or 'gigabyte' in storage.lower()):
                evidence_score += 2.0
            
            score += evidence_score * 0.10  # Reduced from 0.15
        
        # Victim count (weight: 0.30) - Increased significantly - multiple victims is critical
        victim_count = case.get('victim_count')
        if victim_count:
            # Much more aggressive scoring for multiple victims
            if victim_count >= 10:
                score += 15.0 * 0.30  # Extremely high priority for 10+ victims
            elif victim_count >= 7:
                score += 12.0 * 0.30  # Very high priority for 7-9 victims
            elif victim_count >= 5:
                score += 10.0 * 0.30  # High priority for 5-6 victims (increased from 8.0)
            elif victim_count >= 3:
                score += 7.0 * 0.30  # Medium-high for 3-4 victims (increased from 6.0)
            elif victim_count >= 2:
                score += 4.0 * 0.30  # Medium for 2 victims
            else:
                score += 2.0 * 0.30  # Lower for single victim
        
        # Registered sex offender (weight: 0.10)
        if case.get('perpetrator_registered_sex_offender'):
            score += 4.0 * 0.10  # Increased from 3.0
        
        # Case type severity (weight: 0.25) - Increased - production and hands-on are critical
        case_topics = case.get('case_topics') or []
        if isinstance(case_topics, str):
            try:
                case_topics = json.loads(case_topics)
            except:
                case_topics = []
        if not isinstance(case_topics, list):
            case_topics = []
        
        case_type_score = 0.0
        # Allow multiple case types to compound
        if 'production' in case_topics:
            case_type_score += 10.0  # Increased from 8.0
        if 'hands_on' in case_topics:
            case_type_score += 8.0  # Increased from 6.0, and can stack with production
        if 'possession' in case_topics:
            case_type_score += 2.0  # Lower priority
        if 'online_only' in case_topics:
            case_type_score += 1.0  # Lowest priority
        
        score += case_type_score * 0.25  # Increased weight from 0.20
        
        # Severity phrases (weight: 0.15) - Non-traditional indicators of high severity
        severity_phrases = case.get('severity_phrases') or []
        if isinstance(severity_phrases, str):
            try:
                severity_phrases = json.loads(severity_phrases)
            except:
                severity_phrases = []
        if not isinstance(severity_phrases, (list, tuple)):
            severity_phrases = []
        
        # Weight different phrases based on severity indication
        phrase_weights = {
            'dangerous': 4.0,  # High - indicates dangerous behavior
            'out_of_control': 4.0,  # High - escalation indicator
            'attacked': 5.0,  # Very high - physical violence
            'continue': 3.0,  # Medium-high - ongoing abuse
            'stated': 2.0,  # Medium - victim disclosure
            'told': 2.0,  # Medium - victim disclosure
        }
        
        phrase_score = 0.0
        for phrase in severity_phrases:
            phrase_score += phrase_weights.get(phrase, 1.0)
        
        # Bonus for multiple phrases (compound severity)
        if len(severity_phrases) >= 2:
            phrase_score += 2.0  # Bonus for multiple indicators
        if len(severity_phrases) >= 3:
            phrase_score += 3.0  # Additional bonus for 3+ phrases
        
        score += phrase_score * 0.15  # Weight: 15% of total score
        
        return score
    
    # Calculate priority for each case
    cases_with_priority = []
    for case in all_cases:
        priority = calculate_priority_score(case)
        cases_with_priority.append({
            **case,
            'priority_score': priority
        })
    
    # Normalize scores to 5-10 scale
    if cases_with_priority:
        scores = [c['priority_score'] for c in cases_with_priority]
        min_score = min(scores)
        max_score = max(scores)
        
        # Scale to 5-10 range: min_score -> 5, max_score -> 10
        if max_score > min_score:  # Avoid division by zero
            for case in cases_with_priority:
                raw_score = case['priority_score']
                # Linear scaling: (score - min) / (max - min) maps to 0-1, then scale to 5-10
                normalized = 5.0 + (raw_score - min_score) * 5.0 / (max_score - min_score)
                case['priority_score'] = round(normalized, 2)
                case['priority_score_raw'] = raw_score  # Keep raw score for reference
        else:
            # All scores are the same, set all to 7.5 (middle of 5-10)
            for case in cases_with_priority:
                case['priority_score'] = 7.5
                case['priority_score_raw'] = case['priority_score']
    
    # Sort by priority (highest first)
    return sorted(cases_with_priority, key=lambda c: c['priority_score'], reverse=True)


def generate_automated_insights(all_cases: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Generate automated insights about patterns, trends, and anomalies.
    """
    if not all_cases:
        return {'insights': [], 'patterns': [], 'trends': []}
    
    insights = []
    patterns = []
    trends = []
    
    # Parse JSON strings
    for case in all_cases:
        for key in ['platforms_used', 'severity_indicators', 'case_topics', 'agencies_involved']:
            if isinstance(case.get(key), str):
                try:
                    case[key] = json.loads(case[key])
                except:
                    case[key] = []
    
    # Insight 1: Most common platforms
    all_platforms = []
    for case in all_cases:
        platforms = case.get('platforms_used') or []
        if isinstance(platforms, list):
            all_platforms.extend(platforms)
    
    if all_platforms:
        platform_counts = Counter(all_platforms)
        top_platform = platform_counts.most_common(1)[0]
        insights.append({
            'type': 'platform_analysis',
            'title': 'Most Common Platform',
            'description': f"'{top_platform[0]}' appears in {top_platform[1]} cases ({top_platform[1]/len(all_cases)*100:.1f}% of all cases)",
            'severity': 'info'
        })
    
    # Insight 2: Severity distribution
    all_severity = []
    for case in all_cases:
        severity = case.get('severity_indicators') or []
        if isinstance(severity, list):
            all_severity.extend(severity)
    
    if all_severity:
        severity_counts = Counter(all_severity)
        high_severity = ['infant', 'very_young', 'under_5', 'production']
        high_sev_count = sum(severity_counts.get(sev, 0) for sev in high_severity)
        if high_sev_count > 0:
            insights.append({
                'type': 'severity_analysis',
                'title': 'High Severity Cases',
                'description': f"{high_sev_count} cases involve high-severity indicators (infant, very young, under 5, or production)",
                'severity': 'warning'
            })
    
    # Insight 3: Case topics distribution
    all_topics = []
    for case in all_cases:
        topics = case.get('case_topics') or []
        if isinstance(topics, list):
            all_topics.extend(topics)
    
    if all_topics:
        topic_counts = Counter(all_topics)
        top_topic = topic_counts.most_common(1)[0]
        insights.append({
            'type': 'topic_analysis',
            'title': 'Most Common Case Topic',
            'description': f"'{top_topic[0].replace('_', ' ').title()}' appears in {top_topic[1]} cases",
            'severity': 'info'
        })
    
    # Pattern: Registered sex offenders
    rso_count = sum(1 for case in all_cases if case.get('perpetrator_registered_sex_offender'))
    if rso_count > 0:
        patterns.append({
            'pattern': 'repeat_offenders',
            'description': f"{rso_count} cases ({rso_count/len(all_cases)*100:.1f}%) involve registered sex offenders",
            'count': rso_count
        })
    
    # Pattern: Family vs stranger relationship
    family_count = sum(1 for case in all_cases if 'family' in (case.get('case_topics') or []))
    stranger_count = len(all_cases) - family_count  # Total cases minus family cases
    if family_count > stranger_count:
        patterns.append({
            'pattern': 'relationship_pattern',
            'description': f"Family-related cases ({family_count}) outnumber stranger cases ({stranger_count})",
            'count': family_count
        })
    elif stranger_count > family_count:
        patterns.append({
            'pattern': 'relationship_pattern',
            'description': f"Stranger cases ({stranger_count}) outnumber family-related cases ({family_count})",
            'count': stranger_count
        })
    
    # Pattern: Investigation type distribution
    investigation_types = {}
    for case in all_cases:
        inv_type = case.get('investigation_type')
        if inv_type:
            investigation_types[inv_type] = investigation_types.get(inv_type, 0) + 1
    
    if investigation_types:
        most_common_inv = max(investigation_types.items(), key=lambda x: x[1])
        if most_common_inv[1] > len(all_cases) * 0.4:  # If >40% of cases
            patterns.append({
                'pattern': 'investigation_focus',
                'description': f"{most_common_inv[1]} cases ({most_common_inv[1]/len(all_cases)*100:.1f}%) involve '{most_common_inv[0]}' investigations, indicating a focus area",
                'count': most_common_inv[1]
            })
    
    # Trend: Temporal distribution
    dates = []
    for case in all_cases:
        date_start = case.get('date_start')
        if date_start:
            try:
                dates.append(datetime.fromisoformat(date_start.replace('Z', '+00:00')))
            except:
                pass
    
    if len(dates) > 1:
        dates.sort()
        date_range = (dates[-1] - dates[0]).days
        if date_range > 0:
            trends.append({
                'trend': 'temporal_span',
                'description': f"Cases span {date_range} days ({len(dates)} cases over {date_range/365:.1f} years)",
                'start_date': dates[0].isoformat(),
                'end_date': dates[-1].isoformat()
            })
    
    # Trend: Investigation type distribution
    inv_types = []
    for case in all_cases:
        inv_type = case.get('investigation_type')
        if inv_type:
            inv_types.append(inv_type)
    
    if inv_types:
        inv_counts = Counter(inv_types)
        top_inv = inv_counts.most_common(1)[0]
        trends.append({
            'trend': 'investigation_type',
            'description': f"Most common investigation type: '{top_inv[0]}' ({top_inv[1]} cases)",
            'count': top_inv[1]
        })
    
    return {
        'insights': insights,
        'patterns': patterns,
        'trends': trends,
        'summary': {
            'total_cases': len(all_cases),
            'total_insights': len(insights),
            'total_patterns': len(patterns),
            'total_trends': len(trends)
        }
    }


def run_automated_analysis(all_cases: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Run complete automated analysis pipeline.
    Combines case grouping, triage, and insights generation.
    
    Args:
        all_cases: List of all cases from database
        
    Returns:
        Dictionary containing:
            - case_groups: List of similar case groups
            - triaged_cases: Cases sorted by priority
            - insights: Automated insights and patterns
            - summary: Analysis summary statistics
    """
    if not all_cases:
        return {
            'case_groups': [],
            'triaged_cases': [],
            'insights': {'insights': [], 'patterns': [], 'trends': []},
            'summary': {'total_cases': 0}
        }
    
    # 1. Group similar cases
    case_groups = group_similar_cases(all_cases, similarity_threshold=0.35)
    
    # 2. Triage cases by priority
    triaged_cases = triage_cases(all_cases)
    
    # 3. Generate insights
    insights = generate_automated_insights(all_cases)
    
    # 4. Extract keywords for semantic analysis
    semantic_keywords = []
    for case in all_cases[:10]:  # Sample first 10 cases for keywords
        case_text = case.get('raw_data', {}).get('case_text', '') if isinstance(case.get('raw_data'), dict) else ''
        if not case_text and isinstance(case.get('raw_data'), str):
            try:
                raw_data = json.loads(case['raw_data'])
                case_text = raw_data.get('case_text', '')
            except:
                pass
        
        if case_text:
            keywords = extract_keywords_semantic(case_text, top_n=5)
            semantic_keywords.extend(keywords)
    
    top_keywords = Counter(semantic_keywords).most_common(10)
    
    return {
        'case_groups': case_groups,
        'triaged_cases': triaged_cases[:20],  # Top 20 priority cases
        'insights': insights,
        'semantic_keywords': [{'keyword': kw, 'frequency': freq} for kw, freq in top_keywords],
        'summary': {
            'total_cases': len(all_cases),
            'total_groups': len(case_groups),
            'high_priority_cases': len([c for c in triaged_cases if c.get('priority_score', 0) > 5.0]),
            'average_priority': sum(c.get('priority_score', 0) for c in triaged_cases) / len(triaged_cases) if triaged_cases else 0.0
        }
    }
