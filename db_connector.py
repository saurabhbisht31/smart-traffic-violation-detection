# db_connector.py
import os
import csv
import mimetypes
from datetime import datetime
import smtplib
from email.message import EmailMessage

# MySQL connector
import mysql.connector
from mysql.connector import Error

# Optional PDF generation
try:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    REPORTLAB_AVAILABLE = True
except Exception:
    REPORTLAB_AVAILABLE = False

# Import configuration (ensure config.py exists)
try:
    from config import (
        DB_HOST, DB_USER, DB_PASSWORD, DB_NAME,
        EVIDENCE_DIR, CHALLAN_DIR,
        EMAIL_SENDER, EMAIL_PASSWORD, SMTP_SERVER, SMTP_PORT,
        FINE_AMOUNT, ISSUER_NAME
    )
except Exception as e:
    raise ImportError(f"Failed to import config values: {e}")

# Ensure directories
os.makedirs(EVIDENCE_DIR, exist_ok=True)
os.makedirs(CHALLAN_DIR, exist_ok=True)

CSV_FALLBACK = os.path.join(os.getcwd(), "violations_log.csv")
if not os.path.exists(CSV_FALLBACK):
    with open(CSV_FALLBACK, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "license_plate", "camera_id", "violation_type", "image_path", "details"])

# ----------------- DB helpers -----------------
def _get_conn():
    return mysql.connector.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        autocommit=False
    )

def ensure_tables_exist():
    """
    Create minimal required tables if they don't exist.
    """
    conn = None
    try:
        conn = _get_conn()
        cur = conn.cursor()
        # violationtypes
        cur.execute("""
            CREATE TABLE IF NOT EXISTS violationtypes (
                type_id INT AUTO_INCREMENT PRIMARY KEY,
                type_name VARCHAR(128) UNIQUE,
                fine_amount DECIMAL(10,2)
            )
        """)
        # registered_vehicles
        cur.execute("""
            CREATE TABLE IF NOT EXISTS registered_vehicles (
                license_plate VARCHAR(50) PRIMARY KEY,
                owner_name VARCHAR(255),
                email VARCHAR(255),
                mobile_no VARCHAR(50),
                address VARCHAR(512)
            )
        """)
        # violations
        cur.execute("""
            CREATE TABLE IF NOT EXISTS violations (
                id INT AUTO_INCREMENT PRIMARY KEY,
                violation_timestamp DATETIME NOT NULL,
                license_plate_text VARCHAR(200) NOT NULL,
                camera_id INT DEFAULT 1,
                violation_type_id INT,
                image_path VARCHAR(512),
                details VARCHAR(512),
                FOREIGN KEY (violation_type_id) REFERENCES violationtypes(type_id)
            )
        """)
        conn.commit()

        # Ensure default violation type
        cur.execute("SELECT type_id FROM violationtypes WHERE type_name=%s", ("No Helmet",))
        if cur.fetchone() is None:
            cur.execute("INSERT INTO violationtypes (type_name, fine_amount) VALUES (%s, %s)",
                        ("No Helmet", FINE_AMOUNT))
            conn.commit()

        cur.close()
        return True
    except Exception as e:
        print("[DB] ensure_tables_exist error:", e)
        return False
    finally:
        try:
            if conn and conn.is_connected():
                conn.close()
        except:
            pass

# ----------------- PDF generator -----------------
def generate_challan_pdf(owner_name, license_plate, violation_type, fine_amount, timestamp, image_path=None):
    """
    Create a simple e-challan PDF and return its path.
    Requires reportlab. If not installed, returns None.
    """
    if not REPORTLAB_AVAILABLE:
        print("[PDF] reportlab not installed — skipping PDF generation.")
        return None

    safe_ts = timestamp.replace(":", "-").replace(" ", "_")
    pdf_name = f"e_challan_{license_plate}_{safe_ts}.pdf"
    pdf_path = os.path.join(CHALLAN_DIR, pdf_name)

    try:
        c = canvas.Canvas(pdf_path, pagesize=A4)
        width, height = A4

        # Header
        c.setFont("Helvetica-Bold", 18)
        c.drawCentredString(width / 2, height - 72, "Traffic Violation e-Challan")

        # Info
        c.setFont("Helvetica", 12)
        y = height - 120
        line_gap = 18
        info = [
            ("Owner Name", owner_name or "N/A"),
            ("License Plate", license_plate),
            ("Violation Type", violation_type),
            ("Fine Amount", f"₹{fine_amount:.2f}"),
            ("Date & Time", timestamp),
            ("Issued By", ISSUER_NAME or "Smart Traffic Detection System"),
        ]
        for k, v in info:
            c.drawString(72, y, f"{k}: {v}")
            y -= line_gap

        # Evidence image
        if image_path and os.path.exists(image_path):
            try:
                img_x = 72
                img_y = y - 220
                # keep a safe size for the image
                c.drawImage(image_path, img_x, img_y, width=360, height=220, preserveAspectRatio=True, mask='auto')
            except Exception as img_err:
                print("[PDF] image attach error:", img_err)

        c.setFont("Helvetica-Oblique", 10)
        c.drawCentredString(width / 2, 40, "This is a system-generated challan. Please pay within 7 days.")
        c.save()
        print(f"[PDF] Generated: {pdf_path}")
        return pdf_path
    except Exception as e:
        print("[PDF] generation error:", e)
        return None

# ----------------- Email sender -----------------
def send_email_with_attachments(to_email, subject, body, attachments=None):
    """
    Send an email with attachments using SMTP details from config.
    Returns True on success.
    """
    try:
        msg = EmailMessage()
        msg["From"] = EMAIL_SENDER
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.set_content(body)

        if attachments:
            for p in attachments:
                if not p or not os.path.exists(p):
                    continue
                ctype, encoding = mimetypes.guess_type(p)
                if ctype:
                    maintype, subtype = ctype.split("/", 1)
                else:
                    maintype, subtype = "application", "octet-stream"
                with open(p, "rb") as f:
                    msg.add_attachment(f.read(), maintype=maintype, subtype=subtype, filename=os.path.basename(p))

        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=30) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.ehlo()
            smtp.login(EMAIL_SENDER, EMAIL_PASSWORD)
            smtp.send_message(msg)

        print(f"[EMAIL] Sent to {to_email}")
        return True
    except Exception as e:
        print("[EMAIL] send error:", e)
        return False

# ----------------- Main logging function -----------------
def log_violation_to_db(license_plate, image_path, confidence, camera_id=1, violation_type_name="No Helmet"):
    """
    Insert violation into DB. If owner exists (and plate is not TEMP), generate pdf and email challan.
    Returns True on DB insert success, False otherwise.
    """
    # ensure tables exist
    ensure_tables_exist()

    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    stored_image_path = image_path  # adminapp provides full path or relative path

    conn = None
    try:
        conn = _get_conn()
        cur = conn.cursor()

        # fetch violation type id
        cur.execute("SELECT type_id FROM violationtypes WHERE type_name=%s LIMIT 1", (violation_type_name,))
        row = cur.fetchone()
        if row:
            violation_type_id = row[0]
        else:
            violation_type_id = 1

        # Insert violation
        cur.execute("""
            INSERT INTO violations (violation_timestamp, license_plate_text, camera_id, violation_type_id, image_path, details)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (ts, license_plate, camera_id, violation_type_id, stored_image_path, f"confidence={confidence}"))
        conn.commit()
        cur.close()

        print(f"[DB] Inserted violation for {license_plate}")

        # lookup owner (if any)
        try:
            cur2 = conn.cursor()
            cur2.execute("SELECT owner_name, email FROM registered_vehicles WHERE license_plate = %s LIMIT 1", (license_plate,))
            owner = cur2.fetchone()
            cur2.close()
        except Exception as e:
            print("[DB] owner lookup error:", e)
            owner = None

        # Only send email if owner exists and plate is not TEMP*
        is_temp = str(license_plate).upper().startswith("TEMP")
        if owner and owner[1] and not is_temp:
            owner_name, owner_email = owner[0], owner[1]
            pdf_path = None
            try:
                pdf_path = generate_challan_pdf(owner_name, license_plate, violation_type_name, FINE_AMOUNT, ts, stored_image_path)
            except Exception as e:
                print("[PDF] generation failed:", e)
                pdf_path = None

            attachments = []
            if stored_image_path and os.path.exists(stored_image_path):
                attachments.append(stored_image_path)
            if pdf_path:
                attachments.append(pdf_path)

            subject = f"e-Challan: {license_plate} - {violation_type_name}"
            body = (f"Dear {owner_name},\n\nA {violation_type_name} violation was recorded for your vehicle {license_plate} on {ts}.\n"
                    f"Fine: ₹{FINE_AMOUNT:.2f}\nPlease find the attached e-challan and evidence image.\n\nRegards,\n{ISSUER_NAME}")

            sent = send_email_with_attachments(owner_email, subject, body, attachments)
            if sent:
                print(f"[EMAIL] e-challan sent to {owner_email}")
            else:
                print(f"[EMAIL] failed to send to {owner_email}")

        else:
            if is_temp:
                print(f"[EMAIL] Skipping email for TEMP plate {license_plate}")
            else:
                print(f"[DB] No registered owner found for {license_plate} — skipping email.")

        if conn and conn.is_connected():
            conn.close()
        return True

    except Error as db_err:
        print("[DB ERROR] insert failed:", db_err)
        # fallback to CSV logging
        try:
            with open(CSV_FALLBACK, "a", newline="") as f:
                writer = csv.writer(f)
                writer.writerow([ts, license_plate, camera_id, violation_type_name, stored_image_path, f"confidence={confidence}"])
            print("[CSV] violation logged as fallback")
        except Exception as e:
            print("[CSV] fallback failed:", e)
        try:
            if conn and conn.is_connected():
                conn.close()
        except:
            pass
        return False
    except Exception as e:
        print("[ERROR] log_violation_to_db general error:", e)
        try:
            if conn and conn.is_connected():
                conn.close()
        except:
            pass
        return False
