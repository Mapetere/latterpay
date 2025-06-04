import os
from apscheduler.schedulers.background import BackgroundScheduler
from services import sendpdf 
from services.generatePR import generate_payment_report 
from services import  config
import atexit


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

def send_payment_report_to_finance(report_type="pdf"):
    file_path = generate_payment_report()

    if not file_path:
        print("❌ No PDF was generated.")
        return

    sendpdf.send_pdf(config.finance_phone, file_path,"🧾 Church Donation Report")
    os.unlink(file_path)  # cleanup