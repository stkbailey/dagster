from typing import NamedTuple, Optional, Sequence, Union

import dagster._check as check
from dagster.core.definitions.events import AssetKey, CoerceableToAssetKey
from dagster.core.definitions.metadata import (
    MetadataEntry,
    MetadataMapping,
    MetadataUserInput,
    PartitionMetadataEntry,
    normalize_metadata,
)
from dagster.core.definitions.partition import PartitionsDefinition
from dagster.core.definitions.resource_requirement import ResourceAddable
from dagster.core.definitions.utils import validate_group_name
from dagster.core.errors import DagsterInvalidDefinitionError
from dagster.core.storage.io_manager import IOManagerDefinition


class SourceAsset(
    NamedTuple(
        "_SourceAsset",
        [
            ("key", AssetKey),
            ("metadata_entries", Sequence[Union[MetadataEntry, PartitionMetadataEntry]]),
            ("io_manager_key", Optional[str]),
            ("io_manager_def", Optional[IOManagerDefinition]),
            ("description", Optional[str]),
            ("partitions_def", Optional[PartitionsDefinition]),
            ("group_name", str),
        ],
    ),
    ResourceAddable,
):
    """A SourceAsset represents an asset that will be loaded by (but not updated by) Dagster.

    Attributes:
        key (Union[AssetKey, Sequence[str], str]): The key of the asset.
        metadata_entries (List[MetadataEntry]): Metadata associated with the asset.
        io_manager_key (Optional[str]): The key for the IOManager that will be used to load the contents of
            the asset when it's used as an input to other assets inside a job.
        io_manager_def (Optional[IOManagerDefinition]): The definition of the IOManager that will be used to load the contents of
            the asset when it's used as an input to other assets inside a job.
        description (Optional[str]): The description of the asset.
        partitions_def (Optional[PartitionsDefinition]): Defines the set of partition keys that
            compose the asset.
    """

    def __new__(
        cls,
        key: CoerceableToAssetKey,
        metadata: Optional[MetadataUserInput] = None,
        io_manager_key: Optional[str] = None,
        io_manager_def: Optional[IOManagerDefinition] = None,
        description: Optional[str] = None,
        partitions_def: Optional[PartitionsDefinition] = None,
        _metadata_entries: Optional[Sequence[Union[MetadataEntry, PartitionMetadataEntry]]] = None,
        group_name: Optional[str] = None,
    ):

        key = AssetKey.from_coerceable(key)
        metadata = check.opt_dict_param(metadata, "metadata", key_type=str)
        metadata_entries = _metadata_entries or normalize_metadata(metadata, [], allow_invalid=True)
        return super().__new__(
            cls,
            key=key,
            metadata_entries=metadata_entries,
            io_manager_key=check.opt_str_param(io_manager_key, "io_manager_key"),
            io_manager_def=check.opt_inst_param(
                io_manager_def, "io_manager_def", IOManagerDefinition
            ),
            description=check.opt_str_param(description, "description"),
            partitions_def=check.opt_inst_param(
                partitions_def, "partitions_def", PartitionsDefinition
            ),
            group_name=validate_group_name(group_name),
        )

    @property
    def metadata(self) -> MetadataMapping:
        # PartitionMetadataEntry (unstable API) case is unhandled
        return {entry.label: entry.entry_data for entry in self.metadata_entries}  # type: ignore

    def get_io_manager_key(self) -> str:
        if not self.io_manager_key and not self.io_manager_def:
            return "io_manager"
        source_asset_path = "__".join(self.key.path)
        return self.io_manager_key or f"{source_asset_path}__io_manager"

    def with_resources(self, resource_defs) -> "SourceAsset":
        if self.io_manager_def:
            return self

        io_manager_def = resource_defs.get(self.get_io_manager_key())
        if not io_manager_def and self.get_io_manager_key() != "io_manager":
            raise DagsterInvalidDefinitionError(
                f"SourceAsset with asset key {self.key} requires IO manager with key '{self.get_io_manager_key()}', but none was provided."
            )

        return SourceAsset(
            key=self.key,
            io_manager_def=io_manager_def,
            io_manager_key=self.get_io_manager_key(),
            description=self.description,
            partitions_def=self.partitions_def,
            _metadata_entries=self.metadata_entries,
        )
