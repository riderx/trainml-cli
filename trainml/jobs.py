import json
import asyncio
import math
import logging
import warnings
from datetime import datetime

from trainml.exceptions import (
    ApiError,
    JobError,
    SpecificationError,
    TrainMLException,
)
from trainml.connections import Connection


def _clean_datasets_selection(
    requested_datasets, provider, my_datasets, public_datasets
):
    datasets = []
    for dataset in requested_datasets:
        if "id" in dataset.keys():
            datasets.append(
                dict(
                    dataset_uuid=dataset.get("id"),
                    type=dataset.get("type"),
                )
            )
        elif "dataset_uuid" in dataset.keys():
            datasets.append(dataset)
        elif "name" in dataset.keys():
            if dataset.get("type") == "existing":
                selected_dataset = next(
                    (
                        d
                        for d in my_datasets
                        if d.name == dataset.get("name")
                        and d.provider == provider
                    ),
                    None,
                )
                if not selected_dataset:
                    raise SpecificationError(
                        "datasets", f"Dataset {dataset} Not Found"
                    )
                datasets.append(
                    dict(
                        dataset_uuid=selected_dataset.id,
                        type=dataset.get("type"),
                    )
                )
            elif dataset.get("type") == "public":
                selected_dataset = next(
                    (
                        d
                        for d in public_datasets
                        if d.name == dataset.get("name")
                        and d.provider == provider
                    ),
                    None,
                )
                if not selected_dataset:
                    raise SpecificationError(
                        "datasets", f"Dataset {dataset} Not Found"
                    )
                datasets.append(
                    dict(
                        dataset_uuid=selected_dataset.id,
                        type=dataset.get("type"),
                    )
                )
            else:
                raise SpecificationError(
                    "datasets",
                    "Invalid dataset specification, 'type' must be in ['existing','public']",
                )
        else:
            raise SpecificationError(
                "datasets",
                "Invalid dataset specification, either 'id' or 'name' must be provided",
            )
    return datasets


class Jobs(object):
    def __init__(self, trainml):
        self.trainml = trainml

    async def get(self, id):
        resp = await self.trainml._query(f"/job/{id}", "GET")
        return Job(self.trainml, **resp)

    async def list(self):
        resp = await self.trainml._query(f"/job", "GET")
        jobs = [Job(self.trainml, **job) for job in resp]
        return jobs

    async def create(
        self,
        name,
        type,
        gpu_type,
        gpu_count,
        disk_size,
        worker_count=1,
        worker_commands=[],
        environment=dict(type="DEEPLEARNING_PY38"),
        data=dict(datasets=[]),
        model=dict(),
        vpn=dict(net_prefix_type_id=1),
        **kwargs,
    ):

        if type in ["headless", "interactive"]:
            new_type = "notebook" if type == "interactive" else "training"
            warnings.warn(
                f"'{type}' type is deprecated, use '{new_type}' instead.",
                DeprecationWarning,
            )
        gpu_type_task = asyncio.create_task(self.trainml.gpu_types.list())
        my_datasets_task = asyncio.create_task(self.trainml.datasets.list())
        public_datasets_task = asyncio.create_task(
            self.trainml.datasets.list_public()
        )

        gpu_types, my_datasets, public_datasets = await asyncio.gather(
            gpu_type_task, my_datasets_task, public_datasets_task
        )

        selected_gpu_type = next(
            (g for g in gpu_types if g.name == gpu_type or g.id == gpu_type),
            None,
        )
        if not selected_gpu_type:
            raise SpecificationError("gpu_type", "GPU Type Not Found")

        if data:
            datasets = _clean_datasets_selection(
                data.get("datasets"),
                selected_gpu_type.provider,
                my_datasets,
                public_datasets,
            )
            data["datasets"] = datasets

        config = dict(
            name=name,
            type=type,
            resources=dict(
                gpu_type_id=selected_gpu_type.id,
                gpu_count=gpu_count,
                disk_size=disk_size,
            ),
            worker_count=worker_count,
            worker_commands=worker_commands,
            environment=environment,
            data=data,
            model=model,
            vpn=vpn,
            source_job_uuid=kwargs.get("source_job_uuid"),
        )
        payload = {
            k: v
            for k, v in config.items()
            if v
            or (
                k in ["worker_commands", "model"]
                and not kwargs.get("source_job_uuid")
            )
        }
        logging.info(f"Creating Job {name}")
        logging.debug(f"Job payload: {payload}")
        resp = await self.trainml._query("/job", "POST", None, payload)
        job = Job(self.trainml, **resp)
        logging.info(f"Created Job {name} with id {job.id}")
        return job

    async def remove(self, id):
        await self.trainml._query(f"/job/{id}", "DELETE", dict(force=True))


class Job:
    def __init__(self, trainml, **kwargs):
        self.trainml = trainml
        self._job = kwargs
        self._id = self._job.get("id", self._job.get("job_uuid"))
        self._name = self._job.get("name")
        self._provider = self._job.get("provider")
        self._status = self._job.get("status")
        self._type = self._job.get("type")
        self._workers = self._job.get("workers")

    @property
    def id(self) -> str:
        return self._id

    @property
    def name(self) -> str:
        return self._name

    @property
    def status(self) -> str:
        return self._status

    @property
    def provider(self) -> str:
        return self._provider

    @property
    def type(self) -> str:
        return self._type

    def __str__(self):
        return json.dumps({k: v for k, v in self._job.items()})

    def __repr__(self):
        return f"Job( trainml , {self._job.__repr__()})"

    def __bool__(self):
        return bool(self._id)

    async def start(self):
        await self.trainml._query(
            f"/job/{self._id}", "PATCH", None, dict(command="start")
        )

    async def stop(self):
        await self.trainml._query(
            f"/job/{self._id}", "PATCH", None, dict(command="stop")
        )

    async def get_connection_utility_url(self):
        resp = await self.trainml._query(f"/job/{self._id}/download", "GET")
        return resp

    def get_connection_details(self):

        details = dict(
            cidr=self._job.get("vpn").get("cidr"),
            ssh_port=self._job.get("vpn").get("client").get("ssh_port")
            if self._job.get("vpn").get("client")
            else None,
            input_path=None,
            output_path=self._job.get("data").get("output_uri")
            if self._job.get("data").get("output_type") == "local"
            else None,
        )
        return details

    async def connect(self):
        connection = Connection(
            self.trainml, entity_type="job", id=self.id, entity=self
        )
        await connection.start()
        return connection.status

    async def disconnect(self):
        connection = Connection(
            self.trainml, entity_type="job", id=self.id, entity=self
        )
        await connection.stop()
        return connection.status

    async def remove(self):
        await self.trainml._query(f"/job/{self._id}", "DELETE")

    async def refresh(self):
        resp = await self.trainml._query(f"/job/{self.id}", "GET")
        self.__init__(self.trainml, **resp)
        return self

    def _get_msg_handler(self, msg_handler):
        worker_numbers = {
            w.get("job_worker_uuid"): ind + 1
            for ind, w in enumerate(self._workers)
        }

        def handler(msg):
            data = json.loads(msg.data)
            if data.get("type") == "subscription":
                data["worker_number"] = worker_numbers.get(data.get("stream"))
                if msg_handler:
                    msg_handler(data)
                else:
                    timestamp = datetime.fromtimestamp(
                        int(data.get("time")) / 1000
                    )
                    if len(self._workers) > 1:
                        print(
                            f"{timestamp.strftime('%m/%d/%Y, %H:%M:%S')}: Worker {data.get('worker_number')} - {data.get('msg').rstrip()}"
                        )
                    else:
                        print(
                            f"{timestamp.strftime('%m/%d/%Y, %H:%M:%S')}: {data.get('msg').rstrip()}"
                        )

        return handler

    async def attach(self, msg_handler=None):
        await self.trainml._ws_subscribe(
            "job", self.id, self._get_msg_handler(msg_handler)
        )

    async def copy(self, name, **kwargs):
        logging.debug(f"copy request - name: {name} ; kwargs: {kwargs}")
        if self.type not in ["interactive", "notebook"]:
            raise SpecificationError(
                "job", "Only notebook job types can be copied"
            )

        job = await self.trainml.jobs.create(
            name,
            type=kwargs.get("type") or self.type,
            gpu_type=kwargs.get("gpu_type")
            or self._job.get("resources").get("gpu_type_id"),
            gpu_count=kwargs.get("gpu_count")
            or self._job.get("resources").get("gpu_count"),
            disk_size=kwargs.get("disk_size")
            or self._job.get("resources").get("disk_size"),
            worker_count=kwargs.get("worker_count"),
            worker_commands=kwargs.get("worker_commands"),
            environment=kwargs.get("environment"),
            data=kwargs.get("data"),
            vpn=kwargs.get("vpn"),
            source_job_uuid=self.id,
        )
        logging.debug(f"copy result: {job}")
        return job

    async def wait_for(self, status, timeout=300):
        valid_statuses = ["running", "stopped", "finished", "archived"]
        if not status in valid_statuses:
            raise SpecificationError(
                "status",
                f"Invalid wait_for status {status}.  Valid statuses are: {valid_statuses}",
            )
        if (
            self.type == "headless" or self.type == "training"
        ) and status == "stopped":
            warnings.warn(
                "'stopped' status is deprecated for training jobs, use 'finished' instead.",
                DeprecationWarning,
            )
        if self.status == status or (
            (self.type == "headless" or self.type == "training")
            and status == "finished"
            and self.status == "stopped"
        ):
            return
        POLL_INTERVAL = 5
        retry_count = math.ceil(timeout / POLL_INTERVAL)
        count = 0
        while count < retry_count:
            await asyncio.sleep(POLL_INTERVAL)
            try:
                await self.refresh()
            except ApiError as e:
                if status == "archived" and e.status == 404:
                    return
                raise e
            if self.status == status or (
                (self.type == "headless" or self.type == "training")
                and status == "finished"
                and self.status == "stopped"
            ):
                return self
            elif self.status == "failed":
                raise JobError(self.status, self)
            else:
                count += 1
                logging.debug(f"self: {self}, retry count {count}")

        raise TrainMLException(f"Timeout waiting for {status}")
