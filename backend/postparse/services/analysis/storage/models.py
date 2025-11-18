from datetime import datetime
from typing import Optional, Dict, Any
import json
from ...core.database.base import Database
from ..classifiers.base import ClassificationResult

class AnalysisDB(Database):
    """Database handler for analysis results."""
    
    def __init__(self, db_dir: str = "data"):
        super().__init__(db_dir)
        self.init_db()
    
    def init_db(self) -> None:
        """Initialize the database with analysis-specific tables."""
        queries = [
            # Analysis results table
            '''
            CREATE TABLE IF NOT EXISTS content_analysis (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content_id INTEGER NOT NULL,
                content_source TEXT NOT NULL,
                classifier_name TEXT NOT NULL,
                label TEXT NOT NULL,
                confidence REAL NOT NULL,
                analyzed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            ''',
            # Analysis details table
            '''
            CREATE TABLE IF NOT EXISTS analysis_details (
                analysis_id INTEGER NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                FOREIGN KEY(analysis_id) REFERENCES content_analysis(id),
                PRIMARY KEY(analysis_id, key)
            )
            '''
        ]
        
        for query in queries:
            self.execute_query(query)
    
    def save_result(
        self,
        content_id: int,
        content_source: str,
        classifier_name: str,
        result: ClassificationResult
    ) -> None:
        """Save an analysis result to the database.
        
        Args:
            content_id: ID of the analyzed content
            content_source: Source of the content ('telegram' or 'instagram')
            classifier_name: Name of the classifier used
            result: Classification result
        """
        # Insert main analysis record
        self.execute_query(
            '''
            INSERT INTO content_analysis (
                content_id, content_source, classifier_name,
                label, confidence
            ) VALUES (?, ?, ?, ?, ?)
            ''',
            (
                content_id,
                content_source,
                classifier_name,
                result.label,
                result.confidence
            )
        )
        
        analysis_id = self.execute_query(
            'SELECT last_insert_rowid()'
        )[0][0]
        
        # Insert details if present
        if result.details:
            self._save_details(analysis_id, result.details)
    
    def _save_details(self, analysis_id: int, details: Dict[str, Any]) -> None:
        """Save analysis details as key-value pairs."""
        detail_params = []
        
        def flatten_dict(d: Dict[str, Any], prefix: str = "") -> None:
            for key, value in d.items():
                full_key = f"{prefix}{key}" if prefix else key
                if isinstance(value, dict):
                    flatten_dict(value, f"{full_key}.")
                else:
                    detail_params.append(
                        (analysis_id, full_key, json.dumps(value))
                    )
        
        flatten_dict(details)
        
        if detail_params:
            self.execute_many(
                '''
                INSERT INTO analysis_details (analysis_id, key, value)
                VALUES (?, ?, ?)
                ''',
                detail_params
            )
    
    def get_results(
        self,
        content_id: int,
        content_source: str,
        classifier_name: Optional[str] = None
    ) -> list[Dict[str, Any]]:
        """Retrieve analysis results for content.
        
        Args:
            content_id: ID of the content
            content_source: Source of the content
            classifier_name: Optional filter by classifier
            
        Returns:
            list[Dict[str, Any]]: List of analysis results with details
        """
        query = """
            SELECT 
                ca.id, ca.classifier_name, ca.label,
                ca.confidence, ca.analyzed_at,
                ad.key, ad.value
            FROM content_analysis ca
            LEFT JOIN analysis_details ad ON ca.id = ad.analysis_id
            WHERE ca.content_id = ? AND ca.content_source = ?
        """
        params = [content_id, content_source]
        
        if classifier_name:
            query += " AND ca.classifier_name = ?"
            params.append(classifier_name)
            
        rows = self.execute_query(query, tuple(params))
        
        # Group results by analysis record
        results = {}
        for row in rows:
            analysis_id = row[0]
            if analysis_id not in results:
                results[analysis_id] = {
                    "classifier_name": row[1],
                    "label": row[2],
                    "confidence": row[3],
                    "analyzed_at": row[4],
                    "details": {}
                }
            if row[5] and row[6]:  # If there are details
                results[analysis_id]["details"][row[5]] = json.loads(row[6])
        
        return list(results.values()) 