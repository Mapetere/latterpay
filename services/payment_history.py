"""
Payment History & Analytics Service for LatterPay
==================================================
Tracks payment history, generates analytics, and provides
reporting capabilities for donors and administrators.

Author: Nyasha Mapetere
Version: 2.1.0
"""

import logging
import sqlite3
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple
from functools import wraps
import json

logger = logging.getLogger(__name__)

DB_PATH = "botdata.db"
DB_TIMEOUT = 30


# ============================================================================
# DATABASE HELPER
# ============================================================================

def with_db_connection(func):
    """Decorator to manage database connections."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        conn = None
        try:
            conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT)
            conn.row_factory = sqlite3.Row
            return func(conn, *args, **kwargs)
        except sqlite3.Error as e:
            logger.error(f"Database error in {func.__name__}: {e}")
            raise
        finally:
            if conn:
                conn.close()
    return wrapper


# ============================================================================
# PAYMENT HISTORY TABLE INITIALIZATION
# ============================================================================

@with_db_connection
def init_payment_history_tables(conn):
    """Initialize payment history tables if they don't exist."""
    cursor = conn.cursor()
    
    # Main payment history table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS payment_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reference TEXT UNIQUE NOT NULL,
            phone TEXT NOT NULL,
            name TEXT,
            region TEXT,
            donation_type TEXT,
            amount REAL NOT NULL,
            currency TEXT DEFAULT 'ZWG',
            payment_method TEXT,
            status TEXT DEFAULT 'pending',
            paynow_reference TEXT,
            poll_url TEXT,
            note TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            completed_at DATETIME
        )
    """)
    
    # Daily aggregates for quick reporting
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS payment_daily_stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT UNIQUE NOT NULL,
            total_amount_usd REAL DEFAULT 0,
            total_amount_zwg REAL DEFAULT 0,
            transaction_count INTEGER DEFAULT 0,
            successful_count INTEGER DEFAULT 0,
            failed_count INTEGER DEFAULT 0,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Create indexes for performance
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_history_phone ON payment_history(phone)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_history_status ON payment_history(status)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_history_date ON payment_history(created_at)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_history_reference ON payment_history(reference)")
    
    conn.commit()
    logger.info("Payment history tables initialized")


# ============================================================================
# PAYMENT RECORDING
# ============================================================================

@with_db_connection
def record_payment(conn, payment_data: Dict[str, Any]) -> Optional[str]:
    """
    Record a new payment in the history.
    
    Args:
        payment_data: Dictionary containing payment details
        
    Returns:
        Reference number if successful, None otherwise
    """
    cursor = conn.cursor()
    
    try:
        reference = payment_data.get('reference', _generate_reference())
        
        cursor.execute("""
            INSERT INTO payment_history 
            (reference, phone, name, region, donation_type, amount, currency, 
             payment_method, status, paynow_reference, poll_url, note)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            reference,
            payment_data.get('phone'),
            payment_data.get('name'),
            payment_data.get('region'),
            payment_data.get('donation_type'),
            payment_data.get('amount', 0),
            payment_data.get('currency', 'ZWG'),
            payment_data.get('payment_method'),
            payment_data.get('status', 'pending'),
            payment_data.get('paynow_reference'),
            payment_data.get('poll_url'),
            payment_data.get('note', '')
        ))
        
        conn.commit()
        logger.info(f"Payment recorded: {reference}")
        return reference
        
    except sqlite3.IntegrityError as e:
        logger.error(f"Duplicate payment reference: {e}")
        return None
    except Exception as e:
        logger.error(f"Failed to record payment: {e}")
        conn.rollback()
        return None


@with_db_connection
def update_payment_status(conn, reference: str, status: str, 
                          paynow_reference: str = None) -> bool:
    """
    Update the status of a payment.
    
    Args:
        reference: Payment reference number
        status: New status (pending, completed, failed, cancelled)
        paynow_reference: Optional Paynow transaction reference
        
    Returns:
        True if successful
    """
    cursor = conn.cursor()
    
    try:
        update_fields = ["status = ?", "updated_at = CURRENT_TIMESTAMP"]
        params = [status]
        
        if paynow_reference:
            update_fields.append("paynow_reference = ?")
            params.append(paynow_reference)
        
        if status == 'completed':
            update_fields.append("completed_at = CURRENT_TIMESTAMP")
        
        params.append(reference)
        
        cursor.execute(f"""
            UPDATE payment_history 
            SET {', '.join(update_fields)}
            WHERE reference = ?
        """, params)
        
        conn.commit()
        
        # Update daily stats
        _update_daily_stats()
        
        logger.info(f"Payment {reference} status updated to {status}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to update payment status: {e}")
        conn.rollback()
        return False


def _generate_reference() -> str:
    """Generate a unique payment reference."""
    import random
    date_part = datetime.now().strftime("%Y%m%d")
    random_part = ''.join([str(random.randint(0, 9)) for _ in range(6)])
    return f"LP-{date_part}-{random_part}"


# ============================================================================
# PAYMENT HISTORY RETRIEVAL
# ============================================================================

@with_db_connection
def get_user_payment_history(conn, phone: str, limit: int = 10) -> List[Dict[str, Any]]:
    """
    Get payment history for a specific user.
    
    Args:
        phone: User's phone number
        limit: Maximum number of records to return
        
    Returns:
        List of payment records
    """
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT reference, name, donation_type, amount, currency, 
               payment_method, status, created_at, completed_at
        FROM payment_history
        WHERE phone = ?
        ORDER BY created_at DESC
        LIMIT ?
    """, (phone, limit))
    
    rows = cursor.fetchall()
    return [dict(row) for row in rows]


@with_db_connection
def get_payment_by_reference(conn, reference: str) -> Optional[Dict[str, Any]]:
    """
    Get a specific payment by reference number.
    
    Args:
        reference: Payment reference number
        
    Returns:
        Payment record or None
    """
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT * FROM payment_history
        WHERE reference = ?
    """, (reference,))
    
    row = cursor.fetchone()
    return dict(row) if row else None


@with_db_connection
def get_recent_payments(conn, hours: int = 24, status: str = None) -> List[Dict[str, Any]]:
    """
    Get recent payments within specified hours.
    
    Args:
        hours: Number of hours to look back
        status: Optional status filter
        
    Returns:
        List of payment records
    """
    cursor = conn.cursor()
    
    cutoff = datetime.now() - timedelta(hours=hours)
    
    if status:
        cursor.execute("""
            SELECT * FROM payment_history
            WHERE created_at >= ? AND status = ?
            ORDER BY created_at DESC
        """, (cutoff.isoformat(), status))
    else:
        cursor.execute("""
            SELECT * FROM payment_history
            WHERE created_at >= ?
            ORDER BY created_at DESC
        """, (cutoff.isoformat(),))
    
    rows = cursor.fetchall()
    return [dict(row) for row in rows]


# ============================================================================
# ANALYTICS & REPORTING
# ============================================================================

@with_db_connection
def get_payment_statistics(conn, days: int = 30) -> Dict[str, Any]:
    """
    Get payment statistics for the specified period.
    
    Args:
        days: Number of days to analyze
        
    Returns:
        Dictionary with statistics
    """
    cursor = conn.cursor()
    cutoff = datetime.now() - timedelta(days=days)
    
    # Total stats
    cursor.execute("""
        SELECT 
            COUNT(*) as total_transactions,
            SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as successful,
            SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed,
            SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) as pending,
            SUM(CASE WHEN status = 'completed' THEN amount ELSE 0 END) as total_amount
        FROM payment_history
        WHERE created_at >= ?
    """, (cutoff.isoformat(),))
    
    totals = dict(cursor.fetchone())
    
    # By currency
    cursor.execute("""
        SELECT 
            currency,
            SUM(amount) as total,
            COUNT(*) as count
        FROM payment_history
        WHERE created_at >= ? AND status = 'completed'
        GROUP BY currency
    """, (cutoff.isoformat(),))
    
    by_currency = {row['currency']: {'total': row['total'], 'count': row['count']} 
                   for row in cursor.fetchall()}
    
    # By payment method
    cursor.execute("""
        SELECT 
            payment_method,
            SUM(amount) as total,
            COUNT(*) as count
        FROM payment_history
        WHERE created_at >= ? AND status = 'completed'
        GROUP BY payment_method
    """, (cutoff.isoformat(),))
    
    by_method = {row['payment_method']: {'total': row['total'], 'count': row['count']} 
                 for row in cursor.fetchall()}
    
    # By donation type
    cursor.execute("""
        SELECT 
            donation_type,
            SUM(amount) as total,
            COUNT(*) as count
        FROM payment_history
        WHERE created_at >= ? AND status = 'completed'
        GROUP BY donation_type
    """, (cutoff.isoformat(),))
    
    by_type = {row['donation_type']: {'total': row['total'], 'count': row['count']} 
               for row in cursor.fetchall()}
    
    # Top donors
    cursor.execute("""
        SELECT 
            name,
            SUM(amount) as total,
            COUNT(*) as count
        FROM payment_history
        WHERE created_at >= ? AND status = 'completed'
        GROUP BY name
        ORDER BY total DESC
        LIMIT 10
    """, (cutoff.isoformat(),))
    
    top_donors = [dict(row) for row in cursor.fetchall()]
    
    return {
        'period_days': days,
        'totals': totals,
        'by_currency': by_currency,
        'by_payment_method': by_method,
        'by_donation_type': by_type,
        'top_donors': top_donors,
        'generated_at': datetime.now().isoformat()
    }


@with_db_connection
def get_daily_report(conn, date: datetime = None) -> Dict[str, Any]:
    """
    Get daily payment report.
    
    Args:
        date: Date for report (defaults to today)
        
    Returns:
        Daily report data
    """
    if date is None:
        date = datetime.now()
    
    date_str = date.strftime("%Y-%m-%d")
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT 
            COUNT(*) as total_transactions,
            SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as successful,
            SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed,
            SUM(CASE WHEN status = 'completed' AND currency = 'USD' THEN amount ELSE 0 END) as total_usd,
            SUM(CASE WHEN status = 'completed' AND currency = 'ZWG' THEN amount ELSE 0 END) as total_zwg
        FROM payment_history
        WHERE date(created_at) = ?
    """, (date_str,))
    
    summary = dict(cursor.fetchone())
    
    cursor.execute("""
        SELECT reference, name, amount, currency, payment_method, status, created_at
        FROM payment_history
        WHERE date(created_at) = ?
        ORDER BY created_at DESC
    """, (date_str,))
    
    transactions = [dict(row) for row in cursor.fetchall()]
    
    return {
        'date': date_str,
        'summary': summary,
        'transactions': transactions,
        'generated_at': datetime.now().isoformat()
    }


@with_db_connection
def _update_daily_stats(conn):
    """Update daily aggregated statistics."""
    cursor = conn.cursor()
    today = datetime.now().strftime("%Y-%m-%d")
    
    cursor.execute("""
        SELECT 
            SUM(CASE WHEN currency = 'USD' AND status = 'completed' THEN amount ELSE 0 END) as usd,
            SUM(CASE WHEN currency = 'ZWG' AND status = 'completed' THEN amount ELSE 0 END) as zwg,
            COUNT(*) as total,
            SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as success,
            SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed
        FROM payment_history
        WHERE date(created_at) = ?
    """, (today,))
    
    stats = cursor.fetchone()
    
    cursor.execute("""
        INSERT INTO payment_daily_stats 
        (date, total_amount_usd, total_amount_zwg, transaction_count, 
         successful_count, failed_count, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(date) DO UPDATE SET
            total_amount_usd = excluded.total_amount_usd,
            total_amount_zwg = excluded.total_amount_zwg,
            transaction_count = excluded.transaction_count,
            successful_count = excluded.successful_count,
            failed_count = excluded.failed_count,
            updated_at = CURRENT_TIMESTAMP
    """, (today, stats['usd'] or 0, stats['zwg'] or 0, 
          stats['total'] or 0, stats['success'] or 0, stats['failed'] or 0))
    
    conn.commit()


# ============================================================================
# USER COMMANDS
# ============================================================================

def format_payment_history_message(payments: List[Dict[str, Any]]) -> str:
    """
    Format payment history for WhatsApp display.
    
    Args:
        payments: List of payment records
        
    Returns:
        Formatted message string
    """
    if not payments:
        return "📭 *No Payment History*\n\nYou haven't made any payments yet."
    
    lines = ["📋 *Your Payment History*\n", "━" * 20]
    
    for i, payment in enumerate(payments[:5], 1):
        status_emoji = {
            'completed': '✅',
            'pending': '⏳',
            'failed': '❌',
            'cancelled': '🚫'
        }.get(payment.get('status'), '❓')
        
        date_str = payment.get('created_at', '')[:10]
        
        lines.append(f"\n*{i}.* {status_emoji} {payment.get('donation_type', 'Payment')}")
        lines.append(f"   💰 {payment.get('currency', 'ZWG')} {payment.get('amount', 0)}")
        lines.append(f"   📅 {date_str}")
        lines.append(f"   🔢 `{payment.get('reference', 'N/A')}`")
    
    if len(payments) > 5:
        lines.append(f"\n_...and {len(payments) - 5} more transactions_")
    
    return '\n'.join(lines)


def format_admin_report(stats: Dict[str, Any]) -> str:
    """
    Format statistics for admin report.
    
    Args:
        stats: Statistics dictionary
        
    Returns:
        Formatted message string
    """
    totals = stats.get('totals', {})
    by_currency = stats.get('by_currency', {})
    
    usd_total = by_currency.get('USD', {}).get('total', 0) or 0
    zwg_total = by_currency.get('ZWG', {}).get('total', 0) or 0
    
    lines = [
        "📊 *PAYMENT STATISTICS*",
        "━" * 25,
        f"\n📅 *Period:* Last {stats.get('period_days', 30)} days",
        "",
        "💰 *Totals:*",
        f"   • USD: ${usd_total:,.2f}",
        f"   • ZWG: ZWG {zwg_total:,.2f}",
        "",
        "📈 *Transactions:*",
        f"   • Total: {totals.get('total_transactions', 0)}",
        f"   • Successful: {totals.get('successful', 0)} ✅",
        f"   • Failed: {totals.get('failed', 0)} ❌",
        f"   • Pending: {totals.get('pending', 0)} ⏳",
        "",
        "🏆 *Top Donors:*"
    ]
    
    for i, donor in enumerate(stats.get('top_donors', [])[:3], 1):
        lines.append(f"   {i}. {donor.get('name', 'Unknown')} - ${donor.get('total', 0):,.2f}")
    
    lines.append(f"\n_Generated: {stats.get('generated_at', '')[:16]}_")
    
    return '\n'.join(lines)


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    # Initialization
    'init_payment_history_tables',
    
    # Recording
    'record_payment',
    'update_payment_status',
    
    # Retrieval
    'get_user_payment_history',
    'get_payment_by_reference',
    'get_recent_payments',
    
    # Analytics
    'get_payment_statistics',
    'get_daily_report',
    
    # Formatting
    'format_payment_history_message',
    'format_admin_report',
]
