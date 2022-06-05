import datetime
from collections import defaultdict

import pytest

from dagster import (
    AssetGroup,
    AssetKey,
    DagsterInvalidDefinitionError,
    DagsterInvariantViolationError,
    JobDefinition,
    PipelineDefinition,
    SensorDefinition,
    SolidDefinition,
    SourceAsset,
    asset,
    build_schedule_from_partitioned_job,
    daily_partitioned_config,
    daily_schedule,
    graph,
    job,
    lambda_solid,
    op,
    pipeline,
    repository,
    schedule,
    sensor,
    solid,
)
from dagster._check import CheckError
from dagster.core.definitions.partition import PartitionedConfig, StaticPartitionsDefinition
from dagster.core.definitions.unresolved_job_definition import UnresolvedJobDefinition
from dagster.core.errors import DagsterInvalidSubsetError


def create_single_node_pipeline(name, called):
    called[name] = called[name] + 1
    return PipelineDefinition(
        name=name,
        solid_defs=[
            SolidDefinition(
                name=name + "_solid",
                input_defs=[],
                output_defs=[],
                compute_fn=lambda *_args, **_kwargs: None,
            )
        ],
    )


def test_repo_lazy_definition():
    called = defaultdict(int)

    @repository
    def lazy_repo():
        return {
            "pipelines": {
                "foo": lambda: create_single_node_pipeline("foo", called),
                "bar": lambda: create_single_node_pipeline("bar", called),
            }
        }

    foo_pipeline = lazy_repo.get_pipeline("foo")
    assert isinstance(foo_pipeline, PipelineDefinition)
    assert foo_pipeline.name == "foo"

    assert "foo" in called
    assert called["foo"] == 1
    assert "bar" not in called

    bar_pipeline = lazy_repo.get_pipeline("bar")
    assert isinstance(bar_pipeline, PipelineDefinition)
    assert bar_pipeline.name == "bar"

    assert "foo" in called
    assert called["foo"] == 1
    assert "bar" in called
    assert called["bar"] == 1

    foo_pipeline = lazy_repo.get_pipeline("foo")
    assert isinstance(foo_pipeline, PipelineDefinition)
    assert foo_pipeline.name == "foo"

    assert "foo" in called
    assert called["foo"] == 1

    pipelines = lazy_repo.get_all_pipelines()

    assert set(["foo", "bar"]) == {pipeline.name for pipeline in pipelines}


def test_dupe_solid_repo_definition():
    @lambda_solid(name="same")
    def noop():
        pass

    @lambda_solid(name="same")
    def noop2():
        pass

    @repository
    def error_repo():
        return {
            "pipelines": {
                "first": lambda: PipelineDefinition(name="first", solid_defs=[noop]),
                "second": lambda: PipelineDefinition(name="second", solid_defs=[noop2]),
            }
        }

    with pytest.raises(
        DagsterInvalidDefinitionError,
        match="Conflicting definitions found in repository with name 'same'. Op/Graph/Solid definition names must be unique within a repository.",
    ):
        error_repo.get_all_pipelines()


def test_non_lazy_pipeline_dict():
    called = defaultdict(int)

    @repository
    def some_repo():
        return [
            create_single_node_pipeline("foo", called),
            create_single_node_pipeline("bar", called),
        ]

    assert some_repo.get_pipeline("foo").name == "foo"
    assert some_repo.get_pipeline("bar").name == "bar"


def test_conflict():
    called = defaultdict(int)
    with pytest.raises(Exception, match="Duplicate pipeline definition found for pipeline 'foo'"):

        @repository
        def _some_repo():
            return [
                create_single_node_pipeline("foo", called),
                create_single_node_pipeline("foo", called),
            ]


def test_key_mismatch():
    called = defaultdict(int)

    @repository
    def some_repo():
        return {"pipelines": {"foo": lambda: create_single_node_pipeline("bar", called)}}

    with pytest.raises(Exception, match="name in PipelineDefinition does not match"):
        some_repo.get_pipeline("foo")


def test_non_pipeline_in_pipelines():
    with pytest.raises(DagsterInvalidDefinitionError, match="all elements of list must be of type"):

        @repository
        def _some_repo():
            return ["not-a-pipeline"]


def test_schedule_partitions():
    @daily_schedule(
        pipeline_name="foo",
        start_date=datetime.datetime(2020, 1, 1),
    )
    def daily_foo(_date):
        return {}

    @repository
    def some_repo():
        return {
            "pipelines": {"foo": lambda: create_single_node_pipeline("foo", defaultdict(int))},
            "schedules": {"daily_foo": lambda: daily_foo},
        }

    assert len(some_repo.schedule_defs) == 1
    assert len(some_repo.partition_set_defs) == 1
    assert some_repo.get_partition_set_def("daily_foo_partitions")


def test_bad_schedule():
    @daily_schedule(
        pipeline_name="foo",
        start_date=datetime.datetime(2020, 1, 1),
    )
    def daily_foo(_date):
        return {}

    with pytest.raises(
        DagsterInvalidDefinitionError,
        match='targets job/pipeline "foo" which was not found in this repository',
    ):

        @repository
        def _some_repo():
            return [daily_foo]


def test_bad_sensor():
    @sensor(
        pipeline_name="foo",
    )
    def foo_sensor(_):
        return {}

    with pytest.raises(
        DagsterInvalidDefinitionError,
        match='targets job/pipeline "foo" which was not found in this repository',
    ):

        @repository
        def _some_repo():
            return [foo_sensor]


def test_direct_schedule_target():
    @solid
    def wow():
        return "wow"

    @graph
    def wonder():
        wow()

    @schedule(cron_schedule="* * * * *", job=wonder)
    def direct_schedule():
        return {}

    @repository
    def test():
        return [direct_schedule]

    assert test


def test_direct_schedule_unresolved_target():

    unresolved_job = UnresolvedJobDefinition(name="unresolved_job", selection="foo")

    @asset
    def foo():
        return None

    foo_group = AssetGroup([foo])

    @schedule(cron_schedule="* * * * *", job=unresolved_job)
    def direct_schedule():
        return {}

    @repository
    def test():
        return [direct_schedule, foo_group]

    assert isinstance(test.get_job("unresolved_job"), JobDefinition)


def test_direct_sensor_target():
    @solid
    def wow():
        return "wow"

    @graph
    def wonder():
        wow()

    @sensor(job=wonder)
    def direct_sensor(_):
        return {}

    @repository
    def test():
        return [direct_sensor]

    assert test


def test_direct_sensor_unresolved_target():

    unresolved_job = UnresolvedJobDefinition(name="unresolved_job", selection="foo")

    @asset
    def foo():
        return None

    foo_group = AssetGroup([foo])

    @sensor(job=unresolved_job)
    def direct_sensor(_):
        return {}

    @repository
    def test():
        return [direct_sensor, foo_group]

    assert isinstance(test.get_job("unresolved_job"), JobDefinition)


def test_target_dupe_job():
    @solid
    def wow():
        return "wow"

    @graph
    def wonder():
        wow()

    w_job = wonder.to_job()

    @sensor(job=w_job)
    def direct_sensor(_):
        return {}

    @repository
    def test():
        return [direct_sensor, w_job]

    assert test


def test_target_dupe_unresolved():
    unresolved_job = UnresolvedJobDefinition(name="unresolved_job", selection="foo")

    @asset
    def foo():
        return None

    foo_group = AssetGroup([foo])

    @sensor(job=unresolved_job)
    def direct_sensor(_):
        return {}

    @repository
    def test():
        return [foo_group, direct_sensor, unresolved_job]

    assert isinstance(test.get_job("unresolved_job"), JobDefinition)


def test_bare_graph():
    @solid
    def ok():
        return "sure"

    @graph
    def bare():
        ok()

    @repository
    def test():
        return [bare]

    # should get updated once "executable" exists
    assert test.get_pipeline("bare")
    assert test.get_job("bare")


def test_unresolved_job():
    unresolved_job = UnresolvedJobDefinition(name="unresolved_job", selection="foo")

    @asset
    def foo():
        return None

    foo_group = AssetGroup([foo])

    @repository
    def test():
        return [foo_group, unresolved_job]

    assert isinstance(test.get_job("unresolved_job"), JobDefinition)
    assert isinstance(test.get_pipeline("unresolved_job"), JobDefinition)


def test_bare_graph_with_resources():
    @solid(required_resource_keys={"stuff"})
    def needy(context):
        return context.resources.stuff

    @graph
    def bare():
        needy()

    with pytest.raises(DagsterInvalidDefinitionError, match="Failed attempting to coerce Graph"):

        @repository
        def _test():
            return [bare]


def test_sensor_no_pipeline_name():
    foo_system_sensor = SensorDefinition(name="foo", evaluation_fn=lambda x: x)

    @repository
    def foo_repo():
        return [foo_system_sensor]

    assert foo_repo.has_sensor_def("foo")


def test_job_with_partitions():
    @solid
    def ok():
        return "sure"

    @graph
    def bare():
        ok()

    @repository
    def test():
        return [
            bare.to_job(
                resource_defs={},
                config=PartitionedConfig(
                    partitions_def=StaticPartitionsDefinition(["abc"]),
                    run_config_for_partition_fn=lambda _: {},
                ),
            )
        ]

    assert test.get_partition_set_def("bare_partition_set")
    # do it twice to make sure we don't overwrite cache on second time
    assert test.get_partition_set_def("bare_partition_set")
    assert test.has_pipeline("bare")
    assert test.get_pipeline("bare")
    assert test.has_job("bare")
    assert test.get_job("bare")


def test_dupe_graph_defs():
    @solid
    def noop():
        pass

    @pipeline(name="foo")
    def pipe_foo():
        noop()

    @graph(name="foo")
    def graph_foo():
        noop()

    with pytest.raises(
        DagsterInvalidDefinitionError,
        # expect to change as migrate to graph/job
        match="Duplicate pipeline definition found for pipeline 'foo'",
    ):

        @repository
        def _pipe_collide():
            return [graph_foo, pipe_foo]

    def get_collision_repo():
        @repository
        def graph_collide():
            return [
                graph_foo.to_job(name="bar"),
                pipe_foo,
            ]

        return graph_collide

    with pytest.raises(
        DagsterInvalidDefinitionError,
        match="Op/Graph/Solid definition names must be unique within a repository",
    ):

        get_collision_repo().get_all_pipelines()

    with pytest.raises(
        DagsterInvalidDefinitionError,
        match="Op/Graph/Solid definition names must be unique within a repository",
    ):

        get_collision_repo().get_all_jobs()


def test_dupe_unresolved_job_defs():
    unresolved_job = UnresolvedJobDefinition(name="bar", selection="foo")

    @asset
    def foo():
        return None

    foo_group = AssetGroup([foo])

    @op
    def the_op():
        pass

    @graph
    def graph_bar():
        the_op()

    bar = graph_bar.to_job(name="bar")

    with pytest.raises(
        DagsterInvalidDefinitionError,
        match="Duplicate job definition found for job 'bar'",
    ):

        @repository
        def _pipe_collide():
            return [foo_group, unresolved_job, bar]

    def get_collision_repo():
        @repository
        def graph_collide():
            return [
                foo_group,
                graph_bar.to_job(name="bar"),
                unresolved_job,
            ]

        return graph_collide

    with pytest.raises(
        DagsterInvalidDefinitionError,
        match="Duplicate definition found for unresolved job 'bar'",
    ):

        get_collision_repo().get_all_pipelines()

    with pytest.raises(
        DagsterInvalidDefinitionError,
        match="Duplicate definition found for unresolved job 'bar'",
    ):

        get_collision_repo().get_all_jobs()


def test_job_pipeline_collision():
    @solid
    def noop():
        pass

    @pipeline(name="foo")
    def my_pipeline():
        noop()

    @job(name="foo")
    def my_job():
        noop()

    with pytest.raises(
        DagsterInvalidDefinitionError,
        match="Duplicate pipeline definition found for pipeline 'foo'",
    ):

        @repository
        def _some_repo():
            return [my_job, my_pipeline]

    with pytest.raises(
        DagsterInvalidDefinitionError,
        match="Duplicate job definition found for job 'foo'",
    ):

        @repository
        def _some_repo():
            return [my_pipeline, my_job]


def test_job_validation():
    @solid
    def noop():
        pass

    @pipeline
    def my_pipeline():
        noop()

    with pytest.raises(
        DagsterInvalidDefinitionError,
        match="Object mapped to my_pipeline is not an instance of JobDefinition or GraphDefinition.",
    ):

        @repository
        def _my_repo():
            return {"jobs": {"my_pipeline": my_pipeline}}


def test_dict_jobs():
    @graph
    def my_graph():
        pass

    @repository
    def jobs():
        return {
            "jobs": {
                "my_graph": my_graph,
                "other_graph": my_graph.to_job(name="other_graph"),
                "tbd": UnresolvedJobDefinition("tbd", selection="*"),
            }
        }

    assert jobs.get_pipeline("my_graph")
    assert jobs.get_pipeline("other_graph")
    assert jobs.has_job("my_graph")
    assert jobs.get_job("my_graph")
    assert jobs.get_job("other_graph")
    assert jobs.has_job("tbd")
    assert jobs.get_job("tbd")


def test_lazy_jobs():
    @graph
    def my_graph():
        pass

    @repository
    def jobs():
        return {
            "jobs": {
                "my_graph": my_graph,
                "my_job": lambda: my_graph.to_job(name="my_job"),
                "other_job": lambda: my_graph.to_job(name="other_job"),
            }
        }

    assert jobs.get_pipeline("my_graph")
    assert jobs.get_pipeline("my_job")
    assert jobs.get_pipeline("other_job")

    assert jobs.has_job("my_graph")
    assert jobs.get_job("my_job")
    assert jobs.get_job("other_job")


def test_lazy_graph():
    @graph
    def my_graph():
        pass

    @repository
    def jobs():
        return {
            "jobs": {
                "my_graph": lambda: my_graph,
            }
        }

    # Repository with a lazy graph can be constructed, but fails when you try to fetch it
    with pytest.raises(
        CheckError,
        match="Invariant failed. Description: Bad constructor for job my_graph: must return JobDefinition",
    ):
        assert jobs.get_pipeline("my_graph")


def test_list_dupe_graph():
    @graph
    def foo():
        pass

    with pytest.raises(
        DagsterInvalidDefinitionError, match="Duplicate job definition found for graph 'foo'"
    ):

        @repository
        def _jobs():
            return [foo.to_job(name="foo"), foo]


def test_job_cannot_select_pipeline():
    @pipeline
    def my_pipeline():
        pass

    @repository
    def my_repo():
        return [my_pipeline]

    assert my_repo.get_pipeline("my_pipeline")

    with pytest.raises(DagsterInvariantViolationError, match="Could not find job 'my_pipeline'."):
        my_repo.get_job("my_pipeline")


def test_job_scheduled_partitions():
    @graph
    def my_graph():
        pass

    @daily_partitioned_config(start_date="2021-09-01")
    def daily_schedule_config(_start, _end):
        return {}

    my_job = my_graph.to_job(config=daily_schedule_config)
    my_schedule = build_schedule_from_partitioned_job(my_job)

    @repository
    def schedule_repo():
        return [my_schedule]

    @repository
    def job_repo():
        return [my_job]

    @repository
    def schedule_job_repo():
        return [my_job, my_schedule]

    assert len(schedule_repo.partition_set_defs) == 1
    assert schedule_repo.get_partition_set_def("my_graph_partition_set")
    assert len(job_repo.partition_set_defs) == 1
    assert job_repo.get_partition_set_def("my_graph_partition_set")
    assert len(schedule_job_repo.partition_set_defs) == 1
    assert schedule_job_repo.get_partition_set_def("my_graph_partition_set")
    assert len(schedule_job_repo.job_names) == 1


def test_bad_job_pipeline():
    @pipeline
    def foo():
        pass

    @graph
    def bar():
        pass

    with pytest.raises(DagsterInvalidDefinitionError, match="Conflicting"):

        @repository
        def _fails():
            return {
                "pipelines": {"foo": foo},
                "jobs": {"foo": bar.to_job(name="foo")},
            }


def test_bad_coerce():
    @op(required_resource_keys={"x"})
    def foo():
        pass

    @graph
    def bar():
        foo()

    with pytest.raises(DagsterInvalidDefinitionError, match="Failed attempting to coerce Graph"):

        @repository
        def _fails():
            return {
                "jobs": {"bar": bar},
            }


def test_bad_resolve():

    with pytest.raises(DagsterInvalidSubsetError, match="No qualified assets to execute"):

        @repository
        def _fails():
            return {"jobs": {"tbd": UnresolvedJobDefinition(name="tbd", selection="foo")}}


def test_source_assets():
    foo = SourceAsset(key=AssetKey("foo"))
    bar = SourceAsset(key=AssetKey("bar"))

    @repository
    def my_repo():
        return [AssetGroup(assets=[], source_assets=[foo, bar])]

    assert my_repo.source_assets_by_key == {AssetKey("foo"): foo, AssetKey("bar"): bar}


def test_multiple_asset_groups_one_repo():
    @asset
    def asset1():
        ...

    @asset
    def asset2():
        ...

    group1 = AssetGroup(assets=[asset1], source_assets=[SourceAsset(key=AssetKey("foo"))])
    group2 = AssetGroup(assets=[asset2], source_assets=[SourceAsset(key=AssetKey("bar"))])

    @repository
    def my_repo():
        return [group1, group2]

    assert my_repo.source_assets_by_key.keys() == {AssetKey("foo"), AssetKey("bar")}
    assert len(my_repo.get_all_jobs()) == 1
    assert set(my_repo.get_all_jobs()[0].asset_layer.asset_keys) == {
        AssetKey(["asset1"]),
        AssetKey(["asset2"]),
    }


def _create_graph_with_name(name):
    @graph(name=name)
    def _the_graph():
        pass

    return _the_graph


def _create_job_with_name(name):
    @job(name=name)
    def _the_job():
        pass

    return _the_job


def _create_pipeline_with_name(name):
    @pipeline(name=name)
    def _the_pipeline():
        pass

    return _the_pipeline


def _create_schedule_from_target(target):
    @schedule(job=target, cron_schedule="* * * * *")
    def _the_schedule():
        pass

    return _the_schedule


def _create_sensor_from_target(target):
    @sensor(job=target)
    def _the_sensor():
        pass

    return _the_sensor


def test_duplicate_graph_valid():
    the_graph = _create_graph_with_name("foo")

    # Providing the same graph to the repo and multiple schedules / sensors is valid
    @repository
    def the_repo_dupe_graph_valid():
        return [the_graph, _create_sensor_from_target(the_graph)]

    assert len(the_repo_dupe_graph_valid.get_all_jobs()) == 1


def test_duplicate_unresolved_job_valid():
    the_job = UnresolvedJobDefinition(name="foo", selection="*")

    # Providing the same graph to the repo and multiple schedules / sensors is valid
    @repository
    def the_repo_dupe_unresolved_job_valid():
        return [the_job, _create_sensor_from_target(the_job)]

    assert len(the_repo_dupe_unresolved_job_valid.get_all_jobs()) == 1


def test_duplicate_graph_target_invalid():
    the_graph = _create_graph_with_name("foo")
    other_graph = _create_graph_with_name("foo")
    # Different reference-equal graph provided to repo with same name, ensure error is thrown.
    with pytest.warns(
        UserWarning,
        match="sensor '_the_sensor' targets graph 'foo', but a different graph with the same name was provided.",
    ):

        @repository
        def the_repo_dupe_graph_invalid_sensor():
            return [the_graph, _create_sensor_from_target(other_graph)]

    with pytest.warns(
        UserWarning,
        match="schedule '_the_schedule' targets graph 'foo', but a different graph with the same name was provided.",
    ):

        @repository
        def the_repo_dupe_graph_invalid_schedule():
            return [the_graph, _create_schedule_from_target(other_graph)]


def test_duplicate_job_target_valid():
    the_job = _create_job_with_name("foo")

    @repository
    def the_repo_dupe_job_valid():
        return [the_job, _create_schedule_from_target(the_job), _create_sensor_from_target(the_job)]


def test_duplicate_job_target_invalid():
    the_job = _create_job_with_name("foo")
    other_job = _create_job_with_name("foo")

    with pytest.warns(
        UserWarning,
        match="sensor '_the_sensor' targets job 'foo', but a different job with the same name was provided.",
    ):

        @repository
        def the_repo_dupe_job_invalid_sensor():
            return [the_job, _create_sensor_from_target(other_job)]

    with pytest.warns(
        UserWarning,
        match="schedule '_the_schedule' targets job 'foo', but a different job with the same name was provided.",
    ):

        @repository
        def the_repo_dupe_job_invalid_schedule():
            return [the_job, _create_schedule_from_target(other_job)]


def test_dupe_pipelines_valid():
    the_pipeline = _create_pipeline_with_name("foo")

    @repository
    def the_repo_dupe_pipelines_valid():
        return [
            the_pipeline,
            _create_schedule_from_target(the_pipeline),
            _create_sensor_from_target(the_pipeline),
        ]


def test_dupe_pipelines_invalid():
    the_pipeline = _create_pipeline_with_name("foo")
    other_pipeline = _create_pipeline_with_name("foo")

    with pytest.warns(
        UserWarning,
        match="schedule '_the_schedule' targets pipeline 'foo', but a different pipeline with the same name was provided.",
    ):

        @repository
        def the_repo_dupe_pipelines_invalid_schedule():
            return [the_pipeline, _create_schedule_from_target(other_pipeline)]

    with pytest.warns(
        UserWarning,
        match="sensor '_the_sensor' targets pipeline 'foo', but a different pipeline with the same name was provided.",
    ):

        @repository
        def the_repo_dupe_pipelines_invalid_sensor():
            return [the_pipeline, _create_sensor_from_target(other_pipeline)]


def test_dupe_jobs_pipelines_invalid():
    the_job = _create_job_with_name("foo")
    the_pipeline = _create_pipeline_with_name("foo")

    the_schedule = _create_schedule_from_target(the_pipeline)
    the_sensor = _create_sensor_from_target(the_pipeline)
    with pytest.warns(
        UserWarning,
        match="schedule '_the_schedule' targets pipeline 'foo', but a different job with the same name was provided.",
    ):

        @repository
        def the_repo_dupe_job_pipeline_invalid_schedule_job():
            return [the_job, the_schedule]

    with pytest.warns(
        UserWarning,
        match="sensor '_the_sensor' targets pipeline 'foo', but a different job with the same name was provided.",
    ):

        @repository
        def the_repo_dupe_job_pipeline_invalid_sensor_job():
            return [the_job, the_sensor]

    the_graph = _create_graph_with_name("foo")

    with pytest.warns(
        UserWarning,
        match="sensor '_the_sensor' targets pipeline 'foo', but a different graph with the same name was provided.",
    ):

        @repository
        def the_repo_dupe_graph_pipeline_invalid_sensor_graph():
            return [the_graph, the_sensor]

    with pytest.warns(
        UserWarning,
        match="schedule '_the_schedule' targets pipeline 'foo', but a different graph with the same name was provided.",
    ):

        @repository
        def the_repo_dupe_graph_pipeline_invalid_schedule_graph():
            return [the_graph, the_schedule]
