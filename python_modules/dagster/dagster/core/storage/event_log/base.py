import base64
import warnings
from abc import ABC, abstractmethod
from datetime import datetime
from enum import Enum
from typing import Callable, Iterable, List, Mapping, NamedTuple, Optional, Sequence, Set, Union

import dagster._check as check
from dagster.core.assets import AssetDetails
from dagster.core.definitions.events import AssetKey
from dagster.core.events import DagsterEventType
from dagster.core.events.log import EventLogEntry
from dagster.core.execution.stats import (
    RunStepKeyStatsSnapshot,
    build_run_stats_from_events,
    build_run_step_stats_from_events,
)
from dagster.core.instance import MayHaveInstanceWeakref
from dagster.core.storage.pipeline_run import PipelineRunStatsSnapshot
from dagster.serdes import whitelist_for_serdes
from dagster.seven import json


class RunShardedEventsCursor(NamedTuple):
    """Pairs an id-based event log cursor with a timestamp-based run cursor, for improved
    performance on run-sharded event log storages (e.g. the default SqliteEventLogStorage). For
    run-sharded storages, the id field is ignored, since they may not be unique across shards
    """

    id: int
    run_updated_after: datetime


class EventLogRecord(NamedTuple):
    """Internal representation of an event record, as stored in a
    :py:class:`~dagster.core.storage.event_log.EventLogStorage`.
    """

    storage_id: int
    event_log_entry: EventLogEntry


class EventLogConnection(NamedTuple):
    records: List[EventLogRecord]
    cursor: str
    has_more: bool


class EventLogCursorType(Enum):
    OFFSET = "OFFSET"
    STORAGE_ID = "STORAGE_ID"


class EventLogCursor(NamedTuple):
    """Representation of an event record cursor, keeping track of the log query state"""

    cursor_type: EventLogCursorType
    value: int

    def is_offset_cursor(self) -> bool:
        return self.cursor_type == EventLogCursorType.OFFSET

    def is_id_cursor(self) -> bool:
        return self.cursor_type == EventLogCursorType.STORAGE_ID

    def offset(self) -> int:
        check.invariant(self.cursor_type == EventLogCursorType.OFFSET)
        return max(0, int(self.value))

    def storage_id(self) -> int:
        check.invariant(self.cursor_type == EventLogCursorType.STORAGE_ID)
        return int(self.value)

    def __str__(self):
        return self.to_string()

    def to_string(self) -> str:
        raw = json.dumps({"type": self.cursor_type.value, "value": self.value})
        return base64.b64encode(bytes(raw, encoding="utf-8")).decode("utf-8")

    @staticmethod
    def parse(cursor_str: str) -> "EventLogCursor":
        raw = json.loads(base64.b64decode(cursor_str).decode("utf-8"))
        return EventLogCursor(EventLogCursorType(raw["type"]), raw["value"])

    @staticmethod
    def from_offset(offset: int) -> "EventLogCursor":
        return EventLogCursor(EventLogCursorType.OFFSET, offset)

    @staticmethod
    def from_storage_id(storage_id: int) -> "EventLogCursor":
        return EventLogCursor(EventLogCursorType.STORAGE_ID, storage_id)


class AssetEntry(
    NamedTuple(
        "_AssetEntry",
        [
            ("asset_key", AssetKey),
            ("last_materialization", Optional[EventLogEntry]),
            ("last_run_id", Optional[str]),
            ("asset_details", Optional[AssetDetails]),
        ],
    )
):
    def __new__(
        cls,
        asset_key: AssetKey,
        last_materialization: Optional[EventLogEntry] = None,
        last_run_id: Optional[str] = None,
        asset_details: Optional[AssetDetails] = None,
    ):
        return super(AssetEntry, cls).__new__(
            cls,
            asset_key=check.inst_param(asset_key, "asset_key", AssetKey),
            last_materialization=check.opt_inst_param(
                last_materialization, "last_materialization", EventLogEntry
            ),
            last_run_id=check.opt_str_param(last_run_id, "last_run_id"),
            asset_details=check.opt_inst_param(asset_details, "asset_details", AssetDetails),
        )


class AssetRecord(NamedTuple):
    storage_id: int
    asset_entry: AssetEntry


@whitelist_for_serdes
class EventRecordsFilter(
    NamedTuple(
        "_EventRecordsFilter",
        [
            ("event_type", Optional[DagsterEventType]),
            ("asset_key", Optional[AssetKey]),
            ("asset_partitions", Optional[List[str]]),
            ("after_cursor", Optional[Union[int, RunShardedEventsCursor]]),
            ("before_cursor", Optional[Union[int, RunShardedEventsCursor]]),
            ("after_timestamp", Optional[float]),
            ("before_timestamp", Optional[float]),
        ],
    )
):
    """Defines a set of filter fields for fetching a set of event log entries or event log records.

    Args:
        event_type (Optional[DagsterEventType]): Filter argument for dagster event type
        asset_key (Optional[AssetKey]): Asset key for which to get asset materialization event
            entries / records.
        asset_partitions (Optional[List[str]]): Filter parameter such that only asset
            materialization events with a partition value matching one of the provided values.  Only
            valid when the `asset_key` parameter is provided.
        after_cursor (Optional[Union[int, RunShardedEventsCursor]]): Filter parameter such that only
            records with storage_id greater than the provided value are returned. Using a
            run-sharded events cursor will result in a significant performance gain when run against
            a SqliteEventLogStorage implementation (which is run-sharded)
        before_cursor (Optional[Union[int, RunShardedEventsCursor]]): Filter parameter such that
            records with storage_id less than the provided value are returned. Using a run-sharded
            events cursor will result in a significant performance gain when run against
            a SqliteEventLogStorage implementation (which is run-sharded)
        after_timestamp (Optional[float]): Filter parameter such that only event records for
            events with timestamp greater than the provided value are returned.
        before_timestamp (Optional[float]): Filter parameter such that only event records for
            events with timestamp less than the provided value are returned.
    """

    def __new__(
        cls,
        event_type: Optional[DagsterEventType] = None,
        asset_key: Optional[AssetKey] = None,
        asset_partitions: Optional[List[str]] = None,
        after_cursor: Optional[Union[int, RunShardedEventsCursor]] = None,
        before_cursor: Optional[Union[int, RunShardedEventsCursor]] = None,
        after_timestamp: Optional[float] = None,
        before_timestamp: Optional[float] = None,
    ):
        check.opt_list_param(asset_partitions, "asset_partitions", of_type=str)
        event_type = check.opt_inst_param(event_type, "event_type", DagsterEventType)
        if not event_type:
            warnings.warn(
                "The use of `EventRecordsFilter` without an event type is deprecated and will "
                "begin erroring starting in 0.15.0"
            )

        return super(EventRecordsFilter, cls).__new__(
            cls,
            event_type=event_type,
            asset_key=check.opt_inst_param(asset_key, "asset_key", AssetKey),
            asset_partitions=asset_partitions,
            after_cursor=check.opt_inst_param(
                after_cursor, "after_cursor", (int, RunShardedEventsCursor)
            ),
            before_cursor=check.opt_inst_param(
                before_cursor, "before_cursor", (int, RunShardedEventsCursor)
            ),
            after_timestamp=check.opt_float_param(after_timestamp, "after_timestamp"),
            before_timestamp=check.opt_float_param(before_timestamp, "before_timestamp"),
        )


class EventLogStorage(ABC, MayHaveInstanceWeakref):
    """Abstract base class for storing structured event logs from pipeline runs.

    Note that event log storages using SQL databases as backing stores should implement
    :py:class:`~dagster.core.storage.event_log.SqlEventLogStorage`.

    Users should not directly instantiate concrete subclasses of this class; they are instantiated
    by internal machinery when ``dagit`` and ``dagster-graphql`` load, based on the values in the
    ``dagster.yaml`` file in ``$DAGSTER_HOME``. Configuration of concrete subclasses of this class
    should be done by setting values in that file.
    """

    def get_logs_for_run(
        self,
        run_id: str,
        cursor: Optional[Union[str, int]] = None,
        of_type: Optional[Union[DagsterEventType, Set[DagsterEventType]]] = None,
        limit: Optional[int] = None,
    ) -> Iterable[EventLogEntry]:
        """Get all of the logs corresponding to a run.

        Args:
            run_id (str): The id of the run for which to fetch logs.
            cursor (Optional[Union[str, int]]): Cursor value to track paginated queries.  Legacy
                support for integer offset cursors.
            of_type (Optional[DagsterEventType]): the dagster event type to filter the logs.
            limit (Optional[int]): Max number of records to return.
        """
        if isinstance(cursor, int):
            cursor = EventLogCursor.from_offset(cursor + 1).to_string()
        records = self.get_records_for_run(run_id, cursor, of_type, limit).records
        return [record.event_log_entry for record in records]

    @abstractmethod
    def get_records_for_run(
        self,
        run_id: str,
        cursor: Optional[str] = None,
        of_type: Optional[Union[DagsterEventType, Set[DagsterEventType]]] = None,
        limit: Optional[int] = None,
    ) -> EventLogConnection:
        """Get all of the event log records corresponding to a run.

        Args:
            run_id (str): The id of the run for which to fetch logs.
            cursor (Optional[str]): Cursor value to track paginated queries.
            of_type (Optional[DagsterEventType]): the dagster event type to filter the logs.
            limit (Optional[int]): Max number of records to return.
        """

    def get_stats_for_run(self, run_id: str) -> PipelineRunStatsSnapshot:
        """Get a summary of events that have ocurred in a run."""
        return build_run_stats_from_events(run_id, self.get_logs_for_run(run_id))

    def get_step_stats_for_run(self, run_id: str, step_keys=None) -> List[RunStepKeyStatsSnapshot]:
        """Get per-step stats for a pipeline run."""
        logs = self.get_logs_for_run(run_id)
        if step_keys:
            logs = [
                event
                for event in logs
                if event.is_dagster_event and event.get_dagster_event().step_key in step_keys
            ]

        return build_run_step_stats_from_events(run_id, logs)

    @abstractmethod
    def store_event(self, event: EventLogEntry):
        """Store an event corresponding to a pipeline run.

        Args:
            event (EventLogEntry): The event to store.
        """

    @abstractmethod
    def delete_events(self, run_id: str):
        """Remove events for a given run id"""

    @abstractmethod
    def upgrade(self):
        """This method should perform any schema migrations necessary to bring an
        out-of-date instance of the storage up to date.
        """

    @abstractmethod
    def reindex_events(self, print_fn: Optional[Callable] = None, force: bool = False):
        """Call this method to run any data migrations across the event_log tables."""

    @abstractmethod
    def reindex_assets(self, print_fn: Optional[Callable] = None, force: bool = False):
        """Call this method to run any data migrations across the asset tables."""

    @abstractmethod
    def wipe(self):
        """Clear the log storage."""

    @abstractmethod
    def watch(self, run_id: str, cursor: str, callback: Callable):
        """Call this method to start watching."""

    @abstractmethod
    def end_watch(self, run_id: str, handler: Callable):
        """Call this method to stop watching."""

    @property
    @abstractmethod
    def is_persistent(self) -> bool:
        """bool: Whether the storage is persistent."""

    def dispose(self):
        """Explicit lifecycle management."""

    def optimize_for_dagit(self, statement_timeout: int):
        """Allows for optimizing database connection / use in the context of a long lived dagit process"""

    @abstractmethod
    def get_event_records(
        self,
        event_records_filter: Optional[EventRecordsFilter] = None,
        limit: Optional[int] = None,
        ascending: bool = False,
    ) -> Iterable[EventLogRecord]:
        pass

    @abstractmethod
    def get_asset_records(
        self, asset_keys: Optional[Sequence[AssetKey]] = None
    ) -> Iterable[AssetRecord]:
        pass

    @abstractmethod
    def has_asset_key(self, asset_key: AssetKey) -> bool:
        pass

    @abstractmethod
    def all_asset_keys(self) -> Iterable[AssetKey]:
        pass

    def get_asset_keys(
        self,
        prefix: Optional[List[str]] = None,
        limit: Optional[int] = None,
        cursor: Optional[str] = None,
    ) -> Iterable[AssetKey]:
        # base implementation of get_asset_keys, using the existing `all_asset_keys` and doing the
        # filtering in-memory
        asset_keys = sorted(self.all_asset_keys(), key=str)
        if prefix:
            asset_keys = [
                asset_key for asset_key in asset_keys if asset_key.path[: len(prefix)] == prefix
            ]
        if cursor:
            cursor_asset = AssetKey.from_db_string(cursor)
            if cursor_asset and cursor_asset in asset_keys:
                idx = asset_keys.index(cursor_asset)
                asset_keys = asset_keys[idx + 1 :]
        if limit:
            asset_keys = asset_keys[:limit]
        return asset_keys

    @abstractmethod
    def get_latest_materialization_events(
        self, asset_keys: Sequence[AssetKey]
    ) -> Mapping[AssetKey, Optional[EventLogEntry]]:
        pass

    @abstractmethod
    def get_asset_run_ids(self, asset_key: AssetKey) -> Iterable[str]:
        pass

    @abstractmethod
    def wipe_asset(self, asset_key: AssetKey):
        """Remove asset index history from event log for given asset_key"""

    @abstractmethod
    def get_materialization_count_by_partition(
        self, asset_keys: Sequence[AssetKey]
    ) -> Mapping[AssetKey, Mapping[str, int]]:
        pass

    def alembic_version(self):
        return None
