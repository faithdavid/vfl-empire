import sys, os, asyncio, logging
sys.path.insert(0, '/home/ubuntu/faith-workspace/vfl-empire/services')
from ingester.server import _ingest_event_list

logging.basicConfig(level=logging.INFO)

async def test():
    print("Starting test...")
    count = await _ingest_event_list()
    print(f"Stored {count} odds entries")

if __name__ == "__main__":
    asyncio.run(test())
