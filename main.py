"""Entry point: `python main.py`."""
import os

import uvicorn

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))  # Render injects PORT
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",  # 0.0.0.0 so your iPhone can reach it over Wi-Fi
        port=port,
        reload=not os.getenv("PORT"),  # auto-reload locally, off in production
    )
