# services/help_docs.py
from fpdf import FPDF
import tempfile


class HelpDocuments:
    @staticmethod
    def create_donation_type_guide():
        """Generate a PDF guide for adding donation types"""
        pdf = FPDF()
        pdf.add_page()
        
        # Title
        pdf.set_font('Arial', 'B', 16)
        pdf.cell(0, 10, 'How to Add New Donation Types', 0, 1, 'C')
        pdf.ln(10)
        
        # Section 1
        pdf.set_font('Arial', 'B', 14)
        pdf.cell(0, 10, '1. Standard Donation Types', 0, 1)
        pdf.set_font('Arial', '', 12)
        pdf.multi_cell(0, 8, 
            "We currently support:\n"
            "- Monthly Contributions\n"
            "- August Conference\n"
            "- Youth Conference\n\n"
            "These are always available for selection.")
        
        # Section 2
        pdf.ln(5)
        pdf.set_font('Arial', 'B', 14)
        pdf.cell(0, 10, '2. Requesting New Types', 0, 1)
        pdf.set_font('Arial', '', 12)
        pdf.multi_cell(0, 8,
            "To request a new donation type:\n"
            "1. Select 'Other' when choosing donation purpose\n"
            "2. Describe your new type (e.g. 'Building Fund')\n"
            "3. Complete your donation\n\n"
            "Our treasurer will review your request within 48 hours.")
        
        # Section 3
        pdf.ln(5)
        pdf.set_font('Arial', 'B', 14)
        pdf.cell(0, 10, '3. Approval Process', 0, 1)
        pdf