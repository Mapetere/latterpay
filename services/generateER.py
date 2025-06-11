from services import  config
import json
import pandas as pd
from fpdf import FPDF   
import tempfile
def generate_excel_report():
    """Generate Excel report of all payments"""
    try:
        with open(config.PAYMENTS_FILE, 'r') as f:
            payments = json.load(f)
            
        if not payments:
            return None
            
        df = pd.DataFrame(payments)
        
        # Create temporary file
        temp_file = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
        excel_path = temp_file.name
        df.to_excel(excel_path, index=False)
        temp_file.close()
        
        return excel_path
        
    except Exception as e:
        print(f"Error generating Excel report: {e}")
        return None