import pandas as pd
import io
from typing import List, Dict, Any

class DataCleaningService:
    def clean_data(self, file_content: bytes, filename: str) -> List[Dict[str, Any]]:
        if filename.endswith('.csv'):
            df = pd.read_csv(io.BytesIO(file_content))
        elif filename.endswith(('.xls', '.xlsx')):
            df = pd.read_excel(io.BytesIO(file_content))
        else:
            raise ValueError("Unsupported file format")

        # Phase 1: Structure Standardization
        # Remove empty rows/cols
        df.dropna(how='all', inplace=True)
        df.dropna(axis=1, how='all', inplace=True)
        
        # Remove "Total" or "合计" rows if present (simple heuristic)
        df = df[~df.iloc[:, 0].astype(str).str.contains('合计|Total', case=False, na=False)]

        # Phase 2: Semantic Enhancement (Simplified)
        # Rename columns if they match common patterns
        # This is a placeholder for more advanced logic
        
        # Phase 3: QC Logic Validation
        # Check if we have 'qualified' and 'defective' columns
        # This would be more complex in a real app
        
        # Convert to list of dicts for frontend
        # Add a unique key for AntD
        df['key'] = range(len(df))
        
        return df.to_dict(orient='records')

data_cleaning_service = DataCleaningService()
