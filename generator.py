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

CLICK_HOST = 'https://clickpy-clickhouse.clickhouse.com/?user=play'
CLICK_PARAMS = {'user': 'play'}
CLICK_QUERY = 'SELECT project FROM pypi.pypi_downloads GROUP BY project ORDER BY sum(count) DESC LIMIT %s FORMAT JSONCompactColumns'

BROKEN_MODULES = {
    'apache-beam': 'https://github.com/astral-sh/uv/issues/3078',
    'awscli': 'The pip is having problems with awscli, see '
              'https://github.com/alphavector/all/actions/runs/11203830224/job/31141517215',
    'awscli-cwlogs': 'The pip is having problems with awscli, see '
              'https://github.com/alphavector/all/actions/runs/11203830224/job/31141517215',
    'thrift': 'The uv has problems with thrift at a certain dependency order '
              '(https://github.com/alphavector/all/actions/runs/11204390601/job/31142712430)'
              ', but the 1 time pass executed successfully '
              'https://github.com/alphavector/all/actions/runs/11203830224/job/31141517284#step:5:569',
    'pycrypto': 'pip: src/_fastmath.c:33:10: fatal error: longintrepr.h: No such file or directory',
    'backports-zoneinfo': 'pip: lib/zoneinfo_module.c:600:19: error: ‘_PyLong_One’ undeclared (first use in this function); did you mean ‘_PyLong_New’?',
    'sklearn': "The 'sklearn' PyPI package is deprecated, use 'scikit-learn' rather than 'sklearn' for pip commands.",
    'pathtools': "ModuleNotFoundError: No module named 'imp'",
    'functools32': 'This backport is for Python 2.7 only.',
    'tfx-bsl': 'Ignored the following versions that require a different python version: ... Requires-Python',
    'tensorflow-data-validation': 'Ignored the following versions that require a different python version: ... Requires-Python',
    'pywin32': 'ignore windows modules',
    'tensorflow-text': 'No matching distribution found for tensorflow-text<=2.17.0',
    'tensorflow-addons': '',
    'tensorflow-metadata': '',
    'tensorflow-transform': '',
    'tensorflow-hub': '',
    'tensorflow-serving-api': '',
    'tensorflow-estimator': '',
    'tensorflow-io-gcs-filesystem': '',
    'tensorflow-model-analysis': '',
    'flask-appbuilder': 'flask-appbuilder==2.1.4 has a bug',
    'bokeh': "AttributeError: module 'configparser' has no attribute 'SafeConfigParser'. Did you mean: 'RawConfigParser'?, "
             "uv did it, but the others didn't, very strange.",

    # Azure
    'azure-cli': 'jsmin==2.2.2: error in jsmin setup command: use_2to3 is invalid.',
    'azure-mgmt-core': '',
    'azure-mgmt-keyvault': '',
    'azure-mgmt-storage': '',
    'azureml-core': '',
    'azure-mgmt-sql': '',
    'azure-mgmt-web': '',
    'azure-mgmt-cognitiveservices': '',
    'azure-mgmt-rdbms': '',
    'azure-mgmt-containerregistry': '',
    'azure-mgmt-datalake-store': '',
    'azure-mgmt-batchai': '',
    'azure-appconfiguration': '',
    'azure-mgmt-media': '',
    'azure-cli-telemetry': '',
    'azure-mgmt-iothub': '',
    'azure-cli-core': '',
    'azure-mgmt-recoveryservices': '',
    'azure-keyvault-keys': '',
    'azure-mgmt-datamigration': '',
    'azure-mgmt-signalr': '',
    'azure-mgmt-cosmosdb': '',
    'azure-mgmt-loganalytics': '',
    'azure-mgmt-batch': '',
    'azure-mgmt-nspkg': '',
    'azure-mgmt-eventgrid': '',
    'azure-mgmt-hdinsight': '',
    'azure-kusto-data': '',
    'azure-eventgrid': '',
    'azure-keyvault': '',
    'azure-mgmt-datafactory': '',
    'azure-mgmt-devtestlabs': '',
    'azure-mgmt-redis': '',
    'azure-mgmt-managementgroups': '',
    'azure-mgmt-maps': '',
    'azure-mgmt-containerservice': '',
    'azure-devops': '',
    'azure-mgmt-dns': '',
    'azure-mgmt-network': '',
    'azure-eventhub': '',
    'azure-cosmosdb-nspkg': '',
    'azure-mgmt-policyinsights': '',
    'azure-mgmt-eventhub': '',
    'azure-mgmt-recoveryservicesbackup': '',
    'azureml-dataprep': '',
    'azure-storage-blob': '',
    'azure-mgmt-iotcentral': '',
    'azure-mgmt-containerinstance': '',
    'azure-storage-queue': '',
    'azure-mgmt-monitor': '',
    'azure-mgmt-compute': '',
    'azure-mgmt-iothubprovisioningservices': '',
    'azure-storage-file-share': '',
    'azure-mgmt-authorization': '',
    'opencensus-ext-azure': '',
    'azure-mgmt-datalake-nspkg': '',
    'azure-core': '',
    'azure-mgmt-marketplaceordering': '',
    'azure-servicebus': '',
    'azure-mgmt-applicationinsights': '',
    'azure-multiapi-storage': '',
    'azure-cosmos': '',
    'azure-mgmt-servicefabric': '',
    'azure-storage-file-datalake': '',
    'azure-storage-common': '',
    'azure-datalake-store': '',
    'azure-mgmt-consumption': '',
    'azure-mgmt-cdn': '',
    'azure-cosmosdb-table': '',
    'azure-mgmt-advisor': '',
    'azure-mgmt-search': '',
    'azure-batch': '',
    'azure-synapse-artifacts': '',
    'azure-mgmt-msi': '',
    'azure-mgmt-billing': '',
    'azure-mgmt-resource': '',
    'azure-graphrbac': '',
    'azure-loganalytics': '',
    'azure-keyvault-secrets': '',
    'azure-nspkg': '',
    'azure-storage-file': '',
    'azure-mgmt-trafficmanager': '',
    'azure-mgmt-reservations': '',
    'azure-mgmt-servicebus': '',
    'azure-mgmt-relay': '',
    'azure-mgmt-datalake-analytics': '',
    'azure-kusto-ingest': '',
    'azure-data-tables': '',
    'azure-keyvault-certificates': '',
    'azure-identity': '',
    'azure-common': '',

}


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


async def consumer(q: asyncio.Queue, requirement: str):
    with open(requirement, 'w') as fd:
        while True:
            msg = await q.get()

            name, latest_version = msg

            if (reasone := BROKEN_MODULES.get(name)) is not None:
                fd.write(f'# {name}<={latest_version} # {reasone}\n')
            else:
                fd.write(f'{name}<={latest_version}\n')
            q.task_done()


async def generator(workers: int, requirement: str, limit: int = 100):
    log.info('Download top %s modules', limit)
    actual_limit = limit + len(BROKEN_MODULES)
    async with aiohttp.ClientSession() as session:
        async with session.get(CLICK_HOST, params=CLICK_PARAMS, data=CLICK_QUERY % (actual_limit,)) as resp:
            assert resp.status == 200
            data: dict = await resp.json(content_type='text/plain')

    packages = data[0]
    total = len(packages)
    log.info('total: %s', total)

    batches: tuple[tuple[str]] = tuple(tuple(x) for x in divide(workers, packages))
    q = asyncio.Queue()

    pbars = [tqdm(total=len(batch), position=i, desc=f'worker {i}', unit='pkgs') for i, batch in
             enumerate(batches)]

    asyncio.create_task(consumer(q, requirement=requirement))  # noqa

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
    parser.add_argument('-r', '--requirement', type=str, default='requirements.txt')
    parser.add_argument('-l', '--limit', type=int, default=100)
    args = vars(parser.parse_args())

    asyncio.run(generator(**args))
