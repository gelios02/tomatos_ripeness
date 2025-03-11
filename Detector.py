import cv2
import numpy as np
import math
from ultralytics import YOLO
from app import db, TomatoRecognition
# Инициализируем каскад для обнаружения лиц
face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')

# Глобальная модель YOLO (файл best.pt должен находиться в той же директории)
detection_model = YOLO("best.pt")


def compute_iou(boxA, boxB):
    """
    Вычисляет Intersection over Union (IoU) для двух bounding box.
    Каждый box представлен списком [x1, y1, x2, y2].
    """
    xA = max(boxA[0], boxB[0])
    yA = max(boxA[1], boxB[1])
    xB = min(boxA[2], boxB[2])
    yB = min(boxA[3], boxB[3])
    interWidth = max(0, xB - xA + 1)
    interHeight = max(0, yB - yA + 1)
    interArea = interWidth * interHeight
    boxAArea = (boxA[2] - boxA[0] + 1) * (boxA[3] - boxA[1] + 1)
    boxBArea = (boxB[2] - boxB[0] + 1) * (boxB[3] - boxB[1] + 1)
    iou = interArea / float(boxAArea + boxBArea - interArea)
    return iou


def gen_frames(user_settings, user_id, camera_id=0):
    """
    Генерирует поток JPEG‑изображений с камеры, проводя детекцию томатов.
    Фильтрует объекты, пересекающиеся с лицами (IoU > 0.3).

    Параметры:
      user_settings – объект настроек пользователя (содержит conf_threshold, desired_ripeness, max_harvest_time)
      user_id – id пользователя (для сохранения результатов в БД)
      camera_id – id камеры (по умолчанию 0)

    Результаты распознавания сохраняются в БД (таблица TomatoRecognition).
    Функция возвращает поток изображений в формате multipart/x-mixed-replace.
    """
    conf_threshold = user_settings.conf_threshold
    desired_ripeness = user_settings.desired_ripeness
    max_harvest_time = user_settings.max_harvest_time

    cap = cv2.VideoCapture(camera_id)  # Используем указанный источник камеры
    tracked_tomatoes = {}
    next_tomato_id = 1
    frame_count = 0
    tracking_distance_threshold = 120  # Порог трекинга по центру bbox (в пикселях)
    deletion_threshold = 50  # Если объект не обновлялся более 50 кадров, удаляем его из трекера

    def distance(p1, p2):
        return math.sqrt((p1[0] - p2[0]) ** 2 + (p1[1] - p2[1]) ** 2)

    while True:
        success, frame = cap.read()
        if not success:
            break
        frame_count += 1
        h, w, _ = frame.shape

        # Детектируем лица на кадре для фильтрации ложных детекций
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5)
        face_boxes = []
        for (fx, fy, fw, fh) in faces:
            face_boxes.append([fx, fy, fx + fw, fy + fh])

        results = detection_model.predict(frame, verbose=False)
        for result in results:
            boxes = result.boxes
            for box in boxes:
                conf = float(box.conf)
                if conf < conf_threshold:
                    continue
                x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
                x1, y1 = max(0, x1), max(0, y1)
                x2, y2 = min(w - 1, x2), min(h - 1, y2)

                # Проверка: если bbox от YOLO пересекается с лицом, пропускаем объект
                yolo_box = [x1, y1, x2, y2]
                skip = False
                for face_box in face_boxes:
                    if compute_iou(yolo_box, face_box) > 0.3:
                        skip = True
                        break
                if skip:
                    continue

                width = x2 - x1
                height = y2 - y1
                if height == 0:
                    continue
                aspect_ratio = width / height
                if aspect_ratio < 0.7 or aspect_ratio > 1.3:
                    continue

                tomato_roi = frame[y1:y2, x1:x2]
                if tomato_roi.size == 0:
                    continue

                hsv_roi = cv2.cvtColor(tomato_roi, cv2.COLOR_BGR2HSV)
                lab_roi = cv2.cvtColor(tomato_roi, cv2.COLOR_BGR2LAB)

                mean_h = hsv_roi[:, :, 0].mean()
                mean_s = hsv_roi[:, :, 1].mean()
                mean_v = hsv_roi[:, :, 2].mean()
                mean_L = lab_roi[:, :, 0].mean()
                mean_a = lab_roi[:, :, 1].mean()
                mean_b = lab_roi[:, :, 2].mean()

                hsv_hue = hsv_roi[:, :, 0]
                total_pixels = hsv_hue.size
                red_pixels = np.count_nonzero((hsv_hue < 10) | (hsv_hue > 170))
                yellow_pixels = np.count_nonzero((hsv_hue >= 15) & (hsv_hue <= 35))
                green_pixels = np.count_nonzero((hsv_hue > 40) & (hsv_hue < 80))

                red_ratio = red_pixels / total_pixels
                yellow_ratio = yellow_pixels / total_pixels
                green_ratio = green_pixels / total_pixels

                if red_ratio > 0.5:
                    classification = "Ripe"
                    ripeness_percentage = red_ratio * 100
                elif yellow_ratio > 0.5:
                    classification = "Yellow"
                    ripeness_percentage = yellow_ratio * 100
                elif green_ratio > 0.5:
                    classification = "Unripe"
                    ripeness_percentage = 0
                else:
                    classification = "Partially Ripe"
                    ripeness_percentage = (red_ratio + yellow_ratio) / 2 * 100

                if classification in ["Unripe", "Partially Ripe"]:
                    time_to_harvest = round(max_harvest_time * (1 - ripeness_percentage / 100), 1)
                else:
                    time_to_harvest = 0

                center = ((x1 + x2) / 2, (y1 + y2) / 2)
                assigned_id = None
                for tid, (prev_center, last_seen) in tracked_tomatoes.items():
                    if distance(center, prev_center) < tracking_distance_threshold:
                        assigned_id = tid
                        tracked_tomatoes[tid] = (center, frame_count)
                        break
                if assigned_id is None:
                    assigned_id = next_tomato_id
                    tracked_tomatoes[assigned_id] = (center, frame_count)
                    next_tomato_id += 1

                is_ripe = "Yes" if classification in ["Ripe", "Yellow"] else "No"
                collected = ""

                # Сохраняем результат в БД в контексте приложения
                with app.app_context():
                    rec = TomatoRecognition(
                        tomato_id=assigned_id,
                        mean_h=mean_h,
                        mean_s=mean_s,
                        mean_v=mean_v,
                        mean_L=mean_L,
                        mean_a=mean_a,
                        mean_b=mean_b,
                        ripeness_percentage=ripeness_percentage,
                        classification=classification,
                        is_ripe=is_ripe,
                        time_to_harvest=time_to_harvest,
                        collected=collected,
                        user_id=user_id,
                        camera_id=camera_id
                    )
                    db.session.add(rec)
                    db.session.commit()

                box_color = (0, 0, 255) if classification == "Ripe" else (
                0, 255, 255) if classification == "Yellow" else (0, 255, 0)
                label = f"ID:{assigned_id} {classification} {ripeness_percentage:.1f}%"
                if time_to_harvest > 0:
                    label += f", {time_to_harvest}d"
                cv2.rectangle(frame, (x1, y1), (x2, y2), box_color, 2)
                cv2.putText(frame, label, (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, box_color, 2)

        ret2, buffer = cv2.imencode('.jpg', frame)
        frame_bytes = buffer.tobytes()
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')

    cap.release()
