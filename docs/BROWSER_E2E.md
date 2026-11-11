# PULSE-012 — браузерная приёмка в Chromium

Помимо быстрых Python/pytest и Docker CI, отдельный GitHub Actions job
`Chromium / сквозной сценарий` устанавливает Chromium и запускает
локальный Uvicorn **только на runner**.

Проверяется основной пользовательский путь:
1. Вход администратора.
2. Просмотр KPI и фильтрация новичков.
3. Карточка сотрудника и работающая кнопка копирования ссылки.
4. Анкета с отрицательным ответом.
5. Создание обращения.
6. Закрытие обращения с комментарием.
7. Проверка отсутствия горизонтального overflow при 320/360/390/768/1280 px.

Для ручного запуска в отдельном окружении:

```bash
python -m pip install -e '.[dev,e2e]'
python -m playwright install chromium
export APP_ENV=test
export DATABASE_URL=sqlite:////tmp/pulse-browser-e2e.sqlite3
export ADMIN_USERNAME=admin
export ADMIN_PASSWORD=browser-test-password-only
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-proxy-headers
# В другом терминале:
python e2e/run_browser.py
```

Скрипт использует только синтетическую базу. Не запускать его на
публичном VPS: он изменяет состояние чек-инов и обращений.

Статус прохождения определяется завершением GitHub Actions, а не наличием кода.
