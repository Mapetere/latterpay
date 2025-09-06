import json
import pandas as pd
from fpdf import FPDF
import os
import tempfile
from datetime import datetime
from services import  config
from services.config import PAYMENTS_FILE




def generate_payment_report(File_type=None):

    if File_type == "PDF":
        """Generate a PDF report of all payments grouped by congregation"""
        try:
            with open(PAYMENTS_FILE, 'r') as f:
                payments = json.load(f)
            
            if not payments:
                return None
                
            df = pd.DataFrame(payments)
            grouped = df.groupby('congregation')
            
            pdf = FPDF()
            pdf.set_auto_page_break(auto=True, margin=15)
            pdf.add_page()
            
            pdf.set_font('Arial', 'B', 16)
            pdf.cell(0, 10, 'Donation Payments Report', 0, 1, 'C')
            pdf.ln(10)
            
            pdf.set_font('Arial', '', 12)
            pdf.cell(0, 10, f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M')}", 0, 1)
            pdf.ln(10)
            
            total_amount = df['amount'].sum()
            pdf.cell(0, 10, f"Total Donations: ${total_amount:,.2f}", 0, 1)
            pdf.cell(0, 10, f"Total Donors: {len(df)}", 0, 1)
            pdf.ln(15)
            
            for congregation, group in grouped:
                pdf.set_font('Arial', 'B', 14)
                pdf.cell(0, 10, f"Congregation: {congregation}", 0, 1)
                pdf.set_font('Arial', '', 12)
                
                pdf.cell(60, 10, 'Name', 1, 0, 'L')
                pdf.cell(40, 10, 'Amount', 1, 0, 'L')
                pdf.cell(80, 10, 'Purpose', 1, 1, 'L')
                
                for _, row in group.iterrows():
                    pdf.cell(60, 10, row['name'], 1, 0, 'L')
                    pdf.cell(40, 10, f"${row['amount']:,.2f}", 1, 0, 'L')
                    pdf.cell(80, 10, row['purpose'], 1, 1, 'L')
                    
                
                pdf.ln(5)
            
            temp_file = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
            pdf_path = temp_file.name
            pdf.output(pdf_path)
            temp_file.close()
            
            print(f"Found {len(payments)} payments in file.")

            return pdf_path
            
        except Exception as e:
            print(f"Error generating report: {e}")
            return None
        
    elif File_type == "Excel":
        """Generate Excel report of all payments"""
    try:
        with open(config.PAYMENTS_FILE, 'r') as f:
            payments = json.load(f)
            
        if not payments:
            return None
            
        df = pd.DataFrame(payments)
        
        temp_file = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
        excel_path = temp_file.name
        df.to_excel(excel_path, index=False)
        temp_file.close()
        
        return excel_path
        
    except Exception as e:
        print(f"Error generating Excel report: {e}")
        return None




            
