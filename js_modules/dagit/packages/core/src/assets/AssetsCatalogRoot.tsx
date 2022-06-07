import {gql, useQuery} from '@apollo/client';
import {Box, Page, Spinner} from '@dagster-io/ui';
import * as React from 'react';
import {useParams} from 'react-router-dom';

import {displayNameForAssetKey} from '../asset-graph/Utils';
import {useDocumentTitle} from '../hooks/useDocumentTitle';
import {ReloadAllButton} from '../workspace/ReloadAllButton';

import {AssetPageHeader} from './AssetPageHeader';
import {AssetView} from './AssetView';
import {AssetsCatalogTable} from './AssetsCatalogTable';
import {
  AssetsCatalogRootQuery,
  AssetsCatalogRootQueryVariables,
} from './types/AssetsCatalogRootQuery';

export const AssetsCatalogRoot = () => {
  const params = useParams();
  const currentPath: string[] = (params['0'] || '')
    .split('/')
    .filter((x: string) => x)
    .map(decodeURIComponent);

  const queryResult = useQuery<AssetsCatalogRootQuery, AssetsCatalogRootQueryVariables>(
    ASSETS_CATALOG_ROOT_QUERY,
    {
      skip: currentPath.length === 0,
      variables: {assetKey: {path: currentPath}},
    },
  );

  useDocumentTitle(
    currentPath && currentPath.length
      ? `Assets: ${displayNameForAssetKey({path: currentPath})}`
      : 'Assets',
  );

  return queryResult.loading ? (
    <Page>
      <AssetPageHeader assetKey={{path: currentPath}} />
      <Box padding={64}>
        <Spinner purpose="page" />
      </Box>
    </Page>
  ) : currentPath.length === 0 ||
    queryResult.data?.assetOrError.__typename === 'AssetNotFoundError' ? (
    <Page>
      <AssetPageHeader
        assetKey={{path: currentPath}}
        right={<ReloadAllButton label="Reload definitions" />}
      />
      <AssetsCatalogTable prefixPath={currentPath} />
    </Page>
  ) : (
    <AssetView assetKey={{path: currentPath}} />
  );
};

const ASSETS_CATALOG_ROOT_QUERY = gql`
  query AssetsCatalogRootQuery($assetKey: AssetKeyInput!) {
    assetOrError(assetKey: $assetKey) {
      __typename
      ... on Asset {
        id
        key {
          path
        }
      }
    }
  }
`;
