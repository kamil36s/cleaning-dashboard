function identityPart(value) {
  return String(value || '')
    .normalize('NFKD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .replace(/ł/g, 'l')
    .replace(/[đð]/g, 'd')
    .replace(/þ/g, 'th')
    .replace(/æ/g, 'ae')
    .replace(/œ/g, 'oe')
    .replace(/ø/g, 'o')
    .replace(/&/g, ' and ')
    .replace(/[^a-z0-9]+/g, ' ')
    .trim();
}

function identityKey(artist, album) {
  return `${identityPart(artist)}|${identityPart(album)}`;
}

function payloadRows(payload) {
  return Array.isArray(payload) ? payload : (Array.isArray(payload?.rows) ? payload.rows : []);
}

function addUniqueCrossList(items, crossList) {
  if (!crossList?.key || items.some((item) => item?.key === crossList.key)) return;
  items.push(crossList);
}

export function mergeBm365CrossLists(payload, { brutalAssault, rymPolish } = {}) {
  const baMatches = Array.isArray(brutalAssault?.matches) ? brutalAssault.matches : [];
  const baByRowId = new Map(baMatches.map((match) => [String(match?.bmRowId), match]));
  const baByKey = new Map(baMatches.map((match) => [
    identityKey(match?.artist, match?.album),
    match,
  ]));
  const rymByKey = new Map(payloadRows(rymPolish).map((row) => [
    identityKey(row?.artist, row?.album),
    row,
  ]));

  const rows = payloadRows(payload).map((row) => {
    const crossLists = Array.isArray(row?.crossLists)
      ? row.crossLists.filter(Boolean).map((item) => ({ ...item }))
      : (row?.crossList ? [{ ...row.crossList }] : []);
    const key = identityKey(row?.artist, row?.album);
    const baMatch = baByRowId.get(String(row?.rowId)) || baByKey.get(key);
    if (baMatch) {
      addUniqueCrossList(crossLists, {
        key: 'brutal-assault-2027',
        label: 'Brutal Assault 2027',
        rowId: baMatch.baRowId,
        date: baMatch.baDate,
        rating: baMatch.rating,
      });
    }
    const rymRow = rymByKey.get(key);
    if (rymRow) {
      addUniqueCrossList(crossLists, {
        key: 'rym-polish-black-metal-top-100',
        label: 'Top 100 RYM Polish BM',
        rowId: rymRow.rowId,
        rank: rymRow.sourceRank,
        rating: rymRow.rating,
      });
    }
    return crossLists.length
      ? { ...row, crossLists, crossList: crossLists[0] }
      : row;
  });

  return Array.isArray(payload) ? rows : { ...payload, rows };
}
