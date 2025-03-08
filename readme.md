# Tomato Ripeness Recognition System

## Описание

Tomato Ripeness Recognition System — это веб-приложение на Flask с YOLO для распознавания томатов в реальном времени. Система анализирует цветовые характеристики томата и определяет его спелость (Ripe, Yellow, Unripe). Данные сохраняются в SQLite.

## Возможности

- Автоматическое распознавание томатов через камеру
- Определение спелости на основе цветового анализа (HSV, LAB)
- Фильтрация ложных детекций (например, лица)
- Управление камерами и настройками
- Статистика с графиками и таблицами

## Установка

```bash
git clone <repository-url>
cd tomato_ripeness_project
python -m venv venv
source venv/bin/activate  # Для Windows: venv\Scripts\activate
pip install -r requirements.txt
