import os
from apscheduler.schedulers.background import BackgroundScheduler
from services.sendpdf import send_pdf
from services.generatePR import generate_payment_report 
from services import  config
import atexit
import logging

#Daily/weekly auto-reports

def setup_scheduled_reports():
    """Configure automatic daily/weekly reports"""
    scheduler = BackgroundScheduler(daemon=True)
    
    # Daily report at 9am
    scheduler.add_job(
        send_payment_report_to_finance,
        'cron',
        day_of_week='mon-fri',
        hour=9,
        minute=0,
        args=["pdf"]  # Send PDF by default
    )
    
    # Weekly summary every Monday at 10am
    scheduler.add_job(
        lambda: send_payment_report_to_finance("excel"),  # Excel for weekly
        'cron',
        day_of_week='mon',
        hour=10,
        minute=0
    )
    
    scheduler.start()
    scheduler.remove_all_jobs()
    print("Scheduled reports setup complete.")
    # Shut down the scheduler when exiting the app
    atexit.register(lambda: scheduler.shutdown())

def send_payment_report_to_finance():
    try:
        # 1. Generate PDF
        pdf_path = generate_payment_report()
        if not pdf_path:
            print(" PDF generation failed")
            return False

        # 2. Verify PDF
        if not os.path.exists(pdf_path):
            print(f"PDF not found at {pdf_path}")
            return False

        print(f" PDF generated ({os.path.getsize(pdf_path)} bytes)")

        # 3. Send PDF
        success = send_pdf(
            phone=config.FINANCE_PHONE,
            file_path=pdf_path,
            caption="Donation Report"
        )

        # 4. Clean up
        if os.path.exists(pdf_path):
            os.unlink(pdf_path)

        return success

    except Exception as e:
        print(f" Error in send_payment_report_to_finance: {e}")
        return False
