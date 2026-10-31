# 공개 TC에 없는 유형을 첫 답변만 뽑아 사람이 읽어 보는 시험 (서버에서 실행)
import asyncio, json, logging, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import agent
logging.disable(logging.INFO)
cases = json.loads((Path(__file__).resolve().parent.parent / "tests" / "extra_cases.json").read_text(encoding="utf-8"))
async def one(case):
    started = time.time()
    answer = await agent.run_agent("extra:" + case["id"], case["first"])
    print(f"[{case['id']}] {time.time()-started:.1f}초 {len(answer)}자\n{answer}\n", flush=True)
async def main():
    for case in cases:
        await one(case)
asyncio.run(main())
