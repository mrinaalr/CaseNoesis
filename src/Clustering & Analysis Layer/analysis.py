"""
Clustering & Analysis Layer

Simple tag-based case filtering and retrieval.
"""

from typing import List, Dict, Any


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
