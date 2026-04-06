#!/usr/bin/env python3
"""
Analyze dataset statistics and verify claims about the CaseLinker dataset.

This script provides comprehensive statistics and verification of data claims.
"""
import os
import sys
from pathlib import Path
from collections import Counter, defaultdict
from typing import Dict, List, Any
import json

# Add paths
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src" / "Storage Layer"))

# Try PostgreSQL first, fallback to SQLite
if os.getenv("DATABASE_URL"):
    from storage_postgres import CaseStorage
    storage = CaseStorage()
else:
    from storage import CaseStorage
    db_path = project_root / "caselinker.db"
    storage = CaseStorage(str(db_path))


def _perpetrator_age_bin_label(age: int) -> str:
    """Match run/main.py Perpetrator Age chart binning."""
    if 18 <= age <= 19:
        return "18-19"
    lo = (age // 5) * 5
    return f"{lo}-{lo + 4}"


def analyze_age_ranges(cases: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Analyze age range distributions and identify discrepancies."""
    print("\n" + "="*80)
    print("AGE RANGE ANALYSIS")
    print("="*80)
    
    # Count individual age occurrences (like bubble chart)
    age_counter = Counter()
    cases_with_age = []
    
    for case in cases:
        ages = case.get('perpetrator_age')
        if ages:
            case_ages = []
            if isinstance(ages, list):
                for age in ages:
                    if isinstance(age, (int, float)) and 18 <= age <= 99:
                        age_counter[int(age)] += 1
                        case_ages.append(int(age))
            elif isinstance(ages, (int, float)) and 18 <= ages <= 99:
                age_counter[int(ages)] += 1
                case_ages.append(int(ages))
            
            if case_ages:
                cases_with_age.append({
                    'case_id': case.get('id'),
                    'ages': case_ages
                })
    
    # Group into bins (like bubble chart)
    age_bins = {}
    for age, count in age_counter.items():
        bin_key = _perpetrator_age_bin_label(age)
        age_bins[bin_key] = age_bins.get(bin_key, 0) + count
    
    # Count cases per bin (like filter)
    case_bins = defaultdict(set)
    for case_info in cases_with_age:
        for age in case_info['ages']:
            bin_key = _perpetrator_age_bin_label(age)
            case_bins[bin_key].add(case_info['case_id'])
    
    print(f"\nTotal cases with age data: {len(cases_with_age)}")
    print(f"Total age occurrences: {sum(age_counter.values())}")
    print(f"\nAge Range Distribution (Bubble Chart Method - counts occurrences):")
    print("-" * 80)
    
    discrepancies = []
    for bin_key in sorted(age_bins.keys(), key=lambda x: int(x.split('-')[0])):
        occurrence_count = age_bins[bin_key]
        case_count = len(case_bins[bin_key])
        diff = occurrence_count - case_count
        
        print(f"  {bin_key:10} | Occurrences: {occurrence_count:3} | Cases: {case_count:3} | Diff: {diff:+3}")
        
        if diff != 0:
            discrepancies.append({
                'range': bin_key,
                'occurrences': occurrence_count,
                'cases': case_count,
                'diff': diff
            })
    
    if discrepancies:
        print(f"\n⚠️  DISCREPANCIES FOUND: {len(discrepancies)} age ranges have mismatches")
        print("\nThis happens because:")
        print("  - Bubble chart counts individual age occurrences")
        print("  - Filter counts unique cases")
        print("  - Cases with multiple perpetrators in same age range are counted multiple times in bubbles")
        
        print("\nExample cases causing discrepancies:")
        for disc in discrepancies[:5]:  # Show first 5
            bin_min, bin_max = map(int, disc['range'].split('-'))
            matching_cases = [
                c for c in cases_with_age
                if any(bin_min <= age <= bin_max for age in c['ages'])
            ]
            multi_age_cases = [c for c in matching_cases if len(c['ages']) > 1]
            if multi_age_cases:
                print(f"\n  {disc['range']}: {len(multi_age_cases)} cases have multiple ages")
                for case_info in multi_age_cases[:3]:
                    print(f"    - {case_info['case_id']}: ages {case_info['ages']}")
    
    return {
        'age_bins': age_bins,
        'case_bins': {k: len(v) for k, v in case_bins.items()},
        'discrepancies': discrepancies,
        'total_cases_with_age': len(cases_with_age),
        'total_age_occurrences': sum(age_counter.values())
    }

def analyze_feature_coverage(cases: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Analyze feature coverage across cases."""
    print("\n" + "="*80)
    print("FEATURE COVERAGE ANALYSIS")
    print("="*80)
    
    total_cases = len(cases)
    if total_cases == 0:
        print("No cases found!")
        return {}
    
    features = {
        'perpetrator_age': 0,
        'perpetrator_registered_sex_offender': 0,
        'relationship_to_victim': 0,
        'platforms_used': 0,
        'severity_indicators': 0,
        'case_topics': 0,
        'investigation_type': 0,
        'organizations': 0,
        'prosecution_outcome': 0,
        'victim_demographics': 0,
    }
    
    for case in cases:
        if case.get('perpetrator_age'):
            features['perpetrator_age'] += 1
        if case.get('perpetrator_registered_sex_offender') is not None:
            features['perpetrator_registered_sex_offender'] += 1
        if case.get('relationship_to_victim'):
            features['relationship_to_victim'] += 1
        if case.get('platforms_used'):
            features['platforms_used'] += 1
        if case.get('severity_indicators'):
            features['severity_indicators'] += 1
        if case.get('case_topics'):
            features['case_topics'] += 1
        if case.get('investigation_type'):
            features['investigation_type'] += 1
        if case.get('organizations'):
            features['organizations'] += 1
        if case.get('prosecution_outcome'):
            features['prosecution_outcome'] += 1
        if case.get('victim_demographics') or case.get('case_demographics'):
            features['victim_demographics'] += 1
    
    print(f"\nTotal cases: {total_cases}")
    print("\nFeature Coverage:")
    print("-" * 80)
    for feature, count in sorted(features.items(), key=lambda x: x[1], reverse=True):
        percentage = (count / total_cases * 100) if total_cases > 0 else 0
        bar = "█" * int(percentage / 2)
        print(f"  {feature:35} | {count:4}/{total_cases:4} ({percentage:5.1f}%) {bar}")
    
    return features

def analyze_organizations(cases: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Analyze organization distribution."""
    print("\n" + "="*80)
    print("ORGANIZATION ANALYSIS")
    print("="*80)
    
    org_counter = Counter()
    source_counter = Counter()
    
    for case in cases:
        source = case.get('source', 'unknown')
        source_counter[source] += 1
        
        orgs = case.get('organizations', [])
        if isinstance(orgs, list):
            for org in orgs:
                if org:
                    org_counter[org] += 1
        elif orgs:
            org_counter[orgs] += 1
    
    print("\nCases by Source:")
    print("-" * 80)
    for source, count in source_counter.most_common():
        print(f"  {source:30} | {count:4} cases")
    
    print("\nTop Organizations:")
    print("-" * 80)
    for org, count in org_counter.most_common(20):
        print(f"  {org:50} | {count:4} cases")
    
    return {
        'sources': dict(source_counter),
        'organizations': dict(org_counter)
    }

def analyze_geography(cases: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Analyze geographical distribution of cases."""
    print("\n" + "="*80)
    print("GEOGRAPHICAL FOCUS ANALYSIS")
    print("="*80)
    
    # US state names and abbreviations
    us_states = {
        'Alabama', 'Alaska', 'Arizona', 'Arkansas', 'California', 'Colorado', 'Connecticut',
        'Delaware', 'Florida', 'Georgia', 'Hawaii', 'Idaho', 'Illinois', 'Indiana', 'Iowa',
        'Kansas', 'Kentucky', 'Louisiana', 'Maine', 'Maryland', 'Massachusetts', 'Michigan',
        'Minnesota', 'Mississippi', 'Missouri', 'Montana', 'Nebraska', 'Nevada', 'New Hampshire',
        'New Jersey', 'New Mexico', 'New York', 'North Carolina', 'North Dakota', 'Ohio',
        'Oklahoma', 'Oregon', 'Pennsylvania', 'Rhode Island', 'South Carolina', 'South Dakota',
        'Tennessee', 'Texas', 'Utah', 'Vermont', 'Virginia', 'Washington', 'West Virginia',
        'Wisconsin', 'Wyoming', 'District of Columbia'
    }
    
    state_abbrev = {
        'AL': 'Alabama', 'AK': 'Alaska', 'AZ': 'Arizona', 'AR': 'Arkansas', 'CA': 'California',
        'CO': 'Colorado', 'CT': 'Connecticut', 'DE': 'Delaware', 'FL': 'Florida', 'GA': 'Georgia',
        'HI': 'Hawaii', 'ID': 'Idaho', 'IL': 'Illinois', 'IN': 'Indiana', 'IA': 'Iowa',
        'KS': 'Kansas', 'KY': 'Kentucky', 'LA': 'Louisiana', 'ME': 'Maine', 'MD': 'Maryland',
        'MA': 'Massachusetts', 'MI': 'Michigan', 'MN': 'Minnesota', 'MS': 'Mississippi',
        'MO': 'Missouri', 'MT': 'Montana', 'NE': 'Nebraska', 'NV': 'Nevada', 'NH': 'New Hampshire',
        'NJ': 'New Jersey', 'NM': 'New Mexico', 'NY': 'New York', 'NC': 'North Carolina',
        'ND': 'North Dakota', 'OH': 'Ohio', 'OK': 'Oklahoma', 'OR': 'Oregon', 'PA': 'Pennsylvania',
        'RI': 'Rhode Island', 'SC': 'South Carolina', 'SD': 'South Dakota', 'TN': 'Tennessee',
        'TX': 'Texas', 'UT': 'Utah', 'VT': 'Vermont', 'VA': 'Virginia', 'WA': 'Washington',
        'WV': 'West Virginia', 'WI': 'Wisconsin', 'WY': 'Wyoming', 'DC': 'District of Columbia'
    }
    
    state_counter = Counter()
    city_counter = Counter()
    county_counter = Counter()
    cases_with_locations = 0
    multi_state_cases = 0
    location_coverage = 0
    
    for case in cases:
        locations = case.get('locations', [])
        if not locations:
            continue
        
        cases_with_locations += 1
        case_states = set()
        case_cities = []
        case_counties = []
        
        for loc in locations:
            if not isinstance(loc, str):
                continue
            
            loc_clean = loc.strip()
            
            # Check if it's a state (full name or abbreviation)
            if loc_clean in us_states:
                case_states.add(loc_clean)
                state_counter[loc_clean] += 1
            elif loc_clean.upper() in state_abbrev:
                state_name = state_abbrev[loc_clean.upper()]
                case_states.add(state_name)
                state_counter[state_name] += 1
            # Check for county patterns
            elif 'County' in loc_clean or 'county' in loc_clean.lower():
                county_counter[loc_clean] += 1
                case_counties.append(loc_clean)
            # Likely a city (not a state, not a county)
            else:
                # Filter out common false positives
                if loc_clean.lower() not in ['united states', 'us', 'usa', 'u.s.', 'u.s.a.']:
                    city_counter[loc_clean] += 1
                    case_cities.append(loc_clean)
        
        if len(case_states) > 1:
            multi_state_cases += 1
    
    total_cases = len(cases)
    location_coverage = (cases_with_locations / total_cases * 100) if total_cases > 0 else 0
    
    print(f"\nLocation Coverage:")
    print("-" * 80)
    print(f"  Cases with location data: {cases_with_locations}/{total_cases} ({location_coverage:.1f}%)")
    print(f"  Multi-state cases: {multi_state_cases}")
    
    if state_counter:
        print(f"\nTop States (by case mentions):")
        print("-" * 80)
        for state, count in state_counter.most_common(20):
            percentage = (count / cases_with_locations * 100) if cases_with_locations > 0 else 0
            bar = "█" * int(percentage / 5)
            print(f"  {state:25} | {count:3} mentions ({percentage:5.1f}%) {bar}")
    
    if city_counter:
        print(f"\nTop Cities:")
        print("-" * 80)
        for city, count in city_counter.most_common(15):
            print(f"  {city:40} | {count:3} mentions")
    
    if county_counter:
        print(f"\nTop Counties:")
        print("-" * 80)
        for county, count in county_counter.most_common(10):
            print(f"  {county:40} | {count:3} mentions")
    
    # Analyze by source
    print(f"\nGeographical Distribution by Source:")
    print("-" * 80)
    ncmec_states = Counter()
    azicac_states = Counter()
    
    for case in cases:
        locations = case.get('locations', [])
        if not locations:
            continue
        
        source = case.get('source', '').upper()
        case_states = set()
        
        for loc in locations:
            if isinstance(loc, str):
                if loc in us_states:
                    case_states.add(loc)
                elif loc.upper() in state_abbrev:
                    case_states.add(state_abbrev[loc.upper()])
        
        for state in case_states:
            if 'NCMEC' in source:
                ncmec_states[state] += 1
            elif 'AZICAC' in source or 'AZ' in source:
                azicac_states[state] += 1
    
    if ncmec_states:
        print(f"\n  NCMEC Cases - Top States:")
        for state, count in ncmec_states.most_common(10):
            print(f"    {state:25} | {count:3} cases")
    
    if azicac_states:
        print(f"\n  AZICAC Cases - Top States:")
        for state, count in azicac_states.most_common(10):
            print(f"    {state:25} | {count:3} cases")
    
    return {
        'location_coverage': location_coverage,
        'cases_with_locations': cases_with_locations,
        'multi_state_cases': multi_state_cases,
        'states': dict(state_counter),
        'cities': dict(city_counter),
        'counties': dict(county_counter),
        'ncmec_states': dict(ncmec_states),
        'azicac_states': dict(azicac_states)
    }

def verify_claims(cases: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Verify specific claims about the dataset."""
    print("\n" + "="*80)
    print("CLAIM VERIFICATION")
    print("="*80)
    
    total_cases = len(cases)
    
    # Sanity counts by id prefix (full corpus is 9 sources, not NCMEC+AZ only)
    ncmec_cases = sum(1 for c in cases if c.get('id', '').startswith('ncmec_'))
    azicac_cases = sum(1 for c in cases if c.get('id', '').startswith('azicac_'))
    
    print(f"\nSanity: NCMEC + AZICAC case id counts (subset of full corpus)")
    print(f"  Total cases in DB: {total_cases}")
    print(f"  NCMEC (ncmec_*): {ncmec_cases}")
    print(f"  AZICAC (azicac_*): {azicac_cases}")
    print(f"  Combined: {ncmec_cases + azicac_cases}")
    
    # Check date ranges
    years = Counter()
    for case in cases:
        date_start = case.get('date_start')
        if date_start:
            year = str(date_start)[:4]
            if year.isdigit():
                years[year] += 1
    
    print(f"\nCases by Year:")
    print("-" * 80)
    for year in sorted(years.keys()):
        print(f"  {year}: {years[year]} cases")
    
    return {
        'total_cases': total_cases,
        'ncmec_cases': ncmec_cases,
        'azicac_cases': azicac_cases,
        'years': dict(years)
    }

def main():
    """Run all analyses."""
    print("="*80)
    print("CASELINKER DATASET STATISTICS & VERIFICATION")
    print("="*80)
    
    # Load cases
    print("\nLoading cases from database...")
    cases = storage.get_all_cases(include_raw_data=False)
    print(f"✓ Loaded {len(cases)} cases")
    
    if len(cases) == 0:
        print("❌ No cases found in database!")
        return
    
    # Run analyses
    age_analysis = analyze_age_ranges(cases)
    feature_coverage = analyze_feature_coverage(cases)
    org_analysis = analyze_organizations(cases)
    geography_analysis = analyze_geography(cases)
    claims = verify_claims(cases)
    
    # Save results
    results = {
        'age_analysis': age_analysis,
        'feature_coverage': feature_coverage,
        'organizations': org_analysis,
        'geography': geography_analysis,
        'claims': claims,
        'timestamp': str(Path(__file__).stat().st_mtime)
    }
    
    output_file = project_root / "scripts" / "analysis_results.json"
    with open(output_file, 'w') as f:
        json.dump(results, f, indent=2)
    
    print("\n" + "="*80)
    print(f"✓ Analysis complete! Results saved to: {output_file}")
    print("="*80)

if __name__ == "__main__":
    main()
