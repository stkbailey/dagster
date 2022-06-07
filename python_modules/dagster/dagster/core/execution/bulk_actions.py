from enum import Enum
from dagster.serdes import whitelist_for_serdes


@whitelist_for_serdes
class BulkActionType(Enum):
    PARITION_BACKFILL = "PARTITION_BACKFILL"
