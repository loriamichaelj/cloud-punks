// CloudPunk artwork: the local SVGs copied from nft-collection/ by `make ui-art` (no external
// requests; the CSP allows img-src 'self'). The API has no image field, so the picture is matched
// by SKU: CP-0001 is cloudpunks/0001.svg. The files have no background: the tile behind them is
// coloured by the CloudPunk's market state.

const files = import.meta.glob<string>('./cloudpunks/*.svg', {
  eager: true,
  query: '?url',
  import: 'default',
});

const artByNumber = new Map<string, string>(
  Object.entries(files).map(([path, url]) => [
    path.replace(/^.*\//, '').replace(/\.svg$/, ''),
    url,
  ]),
);

export function artFor(sku: string): string | undefined {
  const match = /^cp-(\d{4})$/i.exec(sku);
  return match?.[1] ? artByNumber.get(match[1]) : undefined;
}
