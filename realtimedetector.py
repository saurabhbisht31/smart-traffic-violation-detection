# Description: Real-time helmet detection using YOLOv8 and EasyOCR
import cv2
from ultralytics import YOLO
import easyocr
import time
import os

from db_connector import log_violation
from config import EVIDENCE_DIR

# Cooldown to avoid spamming database with same violation
COOLDOWN_PERIOD = 60  # seconds
violation_cooldowns = {}  # Key: license_plate, Value: last logged timestamp
last_unreadable_log_time = 0

# ---------------------- LOAD MODELS -------------------
print("Loading YOLOv8 helmet model...")
helmet_model = YOLO("models/hemletYoloV8_25epochs.pt")  # Use your YOLOv8-trained model
print("Helmet model loaded.")

print("Loading EasyOCR...")
ocr_reader = easyocr.Reader(['en'], gpu=False)
print("EasyOCR loaded.")

def process_frame(frame):
    global last_unreadable_log_time

    results = helmet_model(frame)  # detect helmets (YOLOv8)

    # Iterate through detections
    for r in results:
        boxes = r.boxes
        for box in boxes:
            x1, y1, x2, y2 = map(int, box.xyxy[0])
            conf = float(box.conf[0])
            cls = int(box.cls[0])
            class_name = helmet_model.names[cls]

            # Draw bounding box
            color = (0, 255, 0) if class_name.lower() == "helmet" else (0, 0, 255)
            label = class_name.upper()
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
            cv2.putText(frame, f"{label} {conf:.2f}", (x1, y1 - 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)

            # If violation (NO HELMET)
            if class_name.lower() != "helmet" and conf > 0.5:
                roi = frame[y1:y2, x1:x2]
                current_time = time.time()

                # OCR to read license plate
                # NOTE: here ROI may not be the plate region depending on your detection flow.
                # If you have a separate plate detector, use that crop instead.
                ocr_results = ocr_reader.readtext(roi, detail=1, paragraph=False)
                if ocr_results:
                    license_plate = ocr_results[0][1].strip().replace(" ", "")
                    if license_plate in violation_cooldowns and current_time - violation_cooldowns[license_plate] < COOLDOWN_PERIOD:
                        continue
                    violation_cooldowns[license_plate] = current_time
                else:
                    # Unreadable plate cooldown
                    if current_time - last_unreadable_log_time < COOLDOWN_PERIOD:
                        continue
                    last_unreadable_log_time = current_time
                    license_plate = f"UNREADABLE_{int(current_time)}"

                # Save evidence
                timestamp = time.strftime("%Y%m%d_%H%M%S")
                image_filename = f"{license_plate}_{timestamp}.jpg"
                os.makedirs(EVIDENCE_DIR, exist_ok=True)
                image_path = os.path.join(EVIDENCE_DIR, image_filename)
                cv2.imwrite(image_path, frame)

                print(f"[VIOLATION] NO HELMET detected: {license_plate}")
                print(f"Saved evidence: {image_path}")

                # Log into DB via db_connector
                log_violation(
                    license_plate=license_plate,
                    camera_id=1,
                    violation_type_name="No Helmet",
                    image_path=image_path,
                    details=f"Detection confidence: {conf:.2f}"
                )

    return frame

# ---------------------- MAIN LOOP --------------------
def main():
    cap = cv2.VideoCapture(0)  # default webcam
    if not cap.isOpened():
        print("Error: Cannot open camera")
        return

    print("Starting Real-Time Helmet Detection. Press 'q' to quit.")

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        frame = process_frame(frame)
        cv2.imshow("Helmet Detection", frame)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()
    print("Detection stopped.")

if __name__ == "__main__":
    main()
