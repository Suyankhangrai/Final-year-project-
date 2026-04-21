import os
import bcrypt
import mysql.connector
from mysql.connector import pooling


DB_CONFIG = {
    "host":     "localhost",
    "user":     "root",
    "password": "mypetfeeder123",
    "database": "pet_feeder_db",
}

_pool = pooling.MySQLConnectionPool(
    pool_name="pet_feeder_pool",
    pool_size=5,
    **DB_CONFIG,
)

def get_db():
    return _pool.get_connection()



def get_user_by_username_and_password(username: str, plain_password: str):
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT user_id, email, password_hash FROM users WHERE email = %s",
            (username,),
        )
        row = cur.fetchone()
        cur.close()
    finally:
        conn.close()

    if not row:
        return None

    
    if plain_password != row["password_hash"]:
        return None

    
    return {"user_id": row["user_id"], "email": row["email"]}




def get_all_pets():
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute("""
            SELECT pet_id, user_id, pet_name, species, breed,
                   rfid_tag_uid, birth_date, photo_url, created_at
            FROM pets
            ORDER BY created_at DESC
        """)
        rows = cur.fetchall()
        cur.close()
    finally:
        conn.close()
    return rows


def get_pet_by_id(pet_id):
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute("""
            SELECT pet_id, user_id, pet_name, species, breed,
                   rfid_tag_uid, birth_date, photo_url, created_at
            FROM pets WHERE pet_id = %s
        """, (pet_id,))
        row = cur.fetchone()
        cur.close()
    finally:
        conn.close()
    return row


def get_pet_by_rfid(rfid_tag: str):
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT * FROM pets WHERE rfid_tag_uid = %s", (rfid_tag,)
        )
        row = cur.fetchone()
        cur.close()
    finally:
        conn.close()
    return row


def insert_pet(name, species, breed, birth_date, rfid, photo_url, user_id):
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO pets
              (user_id, pet_name, species, breed,
               rfid_tag_uid, birth_date, photo_url, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
        """, (user_id, name, species, breed, rfid, birth_date, photo_url))
        conn.commit()
        cur.close()
    finally:
        conn.close()


def delete_pet(pet_id):
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM pets WHERE pet_id = %s", (pet_id,))
        conn.commit()
        cur.close()
    finally:
        conn.close()


def update_pet_rfid(pet_id: int, rfid_uid: str):
    
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE pets SET rfid_tag_uid = %s WHERE pet_id = %s",
            (rfid_uid, pet_id),
        )
        conn.commit()
        cur.close()
    finally:
        conn.close()




def insert_feed_event(pet_id, triggered_by, requested_grams, dispensed_grams, status):
    
    conn = get_db()
    try:
        cur = conn.cursor()

       
        cur.execute("""
            INSERT INTO feeding_events
              (pet_id, triggered_by, requested_grams,
               dispensed_grams, status, event_time)
            VALUES (%s, %s, %s, %s, %s, NOW())
        """, (pet_id, triggered_by, requested_grams, dispensed_grams, status))

    
        cur.execute("""
            INSERT INTO feeding_log (pet_name, grams, source, fed_at)
            SELECT pet_name, %s, %s, NOW()
            FROM pets WHERE pet_id = %s
        """, (dispensed_grams, triggered_by, pet_id))

        conn.commit()
        cur.close()
    finally:
        conn.close()


def log_feeding_event(pet_name: str, grams: float, source: str):
    
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO feeding_log (pet_name, grams, source, fed_at) VALUES (%s, %s, %s, NOW())",
            (pet_name, grams, source),
        )
        conn.commit()
        cur.close()
    finally:
        conn.close()


def get_feed_history():
   
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute("""
            SELECT pet_name, grams, source, fed_at AS event_time
            FROM feeding_log
            ORDER BY fed_at DESC
        """)
        rows = cur.fetchall()
        cur.close()
    finally:
        conn.close()
    return rows


def create_schedule(pet_id, label, feed_time, portion_grams, days, device_id=1):
    
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO feeding_schedules
              (pet_id, device_id, label, feed_time, portion_grams, days, is_active, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, TRUE, NOW())
        """, (pet_id, device_id, label, feed_time, portion_grams, days))
        conn.commit()
        cur.close()
    finally:
        conn.close()


def get_all_schedules():
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute("""
            SELECT s.schedule_id, s.feed_time, s.portion_grams AS grams,
                   s.days, s.is_active, p.pet_name
            FROM feeding_schedules s
            JOIN pets p ON s.pet_id = p.pet_id
        """)
        rows = cur.fetchall()
        cur.close()
    finally:
        conn.close()
    return rows


def get_active_schedules():
    
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute("""
            SELECT s.schedule_id, s.feed_time, s.portion_grams AS grams,
                   s.days, s.last_served_date, p.pet_name, p.pet_id
            FROM feeding_schedules s
            JOIN pets p ON s.pet_id = p.pet_id
            WHERE s.is_active = TRUE
        """)
        rows = cur.fetchall()
        cur.close()
    finally:
        conn.close()

    for row in rows:
        td = row["feed_time"]
        if hasattr(td, "total_seconds"):
            total = int(td.total_seconds())
            row["feed_time"] = f"{total // 3600:02d}:{(total % 3600) // 60:02d}"

    return rows


def update_last_served(schedule_id: int, date_str: str):
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE feeding_schedules SET last_served_date = %s WHERE schedule_id = %s",
            (date_str, schedule_id),
        )
        conn.commit()
        cur.close()
    finally:
        conn.close()


def delete_schedule(schedule_id: int):
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM feeding_schedules WHERE schedule_id = %s", (schedule_id,)
        )
        conn.commit()
        cur.close()
    finally:
        conn.close()


def toggle_schedule(schedule_id: int, is_active: bool):
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE feeding_schedules SET is_active = %s WHERE schedule_id = %s",
            (is_active, schedule_id),
        )
        conn.commit()
        cur.close()
    finally:
        conn.close()


_DEFAULT_PORTION_GRAMS = 50.0  


def get_all_pets_api():
   
    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute("""
            SELECT rfid_tag_uid AS rfid,
                   pet_name     AS name,
                   %s           AS portion
            FROM pets
        """, (_DEFAULT_PORTION_GRAMS,))
        rows = cur.fetchall()
        cur.close()
    finally:
        conn.close()
    return rows


def get_pending_command():

    conn = get_db()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT * FROM manual_feeds WHERE status = 'pending' ORDER BY created_at ASC LIMIT 1"
        )
        command = cur.fetchone()
        if command:
            cur.execute(
                "UPDATE manual_feeds SET status = 'completed' WHERE id = %s",
                (command["id"],),
            )
            conn.commit()
        cur.close()
    finally:
        conn.close()
    return command
