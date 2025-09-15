import asyncio
from typing import Annotated
from fastdi import Container, Depends, provide, ainject


async def main():
    c = Container()

    # request-scoped provider
    @provide(c, scope="request")
    async def request_id() -> object:
        await asyncio.sleep(0)
        return object()

    @ainject(c)
    async def two_reads(
        r1: Annotated[object, Depends(request_id)],
        r2: Annotated[object, Depends(request_id)],
    ) -> bool:
        return r1 is r2

    same_task_same = await two_reads()

    # Different task should have a different request-scoped value
    async def run_two_reads():
        return await two_reads()

    # Run two tasks concurrently; each should see its own value shared within task
    res1, res2 = await asyncio.gather(run_two_reads(), run_two_reads())

    print({
        "same_task_same": same_task_same,
        "task1_same": res1,
        "task2_same": res2,
    })


if __name__ == "__main__":
    asyncio.run(main())
