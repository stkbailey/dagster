import {Box, Spinner} from '@dagster-io/ui';
import React from 'react';
import {useHistory} from 'react-router-dom';
import styled from 'styled-components/macro';

import {AssetConnectedEdges} from '../asset-graph/AssetEdges';
import {EXPERIMENTAL_MINI_SCALE} from '../asset-graph/AssetGraphExplorer';
import {AssetNodeMinimal, AssetNode} from '../asset-graph/AssetNode';
import {ForeignNode} from '../asset-graph/ForeignNode';
import {buildComputeStatusData, GraphData, LiveData, toGraphId} from '../asset-graph/Utils';
import {SVGViewport} from '../graph/SVGViewport';
import {useAssetLayout} from '../graph/asyncGraphLayout';

import {AssetKey} from './types';
import {AssetNodeDefinitionFragment} from './types/AssetNodeDefinitionFragment';

const LINEAGE_GRAPH_ZOOM_LEVEL = 'lineageGraphZoomLevel';

export type AssetLineageScope = 'neighbors' | 'upstream' | 'downstream';

export const AssetNodeLineageGraph: React.FC<{
  assetNode: AssetNodeDefinitionFragment;
  assetGraphData: GraphData;
  liveDataByNode: LiveData;
}> = ({assetNode, assetGraphData, liveDataByNode}) => {
  const assetGraphId = toGraphId(assetNode.assetKey);

  const [highlighted, setHighlighted] = React.useState<string | null>(null);

  const {layout, loading} = useAssetLayout(assetGraphData);
  const viewportEl = React.useRef<SVGViewport>();
  const history = useHistory();

  const onClickAsset = (key: AssetKey) => {
    history.push(`/instance/assets/${key.path.join('/')}?view=lineage`);
  };

  React.useEffect(() => {
    if (viewportEl.current && layout) {
      const lastZoomLevel = Number(window.localStorage.getItem(LINEAGE_GRAPH_ZOOM_LEVEL));
      viewportEl.current.autocenter(false, lastZoomLevel);
      viewportEl.current.focus();
    }
  }, [viewportEl, layout, assetGraphId]);

  const computeStatuses = React.useMemo(
    () => buildComputeStatusData(assetGraphData, liveDataByNode),
    [assetGraphData, liveDataByNode],
  );

  if (!layout || loading) {
    return (
      <Box style={{flex: 1}} flex={{alignItems: 'center', justifyContent: 'center'}}>
        <Spinner purpose="page" />
      </Box>
    );
  }

  return (
    <SVGViewport
      ref={(r) => (viewportEl.current = r || undefined)}
      interactor={SVGViewport.Interactors.PanAndZoom}
      graphWidth={layout.width}
      graphHeight={layout.height}
      onDoubleClick={(e) => {
        viewportEl.current?.autocenter(true);
        e.stopPropagation();
      }}
      maxZoom={1.2}
      maxAutocenterZoom={1.2}
    >
      {({scale}) => (
        <SVGContainer width={layout.width} height={layout.height}>
          {viewportEl.current && <SVGSaveZoomLevel scale={scale} />}
          <AssetConnectedEdges highlighted={highlighted} edges={layout.edges} />

          {Object.values(layout.nodes).map(({id, bounds}) => {
            const graphNode = assetGraphData.nodes[id];
            const path = JSON.parse(id);

            return (
              <foreignObject
                {...bounds}
                key={id}
                style={{overflow: 'visible'}}
                onMouseEnter={() => setHighlighted(id)}
                onMouseLeave={() => setHighlighted(null)}
                onClick={() => onClickAsset({path})}
                onDoubleClick={(e) => {
                  viewportEl.current?.zoomToSVGBox(bounds, true, 1.2);
                  e.stopPropagation();
                }}
              >
                {!graphNode || !graphNode.definition.opNames.length ? (
                  <ForeignNode assetKey={{path}} />
                ) : scale < EXPERIMENTAL_MINI_SCALE ? (
                  <AssetNodeMinimal
                    definition={graphNode.definition}
                    selected={graphNode.id === assetGraphId}
                  />
                ) : (
                  <AssetNode
                    definition={graphNode.definition}
                    liveData={liveDataByNode[graphNode.id]}
                    computeStatus={computeStatuses[graphNode.id]}
                    selected={graphNode.id === assetGraphId}
                  />
                )}
              </foreignObject>
            );
          })}
        </SVGContainer>
      )}
    </SVGViewport>
  );
};

const SVGSaveZoomLevel = ({scale}: {scale: number}) => {
  React.useEffect(() => {
    window.localStorage.setItem(LINEAGE_GRAPH_ZOOM_LEVEL, `${scale}`);
  }, [scale]);
  return <></>;
};

const SVGContainer = styled.svg`
  overflow: visible;
  border-radius: 0;
`;
