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

  function isLocalDevHost() {
    try {
      var h = window.location.hostname || '';
      return h === 'localhost' || h === '127.0.0.1' || h === '[::1]';
    } catch (e) {
      return false;
    }
  }

  /**
   * Load all case rows for visualization pages.
   * - Local dev (localhost): one GET /api/cases — same data the server uses for analysis; avoids many
   *   sequential chunk round-trips. Requires no secret (run/main.py treats localhost as internal).
   * - Production: paginated slim summaries only (public-safe, smaller payloads).
   */
  window.caselinkerLoadAllSummariesSequential = async function () {
    if (isLocalDevHost()) {
      var r = await caselinkerFetch('/api/cases?include_raw_data=false');
      if (!r.ok) throw new Error('api/cases ' + r.status);
      var data = await r.json();
      return Array.isArray(data) ? data : [];
    }

    var limit = 500;
    var concurrency = 4;
    var all = [];
    var baseOffset = 0;

    async function fetchChunk(offset) {
      var r = await fetch(
        '/api/cases-summaries-chunk?offset=' + offset + '&limit=' + limit
      );
      if (!r.ok) throw new Error('cases-summaries-chunk ' + r.status);
      var j = await r.json();
      return j.summaries || [];
    }

    for (;;) {
      var offsets = [];
      for (var c = 0; c < concurrency; c++) {
        offsets.push(baseOffset + c * limit);
      }

      var chunks = await Promise.all(offsets.map(fetchChunk));
      var shouldStop = false;

      for (var idx = 0; idx < chunks.length; idx++) {
        var chunk = chunks[idx];
        for (var i = 0; i < chunk.length; i++) all.push(chunk[i]);
        if (chunk.length < limit) {
          shouldStop = true;
          break;
        }
      }

      if (shouldStop) break;
      baseOffset += concurrency * limit;
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
