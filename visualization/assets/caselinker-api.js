/**
 * Adds X-CaseLinker-Internal-Key from sessionStorage when calling the API.
 * Set once in the browser console (same origin as the app):
 *   sessionStorage.setItem('CASELINKER_INTERNAL_KEY', '<your Railway secret>');
 * Do not commit keys or embed them in HTML on a public URL.
 */
(function () {
  var HEADER = 'X-CaseLinker-Internal-Key';
  var STORAGE_KEY = 'CASELINKER_INTERNAL_KEY';

  function internalHeaderPairs() {
    try {
      var k = sessionStorage.getItem(STORAGE_KEY);
      if (k) return [[HEADER, k]];
    } catch (e) { /* private mode / blocked */ }
    return [];
  }

  window.caselinkerFetch = function (input, init) {
    init = init || {};
    var headers = new Headers(init.headers || {});
    internalHeaderPairs().forEach(function (pair) {
      headers.set(pair[0], pair[1]);
    });
    init.headers = headers;
    return fetch(input, init);
  };

  /** Public paginated summaries — no internal key; many small responses vs one bulk JSON. */
  window.caselinkerLoadAllSummariesSequential = async function () {
    var limit = 400;
    var offset = 0;
    var all = [];
    for (;;) {
      var r = await fetch(
        '/api/cases-summaries-chunk?offset=' + offset + '&limit=' + limit
      );
      if (!r.ok) throw new Error('cases-summaries-chunk ' + r.status);
      var j = await r.json();
      var chunk = j.summaries || [];
      for (var i = 0; i < chunk.length; i++) all.push(chunk[i]);
      if (chunk.length < limit) break;
      offset += limit;
    }
    return all;
  };

  /** POST /api/cases-summaries-by-ids in batches (e.g. cluster membership). */
  window.caselinkerPostSummariesByIdsBatched = async function (ids, batchSize) {
    batchSize = batchSize || 500;
    var out = [];
    var list = ids || [];
    for (var i = 0; i < list.length; i += batchSize) {
      var slice = list.slice(i, i + batchSize);
      var r = await fetch('/api/cases-summaries-by-ids', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ids: slice }),
      });
      if (!r.ok) continue;
      var j = await r.json();
      var arr = j.summaries || [];
      for (var k = 0; k < arr.length; k++) out.push(arr[k]);
    }
    return out;
  };
})();
