import {gql, useQuery} from '@apollo/client';
import React from 'react';

import {filterByQuery, GraphQueryItem} from '../app/GraphQueryImpl';
import {AssetGroupSelector, PipelineSelector} from '../types/globalTypes';

import {ASSET_NODE_FRAGMENT} from './AssetNode';
import {buildGraphData, GraphData, tokenForAssetKey} from './Utils';
import {
  AssetGraphQuery,
  AssetGraphQueryVariables,
  AssetGraphQuery_assetNodes,
} from './types/AssetGraphQuery';

export interface AssetGraphFetchScope {
  hideEdgesToNodesOutsideQuery?: boolean;
  pipelineSelector?: PipelineSelector;
  groupSelector?: AssetGroupSelector;
}
/** Fetches data for rendering an asset graph:
 *
 * @param pipelineSelector: Optionally scope to an asset job, or pass null for the global graph
 *
 * @param opsQuery: filter the returned graph using selector syntax string (eg: asset_name++)
 *
 * @param filterNodes: filter the returned graph using the provided function. The global graph
 * uses this option to implement the "3 of 4 repositories" picker.
 */
export function useAssetGraphData(opsQuery: string, options: AssetGraphFetchScope) {
  const fetchResult = useQuery<AssetGraphQuery, AssetGraphQueryVariables>(ASSET_GRAPH_QUERY, {
    notifyOnNetworkStatusChange: true,
    variables: {
      pipelineSelector: options.pipelineSelector,
      groupSelector: options.groupSelector,
    },
  });

  const nodes = fetchResult.data?.assetNodes;

  const {
    assetGraphData,
    graphQueryItems,
    graphAssetKeys,
    allAssetKeys,
    applyingEmptyDefault,
  } = React.useMemo(() => {
    if (nodes === undefined) {
      return {
        graphAssetKeys: [],
        graphQueryItems: [],
        assetGraphData: null,
        applyingEmptyDefault: false,
      };
    }

    // Filter the set of all AssetNodes down to those matching the `opsQuery`.
    // In the future it might be ideal to move this server-side, but we currently
    // get to leverage the useQuery cache almost 100% of the time above, making this
    // super fast after the first load vs a network fetch on every page view.
    const graphQueryItems = buildGraphQueryItems(nodes);
    const {all, applyingEmptyDefault} = filterByQuery(graphQueryItems, opsQuery);

    // Assemble the response into the data structure used for layout, traversal, etc.
    const assetGraphData = buildGraphData(all.map((n) => n.node));
    if (options.hideEdgesToNodesOutsideQuery) {
      removeEdgesToHiddenAssets(assetGraphData);
    }

    return {
      allAssetKeys: nodes.map((n) => n.assetKey),
      graphAssetKeys: all.map((n) => ({path: n.node.assetKey.path})),
      assetGraphData,
      graphQueryItems,
      applyingEmptyDefault,
    };
  }, [nodes, opsQuery, options.hideEdgesToNodesOutsideQuery]);

  return {
    fetchResult,
    assetGraphData,
    graphQueryItems,
    graphAssetKeys,
    allAssetKeys,
    applyingEmptyDefault,
  };
}

type AssetNode = AssetGraphQuery_assetNodes;

const buildGraphQueryItems = (nodes: AssetNode[]) => {
  const items: {
    [name: string]: GraphQueryItem & {
      node: AssetNode;
    };
  } = {};

  for (const node of nodes) {
    const name = tokenForAssetKey(node.assetKey);
    items[name] = {
      node,
      name,
      inputs: node.dependencyKeys.map((key) => ({
        dependsOn: [{solid: {name: tokenForAssetKey(key)}}],
      })),
      outputs: node.dependedByKeys.map((key) => ({
        dependedBy: [{solid: {name: tokenForAssetKey(key)}}],
      })),
    };
  }
  return Object.values(items);
};

const removeEdgesToHiddenAssets = (graphData: GraphData) => {
  for (const node of Object.keys(graphData.upstream)) {
    for (const edge of Object.keys(graphData.upstream[node])) {
      if (!graphData.nodes[edge]) {
        delete graphData.upstream[node][edge];
        delete graphData.downstream[edge][node];
      }
    }
  }

  for (const node of Object.keys(graphData.downstream)) {
    for (const edge of Object.keys(graphData.downstream[node])) {
      if (!graphData.nodes[edge]) {
        delete graphData.upstream[edge][node];
        delete graphData.downstream[node][edge];
      }
    }
  }
};

const ASSET_GRAPH_QUERY = gql`
  query AssetGraphQuery($pipelineSelector: PipelineSelector, $groupSelector: AssetGroupSelector) {
    assetNodes(pipeline: $pipelineSelector, group: $groupSelector) {
      id
      dependencyKeys {
        path
      }
      dependedByKeys {
        path
      }
      ...AssetNodeFragment
    }
  }
  ${ASSET_NODE_FRAGMENT}
`;
