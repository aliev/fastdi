import asyncio
from typing import Annotated
from fastdi import Container, Depends, provide, ainject


async def main():
    c = Container()

    @provide(c, singleton=True)
    async def get_db():
        await asyncio.sleep(0)
        return {"db": "conn"}

    @provide(c)
    async def get_num(db=Depends(get_db)) -> int:
        await asyncio.sleep(0)
        return 41 if db else 0

    @ainject(c)
    async def handler(n: Annotated[int, Depends(get_num)]):
        return n + 1

    print(await handler())


if __name__ == "__main__":
    asyncio.run(main())
