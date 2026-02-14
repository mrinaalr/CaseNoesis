"""
Visualization Layer

Purpose: Present case data, clusters, and trends in an interactive, tasteful, and informative way.

Design Ideas from Architecture:
Most important part of project:
- Filtering: analyze all cases based on what interests you
- Clustering: visually grouping similar cases (or even filtered content like platforms)
- Interactive components (think HCI and data visualization class)
- Interactive dashboards
- Graphs (!!)
- Filtering
- Expandable case/data views
"""

from typing import List, Dict, Any, Optional, Tuple
from collections import Counter, defaultdict
from datetime import datetime


def create_timeline_visualization(cases: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Create timeline visualization of cases over time.
    
    Args:
        cases: List of cases with date information
        
    Returns:
        Timeline data for visualization
    """
    timeline_events = []
    
    for case in cases:
        date_range = case.get('date_range', {})
        if isinstance(date_range, dict):
            date_start = date_range.get('start')
            date_end = date_range.get('end') or date_start
            
            if date_start:
                event = {
                    'case_id': case.get('id'),
                    'start': date_start,
                    'end': date_end,
                    'source': case.get('source', 'unknown'),
                    'platforms': case.get('platforms_used', []),
                    'topics': case.get('case_topics', []),
                    'label': f"Case {case.get('id', 'Unknown')}"
                }
                timeline_events.append(event)
    
    time_periods = defaultdict(list)
    for event in timeline_events:
        try:
            date_obj = datetime.fromisoformat(event['start']) if isinstance(event['start'], str) else event['start']
            year = date_obj.year
            time_periods[year].append(event)
        except:
            pass
    
    return {
        'events': timeline_events,
        'time_periods': dict(time_periods),
        'metadata': {
            'total_events': len(timeline_events),
            'date_range': {
                'start': min(e['start'] for e in timeline_events) if timeline_events else None,
                'end': max(e['end'] for e in timeline_events) if timeline_events else None
            }
        }
    }


def filter_cases(all_cases: List[Dict[str, Any]], filters: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Filter cases based on criteria.
    Analyze all cases based on what interests you - core filtering functionality.
    
    Args:
        all_cases: List of all cases
        filters: Dictionary with filter criteria:
            - date_range: {start, end}
            - source: source name
            - platform: platform name(s)
            - topics: topic name(s)
            - region: region name
            - severity: severity indicators
            - victim_count: min/max victim count
            - perpetrator_count: min/max perpetrator count
            
    Returns:
        Filtered list of cases
    """
    filtered = all_cases.copy()
    
    if 'source' in filters:
        filtered = [c for c in filtered if c.get('source') == filters['source']]
    
    if 'date_range' in filters:
        filter_date = filters['date_range']
        date_filtered = []
        for case in filtered:
            case_date = case.get('date_range', {})
            if isinstance(case_date, dict) and isinstance(filter_date, dict):
                case_start = case_date.get('start')
                filter_start = filter_date.get('start')
                filter_end = filter_date.get('end')
                
                if case_start:
                    try:
                        case_dt = datetime.fromisoformat(case_start) if isinstance(case_start, str) else case_start
                        if filter_start:
                            filter_start_dt = datetime.fromisoformat(filter_start) if isinstance(filter_start, str) else filter_start
                            if case_dt < filter_start_dt:
                                continue
                        if filter_end:
                            filter_end_dt = datetime.fromisoformat(filter_end) if isinstance(filter_end, str) else filter_end
                            if case_dt > filter_end_dt:
                                continue
                        date_filtered.append(case)
                    except:
                        pass
        filtered = date_filtered
    
    if 'platform' in filters or 'platforms' in filters:
        platforms_filter = filters.get('platforms', filters.get('platform', []))
        if not isinstance(platforms_filter, list):
            platforms_filter = [platforms_filter]
        platforms_set = set(platforms_filter)
        filtered = [c for c in filtered 
                   if set(c.get('platforms_used', [])) & platforms_set]
    
    if 'topic' in filters or 'topics' in filters:
        topics_filter = filters.get('topics', filters.get('topic', []))
        if not isinstance(topics_filter, list):
            topics_filter = [topics_filter]
        topics_set = set(topics_filter)
        filtered = [c for c in filtered 
                   if set(c.get('case_topics', [])) & topics_set]
    
    if 'region' in filters:
        region_filter = filters['region']
        region_filtered = []
        for case in filtered:
            victim_demo = case.get('victim_demographics', {})
            perp_demo = case.get('perpetrator_demographics', {})
            if (victim_demo.get('region') == region_filter or 
                perp_demo.get('region') == region_filter):
                region_filtered.append(case)
        filtered = region_filtered
    
    if 'severity' in filters:
        severity_filter = filters['severity']
        if not isinstance(severity_filter, list):
            severity_filter = [severity_filter]
        severity_set = set(severity_filter)
        filtered = [c for c in filtered 
                   if set(c.get('severity_indicators', [])) & severity_set]
    
    if 'victim_count' in filters:
        vc_filter = filters['victim_count']
        if isinstance(vc_filter, dict):
            min_vc = vc_filter.get('min')
            max_vc = vc_filter.get('max')
            filtered = [c for c in filtered 
                       if c.get('victim_count') is not None and
                       (min_vc is None or c.get('victim_count') >= min_vc) and
                       (max_vc is None or c.get('victim_count') <= max_vc)]
    
    if 'perpetrator_count' in filters:
        pc_filter = filters['perpetrator_count']
        if isinstance(pc_filter, dict):
            min_pc = pc_filter.get('min')
            max_pc = pc_filter.get('max')
            filtered = [c for c in filtered 
                       if c.get('perpetrator_count') is not None and
                       (min_pc is None or c.get('perpetrator_count') >= min_pc) and
                       (max_pc is None or c.get('perpetrator_count') <= max_pc)]
    
    return filtered


def get_date_range(cases: List[Dict[str, Any]]) -> Optional[Dict[str, str]]:
    """
    Get overall date range from cases.
    
    Args:
        cases: List of cases
        
    Returns:
        Date range dictionary or None
    """
    dates = []
    for case in cases:
        date_range = case.get('date_range', {})
        if isinstance(date_range, dict):
            date_start = date_range.get('start')
            if date_start:
                dates.append(date_start)
    
    if dates:
        try:
            date_objs = [datetime.fromisoformat(d) if isinstance(d, str) else d for d in dates]
            return {
                'start': min(date_objs).isoformat(),
                'end': max(date_objs).isoformat()
            }
        except:
            pass
    
    return None
