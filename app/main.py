from fastapi import FastAPI

app = FastAPI(title="ПУЛЬС", docs_url=None, redoc_url=None)


@app.get("/health")
def health() -> dict[str, str]:
    """Возвращает состояние приложения для проверки готовности."""
    return {"status": "ok"}
