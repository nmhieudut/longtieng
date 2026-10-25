import uvicorn

from .config import ALLOW_LAN, PORT

if __name__ == "__main__":
    host = "0.0.0.0" if ALLOW_LAN else "127.0.0.1"
    print(f"Longtieng: http://127.0.0.1:{PORT}")
    # one worker, no reload: background jobs live in this process
    uvicorn.run("app.main:app", host=host, port=PORT, workers=1)
