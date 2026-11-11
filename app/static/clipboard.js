// PULSE-011: копирование ссылки без inline-обработчиков и ослабления CSP.
document.addEventListener("DOMContentLoaded", () => {
  const input = document.getElementById("checkin-url");
  const button = document.getElementById("copy-checkin-link");
  const result = document.getElementById("copy-result");
  if (!input || !button || !result) return;

  button.addEventListener("click", async () => {
    if (navigator.clipboard && window.isSecureContext) {
      try {
        await navigator.clipboard.writeText(input.value);
        result.textContent = "Ссылка скопирована.";
        return;
      } catch {
        // Браузер запретил доступ к буферу: предложим ручное копирование.
      }
    }
    input.focus();
    input.select();
    result.textContent = "Ссылка выделена. Нажмите Ctrl+C для копирования.";
  });
});
