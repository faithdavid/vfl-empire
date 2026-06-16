import asyncio, sys, os
sys.path.insert(0, os.path.join(os.getcwd(), "services"))
sys.path.insert(0, os.path.join(os.getcwd(), "services", "predictor"))
from services.predictor.server import predict_fixtures

async def test():
    res = await predict_fixtures()
    print(f"Result: {res}")

asyncio.run(test())
