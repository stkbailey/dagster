from typing import Optional

from dagster import _check as check
from dagster.core.storage.base_storage import DagsterStorage
from dagster.core.storage.config import mysql_config
from dagster.core.storage.event_log import EventLogStorage
from dagster.core.storage.runs import RunStorage
from dagster.core.storage.schedules import ScheduleStorage
from dagster.serdes import ConfigurableClass, ConfigurableClassData

from .event_log import MySQLEventLogStorage
from .run_storage import MySQLRunStorage
from .schedule_storage import MySQLScheduleStorage
from .utils import mysql_url_from_config


class DagsterMySQLStorage(DagsterStorage, ConfigurableClass):
    """MySQL-backed dagster storage.

    Users should not directly instantiate this class; it is instantiated by internal machinery when
    ``dagit`` and ``dagster-graphql`` load, based on the values in the ``dagster.yaml`` file in
    ``$DAGSTER_HOME``. Configuration of this class should be done by setting values in that file.

    To use MySQL for storage, you can add a block such as the following to your
    ``dagster.yaml``:

    .. literalinclude:: ../../../../../../examples/docs_snippets/docs_snippets/deploying/dagster-mysql.yaml
       :caption: dagster.yaml
       :language: YAML

    Note that the fields in this config are :py:class:`~dagster.StringSource` and
    :py:class:`~dagster.IntSource` and can be configured from environment variables.
    """

    def __init__(self, mysql_url, inst_data=None):
        self.mysql_url = mysql_url
        self._inst_data = check.opt_inst_param(inst_data, "inst_data", ConfigurableClassData)
        self._run_storage = MySQLRunStorage(mysql_url)
        self._event_log_storage = MySQLEventLogStorage(mysql_url)
        self._schedule_storage = MySQLScheduleStorage(mysql_url)
        super().__init__()

    @property
    def inst_data(self):
        return self._inst_data

    @classmethod
    def config_type(cls):
        return mysql_config()

    @staticmethod
    def from_config_value(inst_data, config_value):
        return DagsterMySQLStorage(
            inst_data=inst_data,
            mysql_url=mysql_url_from_config(config_value),
        )

    @property
    def event_log_storage(self) -> EventLogStorage:
        return self._event_log_storage

    @property
    def run_storage(self) -> RunStorage:
        return self._run_storage

    @property
    def schedule_storage(self) -> ScheduleStorage:
        return self._schedule_storage

    @property
    def event_storage_data(self) -> Optional[ConfigurableClassData]:
        return (
            ConfigurableClassData(
                "dagster_mysql",
                "MySQLEventLogStorage",
                self.inst_data.config_yaml,
            )
            if self.inst_data
            else None
        )

    @property
    def run_storage_data(self) -> Optional[ConfigurableClassData]:
        return (
            ConfigurableClassData(
                "dagster_mysql",
                "MySQLRunStorage",
                self.inst_data.config_yaml,
            )
            if self.inst_data
            else None
        )

    @property
    def schedule_storage_data(self) -> Optional[ConfigurableClassData]:
        return (
            ConfigurableClassData(
                "dagster_mysql",
                "MySQLScheduleStorage",
                self.inst_data.config_yaml,
            )
            if self.inst_data
            else None
        )
