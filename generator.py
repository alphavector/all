import argparse
import asyncio
import http
import logging
from typing import Sequence

import aiohttp
from tqdm import tqdm
from more_itertools import divide

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

SERIAL_FILE = 'https://raw.githubusercontent.com/pypi-data/pypi-json-data/refs/heads/main/release_data/serials.json'
PYPI_API_BASE_URL = 'https://pypi.org'


async def get_latest_version(pbar: tqdm, q: asyncio.Queue, batch: Sequence[str]):
    async with aiohttp.ClientSession(base_url=PYPI_API_BASE_URL) as session:
        for name in batch:
            async with session.get(f'/pypi/{name}/json') as resp:
                if resp.status != http.HTTPStatus.OK:
                    pbar.update()
                    continue

                data = await resp.json()
                urls = data['urls']

                # ignore 2c.py e.g.
                if not urls:
                    pbar.update()
                    continue

                latest_version = data['info']['version']
                await q.put((name, latest_version))
                pbar.update()

    pbar.close()


async def consumer(q: asyncio.Queue, output: str):
    with open(output, 'w') as fd:
        while True:
            msg = await q.get()

            name, latest_version = msg
            fd.write(f'{name}<={latest_version}\n')
            q.task_done()


async def generator(workers, output: str):
    log.info('Download serial.json')
    async with aiohttp.ClientSession() as session:
        async with session.get(SERIAL_FILE) as resp:
            assert resp.status == 200
            data: dict = await resp.json(content_type='text/plain')

    packages = data.keys()
    total = len(packages)
    log.info('total: %s', total)

    batches: tuple[tuple[str]] = tuple(tuple(x) for x in divide(workers, packages))
    q = asyncio.Queue()

    pbars = [tqdm(total=len(batch), position=i, desc=f'worker {i}', unit='pkgs') for i, batch in
             enumerate(batches)]

    asyncio.create_task(consumer(q, output=output))  # noqa

    workers = (
        get_latest_version(
            pbar,
            q,
            batch
        ) for batch, pbar in zip(batches, pbars))

    await asyncio.gather(*workers)
    await q.join()

    log.info('Done')


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('-w', '--workers', type=int, default=100)
    parser.add_argument('-o', '--output', type=str, default='requirements.txt')
    args = vars(parser.parse_args())

    asyncio.run(generator(**args))
