import json
import pandas as pd
from fpdf import FPDF
import os
import tempfile
from datetime import datetime
from services.config import PAYMENTS_FILE




def generate_payment_report():
    """Generate a PDF report of all payments grouped by congregation"""
    try:
        with open(PAYMENTS_FILE, 'r') as f:
            payments = json.load(f)
        
        if not payments:
            return None
            
        # Create DataFrame and group by congregation
        df = pd.DataFrame(payments)
        grouped = df.groupby('congregation')
        
        # Create PDF
        pdf = FPDF()
        pdf.set_auto_page_break(auto=True, margin=15)
        pdf.add_page()
        
        # Title
        pdf.set_font('Arial', 'B', 16)
        pdf.cell(0, 10, 'Donation Payments Report', 0, 1, 'C')
        pdf.ln(10)
        
        # Add date
        pdf.set_font('Arial', '', 12)
        pdf.cell(0, 10, f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M')}", 0, 1)
        pdf.ln(10)
        
        # Add summary stats
        total_amount = df['amount'].sum()
        pdf.cell(0, 10, f"Total Donations: ${total_amount:,.2f}", 0, 1)
        pdf.cell(0, 10, f"Total Donors: {len(df)}", 0, 1)
        pdf.ln(15)
        
        # Add congregation sections
        for congregation, group in grouped:
            pdf.set_font('Arial', 'B', 14)
            pdf.cell(0, 10, f"Congregation: {congregation}", 0, 1)
            pdf.set_font('Arial', '', 12)
            
            # Create table header
            pdf.cell(60, 10, 'Name', 1, 0, 'L')
            pdf.cell(40, 10, 'Amount', 1, 0, 'L')
            pdf.cell(80, 10, 'Purpose', 1, 1, 'L')
            
            # Add rows
            for _, row in group.iterrows():
                pdf.cell(60, 10, row['name'], 1, 0, 'L')
                pdf.cell(40, 10, f"${row['amount']:,.2f}", 1, 0, 'L')
                pdf.cell(80, 10, row['purpose'], 1, 1, 'L')
                
            
            pdf.ln(5)
        
        # Save to temporary file
        temp_file = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        pdf_path = temp_file.name
        pdf.output(pdf_path)
        temp_file.close()
        
        print(f"Found {len(payments)} payments in file.")

        return pdf_path
        
    except Exception as e:
        print(f"Error generating report: {e}")
        return None


        
