import cv2
from flask import Flask, Response, request, redirect, url_for, session, render_template
from ultralytics import YOLO
import easyocr
import numpy as np
import time
import os
from datetime import datetime
import random
import string

from db_connector import log_violation_to_db
from config import EVIDENCE_DIR

from sqlalchemy import create_engine, text

app = Flask(__name__)
app.secret_key = "your_secret_key"

os.makedirs(EVIDENCE_DIR, exist_ok=True)

# ---------------------- Database Connection ----------------------
DB_HOST = "localhost"
DB_USER = "root"
DB_PASSWORD = ""
DB_NAME = "helmet_detection"

engine = create_engine(
    f"mysql+mysqlconnector://{DB_USER}:{DB_PASSWORD}@{DB_HOST}/{DB_NAME}",
    pool_pre_ping=True
)

# ---------------------- Load Models ------------------------
helmet_model_path = "models/hemletYoloV8_25epochs.pt"
plate_model_path = "models/best.pt"

print("📦 Loading YOLO helmet model...")
helmet_model = YOLO(helmet_model_path)
print(f"Helmet model loaded: {helmet_model.names}")

print("📦 Loading YOLO plate model...")
plate_model = YOLO(plate_model_path)
print(f"Plate model loaded: {plate_model.names}")

print("📖 Loading EasyOCR...")
ocr_reader = easyocr.Reader(["en"], gpu=False)
print("EasyOCR loaded.")

# ---------------------- Duplicate Handling -------------
recent_violations = {}
VIOLATION_TIMEOUT = 12

# ---------------------- Utility Functions -----------------
def generate_temp_plate():
    letters = ''.join(random.choices(string.ascii_uppercase, k=3))
    numbers = ''.join(random.choices(string.digits, k=4))
    return f"TEMP{letters}{numbers}"

def sanitize_plate(text):
    if not text:
        return None
    text = text.upper().replace(" ", "")
    cleaned = "".join(ch for ch in text if ch.isalnum())
    return cleaned if len(cleaned) >= 4 else None

def preprocess_plate(plate):
    try:
        gray = cv2.cvtColor(plate, cv2.COLOR_BGR2GRAY)
        gray = cv2.resize(gray, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
        gray = cv2.bilateralFilter(gray, 15, 75, 75)
        thresh = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                       cv2.THRESH_BINARY_INV, 31, 5)
        return thresh
    except:
        return plate

# ---------------------- Live Frame Generator -----------------
def gen_frames():
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("❌ CAMERA NOT AVAILABLE")
        return

    while True:
        ret, frame = cap.read()
        if not ret:
            continue

        helmet_results = helmet_model(frame)
        plate_results = plate_model(frame)

        no_helmet_detected = False
        plate_boxes = []

        # Helmet detection
        for r in helmet_results:
            for box in r.boxes:
                cls = int(box.cls[0])
                name = helmet_model.names[cls].lower()
                conf = float(box.conf[0])
                x1, y1, x2, y2 = map(int, box.xyxy[0])

                if name == "head":
                    no_helmet_detected = True
                    color = (0, 0, 255)
                    label = f"NO HELMET {conf:.2f}"
                else:
                    color = (0, 255, 0)
                    label = f"HELMET {conf:.2f}"

                cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                cv2.putText(frame, label, (x1, y1 - 10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

        # Plate detection
        for r in plate_results:
            for box in r.boxes:
                cls = int(box.cls[0])
                name = plate_model.names[cls].lower()
                if name != "licence":
                    continue

                x1, y1, x2, y2 = map(int, box.xyxy[0])
                x1 = max(0, x1 - 40)
                y1 = max(0, y1 - 20)
                x2 = min(frame.shape[1], x2 + 40)
                y2 = min(frame.shape[0], y2 + 20)

                plate_boxes.append((x1, y1, x2, y2))
                cv2.rectangle(frame, (x1, y1), (x2, y2), (255, 0, 0), 2)
                cv2.putText(frame, "PLATE", (x1, y1 - 10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 0, 0), 2)

        # Record violation
        if no_helmet_detected:
            for (x1, y1, x2, y2) in plate_boxes if plate_boxes else [(0, 0, 0, 0)]:
                plate_crop = frame if (x1 == 0 and x2 == 0) else frame[y1:y2, x1:x2]
                processed = preprocess_plate(plate_crop)
                ocr = ocr_reader.readtext(processed, detail=0)
                plate_text = sanitize_plate(ocr[0]) if ocr else None

                if not plate_text:
                    plate_text = generate_temp_plate()

                now = time.time()
                if plate_text in recent_violations and now - recent_violations[plate_text] < VIOLATION_TIMEOUT:
                    continue

                recent_violations[plate_text] = now

                timestamp = time.strftime("%Y%m%d_%H%M%S")
                img_name = f"{plate_text}_{timestamp}.jpg"
                img_path = os.path.join(EVIDENCE_DIR, img_name)
                cv2.imwrite(img_path, frame)

                log_violation_to_db(plate_text, img_name, 0.90)
                print(f"🚨 Violation logged for {plate_text}")

        ret, buffer = cv2.imencode('.jpg', frame)
        yield b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n'


@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        user = request.form['username']
        pwd = request.form['password']

        if user == "admin" and pwd == "admin123":
            session['user_type'] = "admin"
            return redirect(url_for('admin_dashboard'))
        elif user == "public" and pwd == "public123":
            session['user_type'] = "public"
            return redirect(url_for('public_dashboard'))
        else:
            error = "Invalid username or password"
    return render_template("login.html", error=error)

@app.route('/admin_dashboard')
def admin_dashboard():
    if session.get('user_type') != 'admin':
        return redirect(url_for('login'))
    with engine.connect() as conn:
        total_violations = conn.execute(text("SELECT COUNT(*) FROM violations")).scalar()
        total_vehicles = conn.execute(text("SELECT COUNT(*) FROM vehicles")).scalar()
    return render_template("admin_dashboard.html",
                           total_violations=total_violations,
                           total_vehicles=total_vehicles)

@app.route('/public_dashboard')
def public_dashboard():
    if session.get('user_type') != 'public':
        return redirect(url_for('login'))
    with engine.connect() as conn:
        total_violations = conn.execute(text("SELECT COUNT(*) FROM violations")).scalar()
        total_vehicles = conn.execute(text("SELECT COUNT(*) FROM vehicles")).scalar()
    return render_template("public_dashboard.html",
                           total_violations=total_violations,
                           total_vehicles=total_vehicles)

@app.route('/violations')
def violations():
    with engine.connect() as conn:
        result = conn.execute(text("SELECT license_plate_text AS plate, violation_timestamp AS time, details AS type, image_path AS image FROM violations ORDER BY violation_timestamp DESC"))
        data = result.fetchall()
    return render_template("violations.html", violations=data)

@app.route('/vehicles')
def vehicles():
    with engine.connect() as conn:
        result = conn.execute(text("SELECT owner_name, vehicle_number, vehicle_type FROM vehicles ORDER BY owner_name"))
        data = result.fetchall()
    return render_template("vehicles.html", vehicles=data)

@app.route('/video_feed')
def video_feed():
    if session.get('user_type') != 'admin':
        return "⛔ Access Denied", 403
    return Response(gen_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# ---------------------- App Startup ----------------------
if __name__ == "__main__":
    print("🚀 Starting Smart Traffic Detection at http://127.0.0.1:5000/login")
    app.run(host="127.0.0.1", port=5000, debug=True)
