"""
Storage Layer

Purpose: Store cases and relationships with fast retrieval and lookup capabilities.

Design Ideas from Architecture:
- Case Database (PostgreSQL/MySQL): keep it simple, store case data tables, ideally similar close together
- Store case entities in "rawish" format (preserve original structure + normalized fields)
- Graph Database: Store case and relationships with weighted edges based on similarity strength
- Efficient traversal for link analysis
- Quick relationship queries (e.g., "show all cases connected to case X")
"""

import json
import sqlite3
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime


def get_connection(db_path: str, encryption_key: Optional[str] = None):
    """Get database connection"""
    return sqlite3.connect(db_path)


class CaseStorage:
    """
    Case Database Storage
    
    Stores processed case data in "rawish" format - preserves original structure 
    along with normalized fields. Designed for quick retrieval and lookups.
    Similar cases stored close together for efficient access.
    """
    
    def __init__(self, db_path: str = "caselinker.db", encryption_key: Optional[str] = None):
        """
        Initialize case storage.
        
        Args:
            db_path: Path to SQLite database file
            encryption_key: Deprecated (kept for backward compatibility)
        """
        self.db_path = db_path
        self.init_database()
    
    def init_database(self):
        """
        Initialize database tables.
        Creates tables for storing case data in rawish format.
        """
        conn = get_connection(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS cases (
                id TEXT PRIMARY KEY,
                source TEXT,
                date_start TEXT,
                date_end TEXT,
                victim_count INTEGER,
                perpetrator_count INTEGER,
                relationship_to_victim TEXT,
                platforms_used TEXT,  -- JSON array
                technologies TEXT,    -- JSON array
                communication_methods TEXT,  -- JSON array
                investigation_methods TEXT,   -- JSON array
                severity_indicators TEXT,     -- JSON array
                case_topics TEXT,             -- JSON array
                tags TEXT,                    -- JSON array
                notes TEXT,
                raw_data TEXT,                -- JSON - original case data
                extracted_features TEXT,      -- JSON - structured features
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_source ON cases(source)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_date_start ON cases(date_start)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_case_topics ON cases(case_topics)')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS victim_demographics (
                case_id TEXT,
                age_range TEXT,
                region TEXT,
                anonymized_id TEXT,
                FOREIGN KEY (case_id) REFERENCES cases(id)
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS perpetrator_demographics (
                case_id TEXT,
                age_range TEXT,
                region TEXT,
                anonymized_id TEXT,
                previous_conviction TEXT,  -- JSON
                FOREIGN KEY (case_id) REFERENCES cases(id)
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS prosecution_outcomes (
                case_id TEXT,
                status TEXT,
                charges TEXT,
                sentences TEXT,
                FOREIGN KEY (case_id) REFERENCES cases(id)
            )
        ''')
        
        conn.commit()
        conn.close()
    
    def store_case(self, case: Dict[str, Any]) -> bool:
        """
        Store a single case in the database.
        Preserves raw data while storing normalized fields.
        
        Args:
            case: Case dictionary from processing layer
            
        Returns:
            True if successful, False otherwise
        """
        try:
            conn = get_connection(self.db_path)
            cursor = conn.cursor()
            
            date_range = case.get('date_range', {})
            date_start = date_range.get('start') if isinstance(date_range, dict) else None
            date_end = date_range.get('end') if isinstance(date_range, dict) else None
            
            # Map new schema to database format (backward compatible)
            investigation_info = case.get('investigation_type') or case.get('investigation_methods_and_teams')
            if isinstance(investigation_info, dict):
                # New format: {type: str, agencies: [str]}
                investigation_methods = [investigation_info.get('type')] + investigation_info.get('agencies', [])
            elif isinstance(investigation_info, str):
                investigation_methods = [investigation_info]
            else:
                investigation_methods = case.get('agencies_involved', [])
            
            cursor.execute('''
                INSERT OR REPLACE INTO cases (
                    id, source, date_start, date_end, victim_count, perpetrator_count,
                    relationship_to_victim, platforms_used, technologies, communication_methods,
                    investigation_methods, severity_indicators, case_topics, tags, notes,
                    raw_data, extracted_features, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                case.get('id'),
                case.get('source', 'unknown'),
                date_start,
                date_end,
                case.get('victim_count'),
                None,  # perpetrator_count (deprecated, use perpetrator_age instead)
                case.get('relationship_to_victim'),
                json.dumps(case.get('platforms_used', [])),
                json.dumps([]),  # technologies (deprecated)
                json.dumps([]),  # communication_methods (deprecated)
                json.dumps(investigation_methods),
                json.dumps(case.get('severity_indicators', [])),
                json.dumps(case.get('case_topics', [])),
                json.dumps(case.get('tags', [])),
                case.get('notes'),
                json.dumps(case.get('raw_data', {})),
                json.dumps(case),  # Store full case as extracted_features for new schema
                datetime.now().isoformat()
            ))
            
            victim_demo = case.get('victim_demographics')
            if victim_demo and isinstance(victim_demo, dict):
                # Store age_range as JSON string (can be dict with min/max or list)
                age_range_str = None
                if victim_demo.get('age_range'):
                    age_range_str = json.dumps(victim_demo.get('age_range'))
                elif victim_demo.get('ages'):
                    # Create age_range from ages list
                    ages = victim_demo.get('ages', [])
                    if ages:
                        age_range_str = json.dumps({'min': min(ages), 'max': max(ages)})
                
                cursor.execute('''
                    INSERT OR REPLACE INTO victim_demographics 
                    (case_id, age_range, region, anonymized_id)
                    VALUES (?, ?, ?, ?)
                ''', (
                    case.get('id'),
                    age_range_str,
                    victim_demo.get('region'),
                    None,  # anonymized_id (not extracted)
                ))
            
            # Store perpetrator demographics (new format: age, is_registered)
            perp_age = case.get('perpetrator_age')
            perp_registered = case.get('perpetrator_registered_sex_offender', False)
            perp_demo = case.get('perpetrator_demographics')
            
            if perp_age is not None or perp_registered or perp_demo:
                # Create age_range from age
                age_range_str = None
                if perp_age is not None:
                    age_range_str = json.dumps({'min': perp_age, 'max': perp_age})
                elif perp_demo and isinstance(perp_demo, dict) and perp_demo.get('age'):
                    age = perp_demo.get('age')
                    age_range_str = json.dumps({'min': age, 'max': age})
                
                prev_conviction = case.get('previous_conviction') or (perp_demo.get('previous_conviction') if isinstance(perp_demo, dict) else None)
                
                cursor.execute('''
                    INSERT OR REPLACE INTO perpetrator_demographics 
                    (case_id, age_range, region, anonymized_id, previous_conviction)
                    VALUES (?, ?, ?, ?, ?)
                ''', (
                    case.get('id'),
                    age_range_str,
                    None,  # region (not extracted)
                    None,  # anonymized_id (not extracted)
                    json.dumps(prev_conviction) if prev_conviction else None,
                ))
            
            prosecution = case.get('prosecution_outcome')
            if prosecution and isinstance(prosecution, dict):
                # Map new format to old format for backward compatibility
                status = prosecution.get('booking_status') or prosecution.get('status')
                charges = prosecution.get('charges', [])
                # Convert charges list to old format if needed
                charges_str = json.dumps(charges)
                
                cursor.execute('''
                    INSERT OR REPLACE INTO prosecution_outcomes 
                    (case_id, status, charges, sentences)
                    VALUES (?, ?, ?, ?)
                ''', (
                    case.get('id'),
                    status,
                    charges_str,
                    json.dumps([]),  # sentences (not extracted)
                ))
            
            conn.commit()
            conn.close()
            return True
            
        except Exception as e:
            print(f"Error storing case: {e}")
            return False
    
    def store_cases(self, cases: List[Dict[str, Any]]) -> int:
        """
        Store multiple cases in the database.
        
        Args:
            cases: List of case dictionaries
            
        Returns:
            Number of successfully stored cases
        """
        stored_count = 0
        for case in cases:
            if self.store_case(case):
                stored_count += 1
        return stored_count
    
    def get_case(self, case_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve a single case by ID.
        
        Args:
            case_id: Case identifier
            
        Returns:
            Case dictionary or None if not found
        """
        try:
            conn = get_connection(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('SELECT * FROM cases WHERE id = ?', (case_id,))
            row = cursor.fetchone()
            
            if not row:
                conn.close()
                return None
            
            columns = [desc[0] for desc in cursor.description]
            case_dict = dict(zip(columns, row))
            
            # Parse JSON fields
            for json_field in ['platforms_used', 'technologies', 'communication_methods',
                             'investigation_methods', 'severity_indicators', 'case_topics',
                             'tags', 'raw_data', 'extracted_features']:
                if case_dict.get(json_field):
                    try:
                        case_dict[json_field] = json.loads(case_dict[json_field])
                    except:
                        pass
            
            # Get related data
            cursor.execute('SELECT * FROM victim_demographics WHERE case_id = ?', (case_id,))
            victim_rows = cursor.fetchall()
            if victim_rows:
                victim_cols = [desc[0] for desc in cursor.description]
                case_dict['victim_demographics'] = [dict(zip(victim_cols, row)) for row in victim_rows]
            
            cursor.execute('SELECT * FROM perpetrator_demographics WHERE case_id = ?', (case_id,))
            perp_rows = cursor.fetchall()
            if perp_rows:
                perp_cols = [desc[0] for desc in cursor.description]
                case_dict['perpetrator_demographics'] = [dict(zip(perp_cols, row)) for row in perp_rows]
            
            cursor.execute('SELECT * FROM prosecution_outcomes WHERE case_id = ?', (case_id,))
            prosecution_rows = cursor.fetchall()
            if prosecution_rows:
                prosecution_cols = [desc[0] for desc in cursor.description]
                case_dict['prosecution_outcomes'] = [dict(zip(prosecution_cols, row)) for row in prosecution_rows]
            
            # Reconstruct date_range
            if case_dict.get('date_start') or case_dict.get('date_end'):
                case_dict['date_range'] = {
                    'start': case_dict.get('date_start'),
                    'end': case_dict.get('date_end')
                }
            
            # Merge extracted_features back into case_dict (new schema fields)
            extracted_features = case_dict.get('extracted_features', {})
            if isinstance(extracted_features, dict):
                # Merge new schema fields from extracted_features
                for key in ['perpetrator_age', 'perpetrator_registered_sex_offender', 
                           'agencies_involved', 'investigation_type', 'evidence_volume',
                           'prosecution_outcome', 'victim_demographics', 'relationship_to_victim']:
                    if key in extracted_features:
                        case_dict[key] = extracted_features[key]
            
            # Also merge prosecution_outcome from prosecution_outcomes table if not already merged
            if not case_dict.get('prosecution_outcome') and case_dict.get('prosecution_outcomes'):
                prosecution_rows = case_dict.get('prosecution_outcomes', [])
                if prosecution_rows and len(prosecution_rows) > 0:
                    prosecution = prosecution_rows[0]
                    case_dict['prosecution_outcome'] = {
                        'booking_status': prosecution.get('status'),
                        'charges': json.loads(prosecution.get('charges', '[]')) if prosecution.get('charges') else [],
                        'jail': None
                    }
            
            conn.close()
            return case_dict
            
        except Exception as e:
            print(f"Error retrieving case: {e}")
            return None
    
    def get_all_cases(self) -> List[Dict[str, Any]]:
        """
        Retrieve all cases from the database.
        
        Returns:
            List of case dictionaries
        """
        try:
            # Check if database file exists
            db_path_obj = Path(self.db_path)
            if not db_path_obj.exists():
                print(f"⚠️  Database file not found: {self.db_path}")
                return []
            
            # Check file size - if it's very small, might be empty or corrupted
            file_size = db_path_obj.stat().st_size
            if file_size < 1000:  # Less than 1KB is suspicious
                print(f"⚠️  Database file is very small ({file_size} bytes) - might be empty")
            
            conn = get_connection(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('SELECT id FROM cases ORDER BY date_start, id')
            case_ids = [row[0] for row in cursor.fetchall()]
            
            conn.close()
            
            cases = []
            for case_id in case_ids:
                case = self.get_case(case_id)
                if case:
                    cases.append(case)
            
            return cases
            
        except Exception as e:
            print(f"❌ Error retrieving all cases: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    def search_cases(self, query: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Search cases based on criteria.
        
        Args:
            query: Dictionary with search criteria (source, date_range, etc.)
            
        Returns:
            List of matching case dictionaries
        """
        try:
            conn = get_connection(self.db_path)
            cursor = conn.cursor()
            
            conditions = []
            params = []
            
            if query.get('source'):
                conditions.append('source = ?')
                params.append(query['source'])
            
            if query.get('date_start'):
                conditions.append('date_start >= ?')
                params.append(query['date_start'])
            
            if query.get('date_end'):
                conditions.append('date_start <= ?')
                params.append(query['date_end'])
            
            where_clause = ' AND '.join(conditions) if conditions else '1=1'
            
            cursor.execute(f'SELECT id FROM cases WHERE {where_clause} ORDER BY date_start', params)
            case_ids = [row[0] for row in cursor.fetchall()]
            
            conn.close()
            
            cases = []
            for case_id in case_ids:
                case = self.get_case(case_id)
                if case:
                    cases.append(case)
            
            return cases
            
        except Exception as e:
            print(f"Error searching cases: {e}")
            return []


class GraphStorage:
    """
    Graph Database Storage
    
    Stores case relationships and connections with weighted edges.
    Designed for efficient traversal and link analysis.
    """
    
    def __init__(self, db_path: str = "caselinker_graph.db", encryption_key: Optional[str] = None):
        """
        Initialize graph storage.
        
        Args:
            db_path: Path to SQLite database file
            encryption_key: Deprecated (kept for backward compatibility)
        """
        self.db_path = db_path
        self.init_graph_database()
    
    def init_graph_database(self):
        """
        Initialize graph database tables.
        Creates nodes and edges tables for relationship storage.
        """
        conn = get_connection(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS nodes (
                id TEXT PRIMARY KEY,
                type TEXT,
                properties TEXT,  -- JSON
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS edges (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id TEXT,
                target_id TEXT,
                relationship_type TEXT,
                weight REAL,
                properties TEXT,  -- JSON
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (source_id) REFERENCES nodes(id),
                FOREIGN KEY (target_id) REFERENCES nodes(id)
            )
        ''')
        
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_source ON edges(source_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_target ON edges(target_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_relationship ON edges(relationship_type)')
        
        conn.commit()
        conn.close()
    
    def add_case_node(self, case_id: str, properties: Dict[str, Any]):
        """Add a case node to the graph"""
        try:
            conn = get_connection(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT OR REPLACE INTO nodes (id, type, properties)
                VALUES (?, 'case', ?)
            ''', (case_id, json.dumps(properties)))
            
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Error adding node: {e}")
            return False
    
    def add_relationship(self, source_id: str, target_id: str, 
                       relationship_type: str, weight: float = 1.0,
                       properties: Optional[Dict[str, Any]] = None):
        """Add a relationship edge between two nodes"""
        try:
            conn = get_connection(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO edges (source_id, target_id, relationship_type, weight, properties)
                VALUES (?, ?, ?, ?, ?)
            ''', (source_id, target_id, relationship_type, weight, 
                  json.dumps(properties or {})))
            
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Error adding relationship: {e}")
            return False
    
    def get_connected_cases(self, case_id: str, max_depth: int = 1) -> List[Dict[str, Any]]:
        """Get all cases connected to a given case"""
        try:
            conn = get_connection(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT DISTINCT target_id, relationship_type, weight
                FROM edges
                WHERE source_id = ?
                UNION
                SELECT DISTINCT source_id, relationship_type, weight
                FROM edges
                WHERE target_id = ?
            ''', (case_id, case_id))
            
            results = cursor.fetchall()
            conn.close()
            
            return [{'case_id': row[0], 'relationship': row[1], 'weight': row[2]} 
                   for row in results]
        except Exception as e:
            print(f"Error getting connected cases: {e}")
            return []
    
    def get_all_relationships(self) -> List[Tuple[str, str, str, float]]:
        """Get all relationships in the graph"""
        try:
            conn = get_connection(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT source_id, target_id, relationship_type, weight
                FROM edges
            ''')
            
            results = cursor.fetchall()
            conn.close()
            
            return results
        except Exception as e:
            print(f"Error getting relationships: {e}")
            return []
