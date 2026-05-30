import asyncio
from app.main import lifespan
from fastapi import FastAPI

app = FastAPI()

async def test():
    async with lifespan(app):
        print("Lifespan OK")

if __name__ == "__main__":
    asyncio.run(test())
