import re
import sys
import asyncio
from pytest import mark, fixture

pytestmark = [mark.sdk, mark.integration, mark.datasets]


@mark.create
@mark.asyncio
class GetDatasetTests:
    @fixture(scope="class")
    async def dataset(self, trainml):
        dataset = await trainml.datasets.create(
            name="CLI Automated",
            source_type="aws",
            source_uri="s3://trainml-examples/data/cifar10",
        )
        dataset = await dataset.wait_for("ready", 60)
        yield dataset
        await dataset.remove()
        dataset = await dataset.wait_for("archived", 60)

    async def test_get_public_datasets(self, trainml):
        datasets = await trainml.datasets.list_public()
        assert len(datasets) > 0

    async def test_get_my_datasets(self, trainml, dataset):
        datasets = await trainml.datasets.list()
        assert len(datasets) > 0

    async def test_get_dataset(self, trainml, dataset):
        response = await trainml.datasets.get(dataset.id)
        assert response.id == dataset.id

    async def test_dataset_properties(self, dataset):
        assert isinstance(dataset.id, str)
        assert isinstance(dataset.status, str)
        assert isinstance(dataset.name, str)
        assert isinstance(dataset.provider, str)
        assert isinstance(dataset.size, int)

    def test_dataset_str(self, dataset):
        string = str(dataset)
        regex = r"^{.*\"dataset_uuid\": \"" + dataset.id + r"\".*}$"
        assert isinstance(string, str)
        assert re.match(regex, string)

    def test_dataset_repr(self, dataset):
        string = repr(dataset)
        regex = (
            r"^Dataset\( trainml , \*\*{.*'dataset_uuid': '"
            + dataset.id
            + r"'.*}\)$"
        )
        assert isinstance(string, str)
        assert re.match(regex, string)


@mark.create
@mark.asyncio
async def test_dataset_aws(trainml, capsys):
    dataset = await trainml.datasets.create(
        name="CLI Automated AWS",
        source_type="aws",
        source_uri="s3://trainml-examples/data/cifar10",
    )
    dataset = await dataset.wait_for("ready", 60)
    status = dataset.status
    size = dataset.size
    await dataset.remove()
    assert status == "ready"
    assert size >= 10000000


@mark.create
@mark.asyncio
async def test_dataset_local(trainml, capsys):
    dataset = await trainml.datasets.create(
        name="CLI Automated Local",
        source_type="local",
        source_uri="~/tensorflow-example/data",
    )
    attach_task = asyncio.create_task(dataset.attach())
    connect_task = asyncio.create_task(dataset.connect())
    await asyncio.gather(attach_task, connect_task)
    await dataset.disconnect()
    await dataset.refresh()
    status = dataset.status
    size = dataset.size
    await dataset.remove()
    assert status == "ready"
    assert size >= 10000000
    captured = capsys.readouterr()
    sys.stdout.write(captured.out)
    sys.stderr.write(captured.err)
    assert "Starting data upload from local" in captured.out
    assert "data_batch_1.bin  30733788 bytes" in captured.out
    assert "Upload complete" in captured.out