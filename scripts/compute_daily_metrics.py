import os
import sys
import json
import sqlite3
from datetime import date, timedelta, datetime
import psycopg2

POSTGRES_URL = os.environ.get(
    "DATABASE_URL", 
    "postgresql://penner_admin:penner_secret_password_2026@localhost:5432/penner_governance_db"
)

SQLITE_TRACKING_PATH = "/Users/thejoshuapenner/My Drive/Penner Strategy/sao-scraper/usage_tracking.db"

STOP_WORDS = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for", "of", "with",
    "is", "are", "was", "were", "be", "been", "being", "have", "has", "had", "do", "does",
    "did", "about", "what", "how", "why", "where", "who", "which", "this", "that", "these",
    "those", "i", "me", "my", "you", "your", "he", "him", "his", "she", "her", "it", "its",
    "we", "us", "our", "they", "them", "their", "audit", "audits", "finding", "findings",
    "city", "county", "council", "meeting", "minutes"
}

def get_db_connection():
    try:
        conn = psycopg2.connect(POSTGRES_URL)
        return conn, True
    except Exception:
        try:
            conn = sqlite3.connect(SQLITE_TRACKING_PATH)
            conn.row_factory = sqlite3.Row
            return conn, False
        except Exception as e:
            print(f"Failed to open SQLite fallback database: {e}")
            return None, False

def get_first_event_dates(conn, is_pg):
    cur = conn.cursor()
    first_dates = {}
    
    if is_pg:
        cur.execute("SELECT anonymous_user_id, MIN(timestamp)::date FROM usage_events GROUP BY anonymous_user_id")
    else:
        cur.execute("SELECT anonymous_user_id, MIN(date(timestamp)) FROM usage_events GROUP BY anonymous_user_id")
        
    rows = cur.fetchall()
    for r in rows:
        # PostgreSQL yields date object directly; SQLite yields string 'YYYY-MM-DD'
        user_id = r[0]
        date_val = r[1]
        if isinstance(date_val, str):
            date_val = date.fromisoformat(date_val)
        first_dates[user_id] = date_val
    cur.close()
    return first_dates

def get_user_total_counts_up_to(conn, is_pg, target_date):
    cur = conn.cursor()
    total_counts = {}
    
    if is_pg:
        cur.execute(
            "SELECT anonymous_user_id, COUNT(*) FROM usage_events WHERE timestamp::date <= %s GROUP BY anonymous_user_id",
            (target_date,)
        )
    else:
        cur.execute(
            "SELECT anonymous_user_id, COUNT(*) FROM usage_events WHERE date(timestamp) <= ? GROUP BY anonymous_user_id",
            (target_date.isoformat(),)
        )
        
    rows = cur.fetchall()
    for r in rows:
        total_counts[r[0]] = r[1]
    cur.close()
    return total_counts

def get_user_active_days_in_week(conn, is_pg, end_date):
    cur = conn.cursor()
    active_days = {}
    start_date = end_date - timedelta(days=6)
    
    if is_pg:
        cur.execute(
            "SELECT anonymous_user_id, COUNT(DISTINCT timestamp::date) FROM usage_events WHERE timestamp::date >= %s AND timestamp::date <= %s GROUP BY anonymous_user_id",
            (start_date, end_date)
        )
    else:
        cur.execute(
            "SELECT anonymous_user_id, COUNT(DISTINCT date(timestamp)) FROM usage_events WHERE date(timestamp) >= ? AND date(timestamp) <= ? GROUP BY anonymous_user_id",
            (start_date.isoformat(), end_date.isoformat())
        )
        
    rows = cur.fetchall()
    for r in rows:
        active_days[r[0]] = r[1]
    cur.close()
    return active_days

def compute_metrics_for_date(target_date=None):
    if target_date is None:
        target_date = date.today() - timedelta(days=1)
        
    print(f"Aggregating metrics for date: {target_date}")
    
    conn, is_pg = get_db_connection()
    if not conn:
        print("Database not available. Exiting.")
        sys.exit(1)
        
    try:
        cur = conn.cursor()
        
        # 1. Fetch events for the target day
        if is_pg:
            cur.execute(
                """
                SELECT anonymous_user_id, session_id, message_count_in_session, query_text, jurisdiction 
                FROM usage_events 
                WHERE timestamp::date = %s
                """,
                (target_date,)
            )
        else:
            cur.execute(
                """
                SELECT anonymous_user_id, session_id, message_count_in_session, query_text, jurisdiction 
                FROM usage_events 
                WHERE date(timestamp) = ?
                """,
                (target_date.isoformat(),)
            )
            
        events = cur.fetchall()
        print(f"Found {len(events)} events for {target_date}")
        
        # Basic counters
        users = set()
        sessions = {}
        msg_counts_per_user = {}
        query_words = []
        jurisdictions = {}
        
        for ev in events:
            user_id = ev[0]
            session_id = ev[1]
            msg_num = ev[2]
            q_text = ev[3]
            juris = ev[4]
            
            users.add(user_id)
            msg_counts_per_user[user_id] = msg_counts_per_user.get(user_id, 0) + 1
            
            # Keep track of max message number in each session
            sessions[session_id] = max(sessions.get(session_id, 0), msg_num)
            
            # Words for popular topics
            if q_text:
                words = [w.lower().strip(",.?!()\"'") for w in q_text.split()]
                query_words.extend([w for w in words if w and w not in STOP_WORDS])
                
            # Jurisdiction hits
            if juris:
                jurisdictions[juris] = jurisdictions.get(juris, 0) + 1
                
        dau = len(users)
        total_messages = len(events)
        avg_messages_per_user = round(total_messages / dau, 2) if dau > 0 else 0.0
        
        # Session depth
        total_sessions = len(sessions)
        avg_session_depth = round(sum(sessions.values()) / total_sessions, 2) if total_sessions > 0 else 0.0
        
        # Heavy users day: > 15 messages in the day
        heavy_users_day_count = sum(1 for c in msg_counts_per_user.values() if c > 15)
        
        # Heavy users total: > 50 messages total up to target_date
        total_counts = get_user_total_counts_up_to(conn, is_pg, target_date)
        heavy_users_total_count = sum(1 for c in total_counts.values() if c > 50)
        
        # Heavy users active on 3+ different days in the week ending on target_date
        weekly_active_days = get_user_active_days_in_week(conn, is_pg, target_date)
        heavy_users_multi_day_count = sum(1 for c in weekly_active_days.values() if c >= 3)
        
        # Retention rates (cohort based)
        first_event_dates = get_first_event_dates(conn, is_pg)
        
        def calculate_cohort_retention(cohort_date, check_date):
            # Users whose first day was cohort_date
            cohort = [u for u, fd in first_event_dates.items() if fd == cohort_date]
            if not cohort:
                return 0.0
                
            # How many cohort users are active on check_date?
            # Fetch active users on check_date
            if is_pg:
                cur.execute("SELECT DISTINCT anonymous_user_id FROM usage_events WHERE timestamp::date = %s", (check_date,))
            else:
                cur.execute("SELECT DISTINCT anonymous_user_id FROM usage_events WHERE date(timestamp) = ?", (check_date.isoformat(),))
                
            active_on_day = {r[0] for r in cur.fetchall()}
            retained = sum(1 for u in cohort if u in active_on_day)
            return round((retained / len(cohort)) * 100.0, 2)
            
        retention_day_2 = calculate_cohort_retention(target_date - timedelta(days=1), target_date)
        retention_day_7 = calculate_cohort_retention(target_date - timedelta(days=6), target_date)
        retention_day_30 = calculate_cohort_retention(target_date - timedelta(days=29), target_date)
        
        # Drop-off stats distribution
        drop_off_stats = {}
        for max_msg in sessions.values():
            label = str(max_msg) if max_msg <= 5 else "6+"
            drop_off_stats[label] = drop_off_stats.get(label, 0) + 1
            
        # Popular topics (top 15 keywords)
        word_counts = {}
        for w in query_words:
            word_counts[w] = word_counts.get(w, 0) + 1
        sorted_words = sorted(word_counts.items(), key=lambda x: x[1], reverse=True)[:15]
        popular_topics = {
            "keywords": sorted_words,
            "jurisdictions": sorted(jurisdictions.items(), key=lambda x: x[1], reverse=True)[:5]
        }
        
        # 2. Upsert aggregated daily metrics
        drop_off_json = json.dumps(drop_off_stats)
        topics_json = json.dumps(popular_topics)
        
        if is_pg:
            cur.execute(
                """
                INSERT INTO daily_usage_aggregates (
                    date, dau, total_messages, avg_messages_per_user, avg_session_depth,
                    heavy_users_day_count, heavy_users_total_count, heavy_users_multi_day_count,
                    retention_day_2, retention_day_7, retention_day_30,
                    drop_off_stats, popular_topics
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (date) DO UPDATE SET
                    dau = EXCLUDED.dau,
                    total_messages = EXCLUDED.total_messages,
                    avg_messages_per_user = EXCLUDED.avg_messages_per_user,
                    avg_session_depth = EXCLUDED.avg_session_depth,
                    heavy_users_day_count = EXCLUDED.heavy_users_day_count,
                    heavy_users_total_count = EXCLUDED.heavy_users_total_count,
                    heavy_users_multi_day_count = EXCLUDED.heavy_users_multi_day_count,
                    retention_day_2 = EXCLUDED.retention_day_2,
                    retention_day_7 = EXCLUDED.retention_day_7,
                    retention_day_30 = EXCLUDED.retention_day_30,
                    drop_off_stats = EXCLUDED.drop_off_stats,
                    popular_topics = EXCLUDED.popular_topics
                """,
                (
                    target_date, dau, total_messages, avg_messages_per_user, avg_session_depth,
                    heavy_users_day_count, heavy_users_total_count, heavy_users_multi_day_count,
                    retention_day_2, retention_day_7, retention_day_30,
                    drop_off_json, topics_json
                )
            )
        else:
            cur.execute(
                """
                INSERT OR REPLACE INTO daily_usage_aggregates (
                    date, dau, total_messages, avg_messages_per_user, avg_session_depth,
                    heavy_users_day_count, heavy_users_total_count, heavy_users_multi_day_count,
                    retention_day_2, retention_day_7, retention_day_30,
                    drop_off_stats, popular_topics
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    target_date.isoformat(), dau, total_messages, avg_messages_per_user, avg_session_depth,
                    heavy_users_day_count, heavy_users_total_count, heavy_users_multi_day_count,
                    retention_day_2, retention_day_7, retention_day_30,
                    drop_off_json, topics_json
                )
            )
            
        conn.commit()
        print(f"Metrics upserted successfully for {target_date}!")
        
        # 3. Purge raw logs older than 90 days
        print("Purging raw usage events older than 90 days...")
        if is_pg:
            cur.execute("DELETE FROM usage_events WHERE timestamp < NOW() - INTERVAL '90 days'")
        else:
            cur.execute("DELETE FROM usage_events WHERE timestamp < datetime('now', '-90 days')")
        conn.commit()
        print("Cleanup completed successfully!")
        
        cur.close()
        conn.close()
    except Exception as e:
        print("Error processing daily aggregation script:", e)
        if conn:
            conn.rollback()

if __name__ == "__main__":
    # If a date string is passed as argument, use it; otherwise defaults to yesterday
    if len(sys.argv) > 1:
        try:
            input_date = date.fromisoformat(sys.argv[1])
            compute_metrics_for_date(input_date)
        except Exception as e:
            print("Invalid date format. Use YYYY-MM-DD. Error:", e)
    else:
        compute_metrics_for_date()
