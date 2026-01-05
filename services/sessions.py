"""
Session Management Module for LatterPay
========================================
Handles user session lifecycle with:
- Database-backed session storage
- Automatic session timeout
- Session monitoring daemon
- Connection pooling integration

Author: Nyasha Mapetere
Version: 2.1.0
"""

from datetime import datetime, timedelta
from typing import Optional, Dict, Any
import json
import sqlite3
import threading
import time
import logging
from functools import wraps

# Internal imports
from services.userstore import is_known_user, add_known_user
from services.pygwan_whatsapp import whatsapp

# Configure logger
logger = logging.getLogger(__name__)

# Database configuration
DB_PATH = "botdata.db"
DB_TIMEOUT = 30

# Session configuration
SESSION_TIMEOUT_MINUTES = 5
SESSION_WARNING_MINUTES = 4


# ============================================================================
# DATABASE HELPER WITH AUTOMATIC CONNECTION MANAGEMENT
# ============================================================================

def with_db_connection(func):
    """Decorator to automatically manage database connections with error handling."""
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
        except Exception as e:
            logger.error(f"Unexpected error in {func.__name__}: {e}")
            raise
        finally:
            if conn:
                try:
                    conn.close()
                except:
                    pass
    return wrapper


def safe_db_operation(default_return=None):
    """Decorator to safely execute database operations with fallback."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                logger.error(f"Safe DB operation failed in {func.__name__}: {e}", exc_info=True)
                return default_return
        return wrapper
    return decorator


# ============================================================================
# SESSION CRUD OPERATIONS
# ============================================================================

@with_db_connection
def get_all_sessions(conn) -> list:
    """
    Retrieve all active sessions from database.
    
    Returns:
        List of session dictionaries with phone, step, data, last_active, and warned.
    """
    cursor = conn.cursor()
    cursor.execute("""
        SELECT phone, step, data, last_active, COALESCE(warned, 0) as warned 
        FROM sessions
    """)
    rows = cursor.fetchall()
    
    sessions = []
    for row in rows:
        try:
            # Parse last_active with fallback
            last_active_str = row['last_active']
            if last_active_str:
                try:
                    last_active = datetime.fromisoformat(last_active_str)
                except ValueError:
                    # Try parsing as timestamp
                    last_active = datetime.now()
            else:
                last_active = datetime.now()
            
            # Parse data JSON safely
            data_json = row['data']
            data = json.loads(data_json) if data_json else {}
            
            sessions.append({
                "phone": row['phone'],
                "step": row['step'],
                "data": data,
                "last_active": last_active,
                "warned": row['warned']
            })
        except Exception as e:
            logger.warning(f"Failed to parse session for {row['phone']}: {e}")
            continue
    
    return sessions


@with_db_connection
def load_session(conn, phone: str) -> Optional[Dict[str, Any]]:
    """
    Load a session for a specific phone number.
    
    Args:
        phone: The user's phone number
        
    Returns:
        Session dictionary or None if not found
    """
    cursor = conn.cursor()
    cursor.execute("""
        SELECT step, data, last_active 
        FROM sessions 
        WHERE phone = ?
    """, (phone,))
    
    result = cursor.fetchone()
    
    if result:
        try:
            data = json.loads(result['data']) if result['data'] else {}
            return {
                "step": result['step'],
                "data": data,
                "last_active": result['last_active']
            }
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse session data for {phone}: {e}")
            return {
                "step": result['step'],
                "data": {},
                "last_active": result['last_active']
            }
    
    return None


@with_db_connection
def save_session(conn, phone: str, step: str, data: dict) -> bool:
    """
    Save or update a session.
    
    Args:
        phone: The user's phone number
        step: Current step in the flow
        data: Session data dictionary
        
    Returns:
        True if successful, False otherwise
    """
    cursor = conn.cursor()
    session_json = json.dumps(data)
    now = datetime.now().isoformat()
    
    try:
        cursor.execute("""
            INSERT INTO sessions (phone, step, data, last_active, warned)
            VALUES (?, ?, ?, ?, 0)
            ON CONFLICT(phone) DO UPDATE SET 
                step = excluded.step,
                data = excluded.data,
                last_active = excluded.last_active,
                warned = 0
        """, (phone, step, session_json, now))
        
        conn.commit()
        logger.debug(f"Session saved for {phone}: step={step}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to save session for {phone}: {e}")
        conn.rollback()
        return False


@with_db_connection
def delete_session(conn, phone: str) -> bool:
    """
    Delete a session.
    
    Args:
        phone: The user's phone number
        
    Returns:
        True if successful
    """
    cursor = conn.cursor()
    cursor.execute("DELETE FROM sessions WHERE phone = ?", (phone,))
    conn.commit()
    logger.debug(f"Session deleted for {phone}")
    return True


@with_db_connection
def mark_warned(conn, phone: str) -> bool:
    """
    Mark a session as having received a timeout warning.
    
    Args:
        phone: The user's phone number
        
    Returns:
        True if successful
    """
    cursor = conn.cursor()
    cursor.execute("UPDATE sessions SET warned = 1 WHERE phone = ?", (phone,))
    conn.commit()
    return True


@with_db_connection
def update_last_active(conn, phone: str) -> bool:
    """
    Update the last_active timestamp and reset warned flag.
    
    Args:
        phone: The user's phone number
        
    Returns:
        True if successful
    """
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE sessions
        SET last_active = ?, warned = 0
        WHERE phone = ?
    """, (datetime.now().isoformat(), phone))
    conn.commit()
    return True


@with_db_connection
def get_user_step(conn, phone: str) -> Optional[str]:
    """
    Get the current step for a user.
    
    Args:
        phone: The user's phone number
        
    Returns:
        Current step string or None
    """
    cursor = conn.cursor()
    cursor.execute("SELECT step FROM sessions WHERE phone = ?", (phone,))
    result = cursor.fetchone()
    return result['step'] if result else None


@with_db_connection
def update_user_step(conn, phone: str, step: str) -> bool:
    """
    Update just the step for a user.
    
    Args:
        phone: The user's phone number
        step: New step value
        
    Returns:
        True if successful
    """
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO sessions (phone, step, data, last_active)
        VALUES (?, ?, '{}', CURRENT_TIMESTAMP)
        ON CONFLICT(phone) DO UPDATE SET 
            step = excluded.step, 
            last_active = CURRENT_TIMESTAMP
    """, (phone, step))
    conn.commit()
    return True


@with_db_connection
def update_session_data(conn, phone: str, key: str, value: Any) -> bool:
    """
    Update a specific key in the session data.
    
    Args:
        phone: The user's phone number
        key: Data key to update
        value: New value
        
    Returns:
        True if successful
    """
    cursor = conn.cursor()
    
    # Get existing data
    cursor.execute("SELECT data FROM sessions WHERE phone = ?", (phone,))
    result = cursor.fetchone()
    
    existing_data = json.loads(result['data']) if result and result['data'] else {}
    existing_data[key] = value
    updated_data = json.dumps(existing_data)
    
    cursor.execute("""
        UPDATE sessions 
        SET data = ?, last_active = CURRENT_TIMESTAMP 
        WHERE phone = ?
    """, (updated_data, phone))
    
    conn.commit()
    return True


# ============================================================================
# SESSION LIFECYCLE FUNCTIONS
# ============================================================================

def cancel_session(phone: str) -> None:
    """
    Cancel and clean up a user's session.
    Sends a notification message to the user.
    
    Args:
        phone: The user's phone number
    """
    try:
        session = load_session(phone)
        if session:
            delete_session(phone)
        
        whatsapp.send_message(
            "🚫 Your session has been cancelled.\n\n"
            "_You can start a new session anytime by sending a message._",
            phone
        )
        logger.info(f"Session cancelled for {phone}")
        
    except Exception as e:
        logger.error(f"Failed to cancel session for {phone}: {e}")


def check_session_timeout(phone: str) -> bool:
    """
    Check if a session has timed out due to inactivity.
    
    Args:
        phone: The user's phone number
        
    Returns:
        True if session timed out, False otherwise
    """
    try:
        session = load_session(phone)
        
        if not session:
            return False
        
        last_active = session.get("last_active")
        if not last_active:
            return False
        
        # Parse last_active timestamp
        if isinstance(last_active, str):
            try:
                last_active_dt = datetime.fromisoformat(last_active)
            except ValueError:
                logger.warning(f"Invalid last_active format for {phone}: {last_active}")
                return False
        else:
            last_active_dt = last_active
        
        # Check if timeout exceeded
        if datetime.now() - last_active_dt > timedelta(minutes=SESSION_TIMEOUT_MINUTES):
            delete_session(phone)
            whatsapp.send_message(
                "⏱️ Your session has timed out due to inactivity.\n\n"
                "_Send any message to start a new session._",
                phone
            )
            logger.info(f"Session timed out for {phone}")
            return True
        
        return False
        
    except Exception as e:
        logger.error(f"Error checking session timeout for {phone}: {e}")
        return False


def initialize_session(phone: str, name: str = "there") -> str:
    """
    Initialize a new session for a user.
    
    Args:
        phone: The user's phone number
        name: User's name (optional)
        
    Returns:
        "ok" status string
    """
    try:
        logger.info(f"Creating new session for {phone} ({name})")
        
        # Create session data
        session_data = {
            "step": "name",
            "data": {"user_name": name},
            "last_active": datetime.now().isoformat()
        }
        
        save_session(phone, session_data["step"], session_data["data"])
        
        # Send welcome message
        if not is_known_user(phone):
            whatsapp.send_message(
                "👋 Hello! I'm *LatterPay*, your trusted payments assistant.\n\n"
                "💳 I help you make donations and payments quickly and securely.\n\n"
                "Let's get started! Please enter the *full name* of the person making the payment.",
                phone
            )
            add_known_user(phone)
            logger.info(f"New user registered: {phone}")
        else:
            whatsapp.send_message(
                "🔄 Welcome back to *LatterPay*!\n\n"
                "Ready for another transaction? "
                "Please enter the *name of the person* making this payment.",
                phone
            )
            logger.info(f"Returning user: {phone}")
        
        return "ok"
        
    except Exception as e:
        logger.error(f"Failed to initialize session for {phone}: {e}", exc_info=True)
        # Try to send error message
        try:
            whatsapp.send_message(
                "😔 Sorry, something went wrong. Please try again in a moment.",
                phone
            )
        except:
            pass
        return "error"


# ============================================================================
# SESSION MONITORING DAEMON
# ============================================================================

class SessionMonitor:
    """
    Background daemon that monitors sessions for timeout/warning.
    """
    
    def __init__(self, check_interval: int = 60):
        self.check_interval = check_interval
        self._running = False
        self._thread: Optional[threading.Thread] = None
    
    def start(self) -> None:
        """Start the session monitor daemon."""
        if self._running:
            logger.warning("Session monitor is already running")
            return
        
        self._running = True
        self._thread = threading.Thread(
            target=self._run_monitor,
            daemon=True,
            name="SessionMonitor"
        )
        self._thread.start()
        logger.info("Session monitor daemon started")
    
    def stop(self) -> None:
        """Stop the session monitor daemon."""
        self._running = False
        logger.info("Session monitor daemon stopped")
    
    def _run_monitor(self) -> None:
        """Main monitoring loop."""
        while self._running:
            try:
                self._check_sessions()
            except Exception as e:
                logger.error(f"Session monitor error: {e}", exc_info=True)
            
            time.sleep(self.check_interval)
    
    def _check_sessions(self) -> None:
        """Check all sessions for timeout/warning conditions."""
        sessions = get_all_sessions()
        now = datetime.now()
        
        for session in sessions:
            try:
                phone = session["phone"]
                last_active = session["last_active"]
                warned = session.get("warned", 0)
                
                minutes_inactive = (now - last_active).total_seconds() / 60
                
                # Send warning at ~4 minutes if not already warned
                if SESSION_WARNING_MINUTES < minutes_inactive < SESSION_TIMEOUT_MINUTES and not warned:
                    remaining = int((SESSION_TIMEOUT_MINUTES - minutes_inactive) * 60)
                    whatsapp.send_message(
                        f"⚠️ *Heads up!* Your session will expire in ~{remaining} seconds.\n\n"
                        "_Reply with any message to keep your session active._",
                        phone
                    )
                    mark_warned(phone)
                    logger.debug(f"Sent timeout warning to {phone}")
                
                # Cancel session at timeout
                elif minutes_inactive >= SESSION_TIMEOUT_MINUTES:
                    cancel_session(phone)
                    logger.info(f"Auto-cancelled timed out session for {phone}")
                    
            except Exception as e:
                logger.error(f"Error processing session for {session.get('phone', 'unknown')}: {e}")


# Global session monitor instance
_session_monitor: Optional[SessionMonitor] = None


def monitor_sessions() -> None:
    """Start the global session monitor daemon."""
    global _session_monitor
    
    if _session_monitor is None:
        _session_monitor = SessionMonitor(check_interval=60)
    
    _session_monitor.start()


def stop_session_monitor() -> None:
    """Stop the global session monitor daemon."""
    global _session_monitor
    
    if _session_monitor:
        _session_monitor.stop()
        _session_monitor = None


# ============================================================================
# REGISTRATION DATA FUNCTIONS
# ============================================================================

@with_db_connection
def get_user_registration(conn, phone: str) -> Optional[Dict[str, Any]]:
    """
    Get complete registration data for a user from their session.
    
    Args:
        phone: The user's phone number
        
    Returns:
        Registration data dictionary or None
    """
    session = load_session(phone)
    if not session:
        return None
    return session.get("data", {})


@with_db_connection
def save_registration_to_db(conn, phone: str, **data) -> bool:
    """
    Save registration data to the registrations table.
    
    Args:
        phone: The user's phone number
        **data: Registration fields (name, surname, email, skill, area)
        
    Returns:
        True if successful
    """
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            INSERT OR REPLACE INTO registrations 
            (phone, name, surname, email, skill, area, registered_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            phone,
            data.get('name'),
            data.get('surname'),
            data.get('email'),
            data.get('skill'),
            data.get('area'),
            datetime.now().isoformat()
        ))
        
        conn.commit()
        logger.info(f"Registration saved for {phone}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to save registration for {phone}: {e}")
        conn.rollback()
        return False


# ============================================================================
# UTILITY EXPORTS
# ============================================================================

__all__ = [
    # Session CRUD
    'load_session',
    'save_session',
    'delete_session',
    'get_all_sessions',
    
    # Session lifecycle
    'initialize_session',
    'cancel_session',
    'check_session_timeout',
    'update_last_active',
    
    # Session data operations
    'get_user_step',
    'update_user_step',
    'update_session_data',
    
    # Monitoring
    'monitor_sessions',
    'stop_session_monitor',
    
    # Registration
    'get_user_registration',
    'save_registration_to_db',
]
