import re
import sys
import tempfile
import os
import asyncio
import aiohttp
from pytest import mark, fixture, raises

pytestmark = [mark.sdk, mark.integration, mark.jobs]


@fixture(scope="class")
async def job(trainml):
    job = await trainml.jobs.create(
        name="CLI Automated Job Lifecycle",
        type="notebook",
        gpu_type="GTX 1060",
        gpu_count=1,
        disk_size=1,
        data=dict(datasets=[dict(name="CIFAR-10", type="public")]),
        model=dict(
            source_type="git",
            source_uri="git@github.com:trainML/test-private.git",
        ),
    )
    yield job


@mark.create
@mark.asyncio
class JobLifeCycleTests:
    async def test_wait_for_running(self, job):
        assert job.status != "running"
        job = await job.wait_for("running", 120)
        assert job.status == "running"

    async def test_stop_job(self, job):
        assert job.status == "running"
        await job.stop()
        job = await job.wait_for("stopped", 60)
        assert job.status == "stopped"

    async def test_get_jobs(self, trainml, job):
        jobs = await trainml.jobs.list()
        assert len(jobs) > 0

    async def test_get_job(self, trainml, job):
        response = await trainml.jobs.get(job.id)
        assert response.id == job.id

    async def test_job_properties(self, job):
        assert isinstance(job.id, str)
        assert isinstance(job.name, str)
        assert isinstance(job.status, str)
        assert isinstance(job.provider, str)
        assert isinstance(job.type, str)

    def test_job_str(self, job):
        string = str(job)
        regex = r"^{.*\"job_uuid\": \"" + job.id + r"\".*}$"
        assert isinstance(string, str)
        assert re.match(regex, string)

    def test_job_repr(self, job):
        string = repr(job)
        regex = r"^Job\( trainml , {.*'job_uuid': '" + job.id + r"'.*}\)$"
        assert isinstance(string, str)
        assert re.match(regex, string)

    async def test_start_job(self, job):
        assert job.status == "stopped"
        await job.start()
        job = await job.wait_for("running", 60)
        assert job.status == "running"

    async def test_copy_job(self, job):
        job_copy = await job.copy("CLI Automated Job Copy")
        assert job_copy.id != job.id
        await job_copy.wait_for("running", 120)
        assert job_copy.status == "running"
        await job_copy.stop()
        await job_copy.wait_for("stopped", 60)
        assert job_copy.status == "stopped"
        await job_copy.remove()

    async def test_convert_job(self, job):
        training_job = await job.copy(
            "CLI Automated Job Convert",
            type="training",
            workers=[
                "PYTHONPATH=$PYTHONPATH:$TRAINML_MODEL_PATH python -m official.vision.image_classification.resnet_cifar_main --num_gpus=1 --data_dir=$TRAINML_DATA_PATH --model_dir=$TRAINML_OUTPUT_PATH --enable_checkpoint_and_export=True --train_epochs=1 --batch_size=1024"
            ],
            data=dict(
                datasets=[
                    dict(
                        name="CIFAR-10",
                        type="public",
                    )
                ],
                output_uri="s3://trainml-examples/output/resnet_cifar10",
                output_type="aws",
            ),
        )
        assert training_job.id
        training_job = await training_job.wait_for("finished", 180)
        assert training_job.status == "finished"
        assert training_job.credits > 0
        assert training_job.credits < 0.1
        await training_job.remove()

    async def test_remove_job(self, job):
        assert job.status == "running"
        await job.stop()
        await job.wait_for("stopped", 90)
        await job.remove()
        job = await job.wait_for("archived", 60)
        assert job is None


@mark.create
@mark.asyncio
class JobFeatureTests:
    async def test_job_local_output(self, trainml, capsys):
        temp_dir = tempfile.TemporaryDirectory()
        job = await trainml.jobs.create(
            "CLI Automated Tensorflow Test",
            type="training",
            gpu_type="GTX 1060",
            gpu_count=1,
            disk_size=1,
            workers=[
                "PYTHONPATH=$PYTHONPATH:$TRAINML_MODEL_PATH python -m official.vision.image_classification.resnet_cifar_main --num_gpus=1 --data_dir=$TRAINML_DATA_PATH --model_dir=$TRAINML_OUTPUT_PATH --enable_checkpoint_and_export=True --train_epochs=2 --batch_size=1024"
            ],
            environment=dict(type="TENSORFLOW_PY38_24"),
            data=dict(
                datasets=[
                    dict(
                        name="CIFAR-10",
                        type="public",
                    )
                ],
                output_uri=temp_dir.name,
                output_type="local",
            ),
            model=dict(
                source_type="git",
                source_uri="git@github.com:trainML/test-private.git",
            ),
        )
        await job.wait_for("running")
        attach_task = asyncio.create_task(job.attach())
        connect_task = asyncio.create_task(job.connect())
        await asyncio.gather(attach_task, connect_task)
        await job.refresh()
        assert job.status == "finished"
        await job.disconnect()
        await job.remove()
        upload_contents = os.listdir(temp_dir.name)
        result = any(
            "CLI_Automated_Tensorflow_Test_1" in content
            for content in upload_contents
        )
        assert result is not None
        temp_dir.cleanup()

        captured = capsys.readouterr()
        sys.stdout.write(captured.out)
        sys.stderr.write(captured.err)
        assert "Epoch 1/2" in captured.out
        assert "Epoch 2/2" in captured.out
        assert "adding: model.ckpt-0001.data-00000-of-00001" in captured.out
        assert "Send complete" in captured.out

    async def test_job_model_input_and_output(self, trainml, capsys):

        model = await trainml.models.create(
            name="CLI Automated Jobs -  Git Model",
            source_type="git",
            source_uri="git@github.com:trainML/test-private.git",
        )
        await model.wait_for("ready", 120)
        assert model.size >= 1000000

        job = await trainml.jobs.create(
            "CLI Automated Training With trainML Model Output",
            type="training",
            gpu_type="GTX 1060",
            gpu_count=1,
            disk_size=1,
            worker_commands=[
                "PYTHONPATH=$PYTHONPATH:$TRAINML_MODEL_PATH python -m official.vision.image_classification.resnet_cifar_main --num_gpus=1 --data_dir=$TRAINML_DATA_PATH --model_dir=$TRAINML_OUTPUT_PATH --enable_checkpoint_and_export=True --train_epochs=2 --batch_size=1024"
            ],
            environment=dict(type="TENSORFLOW_PY38_24"),
            data=dict(
                datasets=[
                    dict(
                        name="CIFAR-10",
                        type="public",
                    )
                ],
                output_type="trainml",
            ),
            model=dict(source_type="trainml", source_uri=model.id),
        )
        await job.attach()
        await job.refresh()
        assert job.status == "finished"
        workers = job.workers
        await job.remove()
        await model.remove()
        captured = capsys.readouterr()
        sys.stdout.write(captured.out)
        sys.stderr.write(captured.err)
        assert "Epoch 1/2" in captured.out
        assert "Epoch 2/2" in captured.out

        new_model = await trainml.models.get(
            workers[0].get("output_model_uuid")
        )
        assert new_model.id
        await new_model.wait_for("ready")
        await new_model.refresh()
        assert new_model.size > model.size + 1000000
        assert (
            new_model.name
            == "Job - CLI Automated Training With trainML Model Output"
        )
        await new_model.remove()

    async def test_endpoint(self, trainml):
        job = await trainml.jobs.create(
            "CLI Automated Endpoint",
            type="endpoint",
            gpu_type="GTX 1060",
            gpu_count=1,
            disk_size=1,
            model=dict(
                source_type="git",
                source_uri="https://github.com/trainML/simple-tensorflow-classifier.git",
            ),
            endpoint=dict(
                routes=[
                    dict(
                        path="/predict",
                        verb="POST",
                        function="predict_image",
                        file="predict",
                        positional=True,
                        body=[dict(name="filename", type="str")],
                    )
                ]
            ),
        )
        await job.wait_for("running")
        await job.refresh()
        assert job.url
        async with aiohttp.ClientSession() as session:
            retry = True
            while retry:
                async with session.request(
                    "GET",
                    f"{job.url}/ping",
                ) as resp:
                    if resp.status == 503:
                        resp.close()
                    else:
                        retry = False
                        results = await resp.json()
                        assert results["message"] == "pong"

        await job.stop()
        await job.wait_for("stopped")
        await job.refresh()
        assert not job.url
        await job.remove()

    async def test_job_custom_container(self, trainml, capsys):
        job = await trainml.jobs.create(
            name="Test Custom Container",
            type="training",
            gpu_type="GTX 1060",
            gpu_count=1,
            disk_size=10,
            model=dict(
                source_type="git",
                source_uri="git@github.com:trainML/test-private.git",
            ),
            environment=dict(
                type="CUSTOM",
                custom_image="tensorflow/tensorflow:2.4.2-gpu",
            ),
            worker_commands=[
                "PYTHONPATH=$PYTHONPATH:$TRAINML_MODEL_PATH python -m official.vision.image_classification.resnet_cifar_main --num_gpus=1 --data_dir=$TRAINML_DATA_PATH --model_dir=$TRAINML_OUTPUT_PATH --enable_checkpoint_and_export=True --train_epochs=2 --batch_size=1024",
            ],
            data=dict(
                datasets=[
                    dict(
                        name="CIFAR-10",
                        type="public",
                    )
                ],
                output_uri="s3://trainml-examples/output/resnet_cifar10",
                output_type="aws",
            ),
        )
        assert job.id
        await job.attach()
        await job.refresh()
        assert job.status == "finished"
        await job.remove()
        captured = capsys.readouterr()
        sys.stdout.write(captured.out)
        sys.stderr.write(captured.err)
        assert "Epoch 1/2" in captured.out
        assert "Epoch 2/2" in captured.out
        assert "adding: model.ckpt-0001.data-00000-of-00001" in captured.out
        assert "s3://trainml-examples/output/resnet_cifar10" in captured.out
        assert "Upload complete" in captured.out