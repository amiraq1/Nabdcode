from fastapi import FastAPI

app = FastAPI(title="Simple FastAPI Server")

@app.get("/")
async def root():
    return {"message": "Hello from NABDCODE FastAPI Server", "status": "running"}

@app.get("/health")
async def health_check():
    return {"status": "ok"}
