import {gql, useQuery} from '@apollo/client';
import {
  Alert,
  Box,
  ButtonGroup,
  ButtonLink,
  Checkbox,
  Colors,
  NonIdealState,
  Spinner,
  Tab,
  Tabs,
  Tag,
} from '@dagster-io/ui';
import * as React from 'react';
import {Link} from 'react-router-dom';

import {
  FIFTEEN_SECONDS,
  QueryRefreshCountdown,
  useMergedRefresh,
  useQueryRefreshAtInterval,
} from '../app/QueryRefresh';
import {Timestamp} from '../app/time/Timestamp';
import {GraphData, toGraphId, tokenForAssetKey} from '../asset-graph/Utils';
import {useAssetGraphData} from '../asset-graph/useAssetGraphData';
import {useLiveDataForAssetKeys} from '../asset-graph/useLiveDataForAssetKeys';
import {useQueryPersistedState} from '../hooks/useQueryPersistedState';
import {RepositoryLink} from '../nav/RepositoryLink';
import {useDidLaunchEvent} from '../runs/RunUtils';
import {buildRepoAddress} from '../workspace/buildRepoAddress';
import {workspacePathFromAddress} from '../workspace/workspacePath';

import {AssetEvents} from './AssetEvents';
import {AssetNodeDefinition, ASSET_NODE_DEFINITION_FRAGMENT} from './AssetNodeDefinition';
import {AssetNodeInstigatorTag, ASSET_NODE_INSTIGATORS_FRAGMENT} from './AssetNodeInstigatorTag';
import {AssetLineageScope, AssetNodeLineageGraph} from './AssetNodeLineageGraph';
import {AssetPageHeader} from './AssetPageHeader';
import {LaunchAssetExecutionButton} from './LaunchAssetExecutionButton';
import {AssetKey} from './types';
import {AssetQuery, AssetQueryVariables} from './types/AssetQuery';

interface Props {
  assetKey: AssetKey;
}

export interface AssetViewParams {
  view?: 'activity' | 'definition' | 'lineage';
  lineageScope?: AssetLineageScope;
  lineageShowSecondaryEdges?: boolean;
  partition?: string;
  time?: string;
  asOf?: string;
}

export const AssetView: React.FC<Props> = ({assetKey}) => {
  const [params, setParams] = useQueryPersistedState<AssetViewParams>({});

  const queryResult = useQuery<AssetQuery, AssetQueryVariables>(ASSET_QUERY, {
    variables: {assetKey: {path: assetKey.path}},
    notifyOnNetworkStatusChange: true,
  });

  const {assetOrError} = queryResult.data || queryResult.previousData || {};
  const asset = assetOrError && assetOrError.__typename === 'Asset' ? assetOrError : null;
  const lastMaterializedAt = asset?.assetMaterializations[0]?.timestamp;
  const viewingMostRecent = !params.asOf || Number(lastMaterializedAt) <= Number(params.asOf);

  const definition = asset?.definition;
  const repoAddress = definition
    ? buildRepoAddress(definition.repository.name, definition.repository.location.name)
    : null;

  const token = tokenForAssetKey(assetKey);
  const {assetGraphData, graphAssetKeys} = useAssetGraphData(
    params.view === 'lineage' && params.lineageScope === 'upstream'
      ? `*"${token}"`
      : params.view === 'lineage' && params.lineageScope === 'downstream'
      ? `"${token}"*`
      : `++"${token}"++`,
    {hideEdgesToNodesOutsideQuery: !params.lineageShowSecondaryEdges},
  );

  const {upstream, downstream} = useNeighborsFromGraph(assetGraphData, assetKey);
  const {liveResult, liveDataByNode} = useLiveDataForAssetKeys(graphAssetKeys);

  const refreshState = useMergedRefresh(
    useQueryRefreshAtInterval(queryResult, FIFTEEN_SECONDS),
    useQueryRefreshAtInterval(liveResult, FIFTEEN_SECONDS),
  );

  // Refresh immediately when a run is launched from this page
  useDidLaunchEvent(queryResult.refetch);
  useDidLaunchEvent(liveResult.refetch);

  // Avoid thrashing the materializations UI (which chooses a different default query based on whether
  // data is partitioned) by waiting for the definition to be loaded. (null OR a valid definition)
  const isDefinitionLoaded = definition !== undefined;
  return (
    <Box flex={{direction: 'column'}} style={{height: '100%', width: '100%', overflowY: 'auto'}}>
      <AssetPageHeader
        assetKey={assetKey}
        tags={
          <>
            {repoAddress ? (
              <Tag icon="asset">
                Asset in <RepositoryLink repoAddress={repoAddress} />
              </Tag>
            ) : (
              <Tag icon="asset_non_sda">Asset</Tag>
            )}
            {definition && repoAddress && (
              <AssetNodeInstigatorTag assetNode={definition} repoAddress={repoAddress} />
            )}
            {definition && repoAddress && definition.groupName && (
              <Tag icon="asset_group">
                <Link
                  to={workspacePathFromAddress(
                    repoAddress,
                    `/asset-groups/${definition.groupName}`,
                  )}
                >
                  {definition.groupName}
                </Link>
              </Tag>
            )}
          </>
        }
        tabs={
          <Tabs size="large" selectedTabId={params.view || 'activity'}>
            <Tab
              id="activity"
              title="Activity"
              onClick={() => setParams({...params, view: 'activity'})}
            />
            <Tab
              id="definition"
              title="Definition"
              onClick={() => setParams({...params, view: 'definition'})}
              disabled={!definition}
            />
            <Tab
              id="lineage"
              title="Lineage"
              onClick={() => setParams({...params, view: 'lineage'})}
              disabled={!definition}
            />
          </Tabs>
        }
        right={
          <Box style={{margin: '-4px 0'}} flex={{gap: 8, alignItems: 'baseline'}}>
            <Box margin={{top: 4}}>
              <QueryRefreshCountdown refreshState={refreshState} />
            </Box>
            {definition && definition.jobNames.length > 0 && repoAddress && upstream && (
              <LaunchAssetExecutionButton
                assets={[definition]}
                upstreamAssetKeys={upstream.map((u) => u.assetKey)}
                preferredJobName={definition.jobNames[0]}
                title={lastMaterializedAt ? 'Rematerialize' : 'Materialize'}
              />
            )}
          </Box>
        }
      />

      <div>
        {queryResult.loading && !queryResult.previousData ? (
          <Box
            style={{height: 390}}
            flex={{direction: 'row', justifyContent: 'center', alignItems: 'center'}}
          >
            <Spinner purpose="page" />
          </Box>
        ) : viewingMostRecent ? null : (
          <Box
            padding={{vertical: 16, horizontal: 24}}
            border={{side: 'bottom', width: 1, color: Colors.KeylineGray}}
          >
            <HistoricalViewAlert
              asOf={params.asOf}
              onClick={() => setParams({asOf: undefined, time: params.asOf})}
              hasDefinition={!!definition}
            />
          </Box>
        )}
      </div>
      {isDefinitionLoaded &&
        (params.view === 'definition' ? (
          definition ? (
            <AssetNodeDefinition
              assetNode={definition}
              upstream={upstream}
              downstream={downstream}
              liveDataByNode={liveDataByNode}
            />
          ) : (
            <AssetNoDefinitionState />
          )
        ) : params.view === 'lineage' ? (
          definition ? (
            assetGraphData ? (
              <>
                <Box
                  flex={{justifyContent: 'space-between', alignItems: 'center'}}
                  padding={{horizontal: 24, vertical: 12}}
                  border={{side: 'bottom', color: Colors.KeylineGray, width: 1}}
                >
                  <ButtonGroup<AssetLineageScope>
                    activeItems={new Set([params.lineageScope || 'neighbors'])}
                    buttons={[
                      {id: 'neighbors', label: 'Nearest Neighbors', icon: 'graph_neighbors'},
                      {id: 'upstream', label: 'Upstream', icon: 'graph_upstream'},
                      {id: 'downstream', label: 'Downstream', icon: 'graph_downstream'},
                    ]}
                    onClick={(lineageScope) => setParams({...params, lineageScope})}
                  />
                  <Checkbox
                    format="switch"
                    label="Show secondary edges"
                    checked={params.lineageShowSecondaryEdges === true}
                    onChange={() =>
                      setParams({
                        ...params,
                        lineageShowSecondaryEdges: params.lineageShowSecondaryEdges
                          ? undefined
                          : true,
                      })
                    }
                  />
                </Box>
                <AssetNodeLineageGraph
                  assetNode={definition}
                  liveDataByNode={liveDataByNode}
                  assetGraphData={assetGraphData}
                />
              </>
            ) : (
              <Box style={{flex: 1}} flex={{alignItems: 'center', justifyContent: 'center'}}>
                <Spinner purpose="page" />
              </Box>
            )
          ) : (
            <AssetNoDefinitionState />
          )
        ) : (
          <AssetEvents
            assetKey={assetKey}
            assetLastMaterializedAt={lastMaterializedAt}
            assetHasDefinedPartitions={!!definition?.partitionDefinition}
            params={params}
            paramsTimeWindowOnly={!!params.asOf}
            setParams={setParams}
            liveData={definition ? liveDataByNode[toGraphId(definition.assetKey)] : undefined}
          />
        ))}
    </Box>
  );
};

const AssetNoDefinitionState = () => (
  <Box padding={{vertical: 32}}>
    <NonIdealState
      title="No definition"
      description="This asset doesn't have a software definition in any of your loaded repositories."
      icon="materialization"
    />
  </Box>
);

function useNeighborsFromGraph(graphData: GraphData | null, assetKey: AssetKey) {
  const graphId = toGraphId(assetKey);

  return React.useMemo(() => {
    if (!graphData) {
      return {upstream: null, downstream: null};
    }
    return {
      upstream: Object.values(graphData.nodes)
        .filter((n) => graphData.upstream[graphId]?.[toGraphId(n.assetKey)])
        .map((n) => n.definition),
      downstream: Object.values(graphData.nodes)
        .filter((n) => graphData.downstream[graphId]?.[toGraphId(n.assetKey)])
        .map((n) => n.definition),
    };
  }, [graphData, graphId]);
}

const ASSET_QUERY = gql`
  query AssetQuery($assetKey: AssetKeyInput!) {
    assetOrError(assetKey: $assetKey) {
      ... on Asset {
        id
        key {
          path
        }

        assetMaterializations(limit: 1) {
          timestamp
        }

        definition {
          id
          groupName
          partitionDefinition
          repository {
            id
            name
            location {
              id
              name
            }
          }

          ...AssetNodeInstigatorsFragment
          ...AssetNodeDefinitionFragment
        }
      }
    }
  }
  ${ASSET_NODE_INSTIGATORS_FRAGMENT}
  ${ASSET_NODE_DEFINITION_FRAGMENT}
`;

const HistoricalViewAlert: React.FC<{
  asOf: string | undefined;
  onClick: () => void;
  hasDefinition: boolean;
}> = ({asOf, onClick, hasDefinition}) => (
  <Alert
    intent="info"
    title={
      <span>
        This is a historical view of materializations as of{' '}
        <span style={{fontWeight: 600}}>
          <Timestamp
            timestamp={{ms: Number(asOf)}}
            timeFormat={{showSeconds: true, showTimezone: true}}
          />
        </span>
        .
      </span>
    }
    description={
      <ButtonLink onClick={onClick} underline="always">
        {hasDefinition
          ? 'Show definition and latest materializations'
          : 'Show latest materializations'}
      </ButtonLink>
    }
  />
);
