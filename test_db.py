from ultralytics import YOLO
import cv2
import tkinter as tk
from tkinter import filedialog

# Load model
model = YOLO("models/best.pt")
print(model.names)

# File picker
root = tk.Tk()
root.withdraw()
img_path = filedialog.askopenfilename(title="Choose a number plate image")

if not img_path:
    print("❌ No image selected!")
    exit()

# Load image
img = cv2.imread(img_path)
if img is None:
    print("❌ Failed to read image.")
    exit()

# Run model
results = model(img)

# Print results
for r in results:
    print(r.boxes)

# Show image with boxes
res_plotted = results[0].plot()
cv2.imshow("Plate Detection", res_plotted)
cv2.waitKey(0)
cv2.destroyAllWindows()
