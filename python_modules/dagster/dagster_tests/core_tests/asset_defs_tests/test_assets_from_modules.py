import re

import pytest

from dagster import (
    AssetKey,
    AssetsDefinition,
    DagsterInvalidDefinitionError,
    SourceAsset,
    asset,
    assets_from_current_module,
    assets_from_modules,
    assets_from_package_module,
    assets_from_package_name,
)

get_unique_asset_identifier = (
    lambda asset: asset.op.name if isinstance(asset, AssetsDefinition) else asset.key
)


def test_assets_from_package_name():
    from . import asset_package

    assets_defs = assets_from_package_name(asset_package.__name__)
    assert len(assets_defs) == 10

    assets_1 = [get_unique_asset_identifier(asset) for asset in assets_defs]

    assets_defs_2 = assets_from_package_name(asset_package.__name__)
    assert len(assets_defs_2) == 10

    assets_2 = [get_unique_asset_identifier(asset) for asset in assets_defs]

    assert assets_1 == assets_2


def test_assets_from_package_module():
    from . import asset_package

    assets_1 = assets_from_package_module(asset_package)
    assert len(assets_1) == 10

    assets_1 = [get_unique_asset_identifier(asset) for asset in assets_1]

    assets_2 = assets_from_package_module(asset_package)
    assert len(assets_2) == 10

    assets_2 = [get_unique_asset_identifier(asset) for asset in assets_2]

    assert assets_1 == assets_2


def test_assets_from_modules(monkeypatch):
    from . import asset_package
    from .asset_package import module_with_assets

    collection_1 = assets_from_modules([asset_package, module_with_assets])

    assets_1 = [get_unique_asset_identifier(asset) for asset in collection_1]

    collection_2 = assets_from_modules([asset_package, module_with_assets])

    assets_2 = [get_unique_asset_identifier(asset) for asset in collection_2]

    assert assets_1 == assets_2

    with monkeypatch.context() as m:

        @asset
        def little_richard():
            pass

        m.setattr(asset_package, "little_richard_dup", little_richard, raising=False)
        with pytest.raises(
            DagsterInvalidDefinitionError,
            match=re.escape(
                "Asset key AssetKey(['little_richard']) is defined multiple times. "
                "Definitions found in modules: dagster_tests.core_tests.asset_defs_tests.asset_package."
            ),
        ):
            assets_from_modules([asset_package, module_with_assets])


@asset(group_name="my_group")
def asset_in_current_module():
    pass


source_asset_in_current_module = SourceAsset(AssetKey("source_asset_in_current_module"))


def test_assets_from_current_module():
    assets = assets_from_current_module()
    assets = [get_unique_asset_identifier(asset) for asset in assets]
    assert assets == ["asset_in_current_module", AssetKey("source_asset_in_current_module")]
    assert len(assets) == 2


def test_assets_from_modules_with_group_name():
    from . import asset_package
    from .asset_package import module_with_assets

    def check_asset_group(assets):
        for asset in assets:
            if isinstance(asset, AssetsDefinition):
                asset_keys = asset.asset_keys
                for asset_key in asset_keys:
                    assert asset.group_names.get(asset_key) == "my_cool_group"

    assets = assets_from_modules([asset_package, module_with_assets], group_name="my_cool_group")
    check_asset_group(assets)

    assets = assets_from_package_module(asset_package, group_name="my_cool_group")
    check_asset_group(assets)


def test_respect_existing_groups():
    assets = assets_from_current_module()
    assert assets[0].group_names.get(AssetKey("asset_in_current_module")) == "my_group"

    with pytest.raises(DagsterInvalidDefinitionError):
        assets_from_current_module(group_name="yay")


def test_prefix():
    from . import asset_package
    from .asset_package import module_with_assets

    def check_asset_prefix(assets):
        for asset in assets:
            if isinstance(asset, AssetsDefinition):
                asset_keys = asset.asset_keys
                for asset_key in asset_keys:
                    assert asset_key.path[0] == "my_cool_prefix"

    assets = assets_from_modules(
        [asset_package, module_with_assets], asset_key_prefix="my_cool_prefix"
    )
    check_asset_prefix(assets)

    assets = assets_from_package_module(asset_package, asset_key_prefix="my_cool_prefix")
    check_asset_prefix(assets)
