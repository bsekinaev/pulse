"""Сквозной браузерный тест работы HR и новичка в Chromium."""

from __future__ import annotations

import os

from playwright.sync_api import sync_playwright, expect


BASE_URL = os.getenv("PULSE_E2E_BASE_URL", "http://127.0.0.1:8000")


def main() -> None:
    """Проверяет взаимодействия, которые не покрывают тесты HTTP-клиента."""
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            permissions=["clipboard-read", "clipboard-write"],
        )
        page = context.new_page()

        page.goto(BASE_URL + "/login", wait_until="networkidle")
        expect(page.get_by_role("heading", name="Контроль адаптации")).to_be_visible()
        page.get_by_label("Логин").fill("admin")
        page.get_by_label("Пароль").fill("browser-test-password-only")
        page.get_by_role("button", name="Войти в панель").click()
        page.wait_for_url("**/dashboard")

        expect(page.get_by_text("Первые дни под контролем")).to_be_visible()
        expect(page.locator(".metrics .metric")).to_have_count(4)
        page.get_by_label("Состояние").select_option("needs_help")
        page.get_by_role("button", name="Найти").click()
        expect(page.get_by_text("Показано 2 из 8")).to_be_visible()

        page.goto(BASE_URL + "/employees/1")
        expect(page.get_by_role("heading", name="Алексей М.")).to_be_visible()
        checkin_url = page.locator("#checkin-url").input_value()
        assert checkin_url.startswith(BASE_URL + "/checkin/"), checkin_url
        page.get_by_role("button", name="Скопировать ссылку").click()
        expect(page.locator("#copy-result")).to_have_text("Ссылка скопирована.")
        assert page.evaluate("navigator.clipboard.readText()") == checkin_url

        page.goto(checkin_url)
        page.locator('input[name="equipment"][value="no"]').check()
        page.locator('input[name="instructions"][value="yes"]').check()
        page.locator('input[name="support"][value="yes"]').check()
        page.locator('textarea[name="comment"]').fill(
            "Для тестирования: требуется доступ к рабочему терминалу."
        )
        page.get_by_role("button", name="Отправить ответы").click()
        expect(page.get_by_role("heading", name="Спасибо, ответ получен!")).to_be_visible()

        page.goto(BASE_URL + "/employees/1")
        expect(page.get_by_text("Анкета уже заполнена")).to_be_visible()
        page.locator(".history-item").first.click()
        expect(page.get_by_role("heading", name="Оборудование и доступы")).to_be_visible()
        page.locator('textarea[name="resolution"]').fill(
            "Для тестирования: терминал выдан и доступ подтверждён."
        )
        page.get_by_role("button", name="Зафиксировать решение").click()
        expect(page.get_by_text("Проблема закрыта", exact=True)).to_be_visible()

        page.goto(BASE_URL + "/dashboard")
        for width in (320, 360, 390, 768, 1280):
            page.set_viewport_size({"width": width, "height": 800})
            assert page.evaluate(
                "document.documentElement.scrollWidth <= window.innerWidth + 1"
            ), f"На панели горизонтальный overflow при {width}px"
            expect(page.get_by_role("heading", name="Первые дни под контролем")).to_be_visible()

        context.close()
        browser.close()
    print("PULSE_BROWSER_E2E=PASS")


if __name__ == "__main__":
    main()
