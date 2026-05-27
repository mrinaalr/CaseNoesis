(function () {
  function el(tag, attrs, text) {
    const n = document.createElement(tag);
    if (attrs) Object.entries(attrs).forEach(([k, v]) => n.setAttribute(k, v));
    if (text != null) n.textContent = String(text);
    return n;
  }

  function renderBars(container, rows, labelKey, valueKey) {
    const max = Math.max.apply(null, rows.map(r => (r[valueKey] || 0)));
    const denom = max > 0 ? max : 1;
    const wrap = el("div", { class: "mini-bars" });
    rows.forEach(r => {
      const row = el("div", { class: "bar-row" });
      row.appendChild(el("div", { class: "bar-label" }, r[labelKey]));
      const bar = el("div", { class: "bar" });
      const fill = el("span");
      fill.style.width = ((r[valueKey] || 0) / denom * 100).toFixed(1) + "%";
      bar.appendChild(fill);
      row.appendChild(bar);
      row.appendChild(el("div", { class: "bar-val" }, r[valueKey] || 0));
      wrap.appendChild(row);
    });
    container.appendChild(wrap);
  }

  function renderTable(container, headers, rows) {
    const table = el("table");
    const thead = el("thead");
    const trh = el("tr");
    headers.forEach(h => trh.appendChild(el("th", null, h)));
    thead.appendChild(trh);
    table.appendChild(thead);
    const tbody = el("tbody");
    rows.forEach(r => {
      const tr = el("tr");
      r.forEach(cell => tr.appendChild(el("td", null, cell)));
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    container.appendChild(table);
  }

  function caseLink(caseId) {
    return el(
      "a",
      { href: "/visualization?viz=caseviz&case=" + encodeURIComponent(caseId), target: "_blank", rel: "noopener" },
      caseId
    );
  }

  async function main() {
    const qid = (document.body.getAttribute("data-qid") || "").trim().toLowerCase();
    if (!/^q0[1-3]$/.test(qid)) throw new Error("Bad question id: " + qid);

    const resp = await fetch("/ontology/question_data/" + qid + ".json", { cache: "no-store" });
    if (!resp.ok) throw new Error("Failed to load question data: " + resp.status);
    const q = await resp.json();

    document.title = "CaseLinker — " + q.question_id.toUpperCase();
    document.querySelector("#title").textContent = q.question_id.toUpperCase() + ": " + q.title;
    document.querySelector("#audience").textContent = q.audience;
    document.querySelector("#finding").textContent = q.finding_summary;
    document.querySelector("#limitations").textContent = q.limitations || "";
    document.querySelector("#sparql").textContent = (q.sparql_query || "").trim();

    const data = document.querySelector("#data");
    data.innerHTML = "";

    // Heuristic renderers by known shapes
    if (q.data && q.data.top_platforms) {
      renderTable(data, ["Platform", "CAC type", "Cases"], q.data.top_platforms.map(r => [r.platform, r.type, String(r.cases)]));
      renderBars(data, q.data.top_platforms.slice(0, 10).map(r => ({ label: r.platform, value: r.cases })), "label", "value");
    } else if (q.data && q.data.event_distribution) {
      renderTable(data, ["Event type", "Cases"], q.data.event_distribution.map(r => [r.event, String(r.cases)]));
      renderBars(data, q.data.event_distribution.slice(0, 10).map(r => ({ label: r.event, value: r.cases })), "label", "value");
    } else if (q.data && q.data.top_bridge_nodes) {
      renderTable(data, ["Bridge node", "Type", "Cases"], q.data.top_bridge_nodes.map(r => [r.id, r.type, String(r.cases)]));
      renderBars(data, q.data.top_bridge_nodes.slice(0, 10).map(r => ({ label: r.id.replace("resource/", ""), value: r.cases })), "label", "value");
    } else if (q.data && q.data.top_pairs) {
      renderTable(data, ["Platform A", "Platform B", "Cases"], q.data.top_pairs.map(r => [r.a, r.b, String(r.cases)]));
      renderBars(data, q.data.top_pairs.slice(0, 10).map(r => ({ label: r.a + "↔" + r.b, value: r.cases })), "label", "value");
    } else if (q.data && q.data.platform_type_event_profiles) {
      renderTable(
        data,
        ["Platform type", "Cases", "Top events"],
        q.data.platform_type_event_profiles.map(r => [
          r.platform_type,
          String(r.cases),
          (r.top_events || []).map(e => e.event + "(" + e.count + ")").join(", ")
        ])
      );
    } else if (q.data && q.data.e2e_group && q.data.non_e2e_group) {
      renderTable(
        data,
        ["Group", "Cases", "CyberTip %", "Undercover %", "Proactive %", "Charge filed %"],
        [
          ["E2E-associated", String(q.data.e2e_group.cases), String(q.data.e2e_group.cybertip_pct), String(q.data.e2e_group.undercover_pct), String(q.data.e2e_group.proactive_pct), String(q.data.e2e_group.charge_filed_pct)],
          ["Non-E2E", String(q.data.non_e2e_group.cases), String(q.data.non_e2e_group.cybertip_pct), String(q.data.non_e2e_group.undercover_pct), String(q.data.non_e2e_group.proactive_pct), String(q.data.non_e2e_group.charge_filed_pct)]
        ]
      );
    } else if (q.data && q.data.top_classes) {
      renderTable(data, ["CAC class", "Instances", "Cases"], q.data.top_classes.map(r => [r.class, String(r.instances), String(r.cases)]));
    } else if (q.data && q.data.density) {
      renderTable(data, ["CAC class", "Instances", "Median props", "Max props"], q.data.density.map(r => [r.class, String(r.instances), String(r.median_props), String(r.max_props)]));
    } else if (q.data && q.data.top_shared_entities) {
      renderTable(data, ["Shared singleton", "Cases", "Entropy (norm)", "Top partner"], q.data.top_shared_entities.map(r => [r.node, String(r.cases), String(r.normalised_entropy), r.top_partner + " (" + r.top_partner_count + ")"]));
    } else if (q.data && q.data.network) {
      const n = q.data.network;
      renderTable(
        data,
        ["Metric", "Value"],
        [
          ["Cases", String(n.cases)],
          ["Edges", String(n.edges)],
          ["Avg degree", String(n.avg_degree)],
          ["Largest connected component", String(n.largest_connected_component)],
          ["Components", String(n.components)],
          ["Isolated nodes", String(n.isolated_nodes)],
          ["Avg clustering", String(n.avg_clustering)]
        ]
      );
      renderBars(data, (n.top_component_sizes || []).slice(0, 10).map((v, i) => ({ label: "CC#" + (i + 1), value: v })), "label", "value");
    } else if (q.data && q.data.tiers) {
      renderTable(
        data,
        ["Tier", "Cases", "Top events", "Top platforms"],
        q.data.tiers.map(r => [
          r.tier,
          String(r.cases),
          (r.top_events || []).map(e => e[0] + "(" + e[1] + ")").join(", "),
          (r.top_platforms || []).map(p => p[0] + "(" + p[1] + ")").join(", ")
        ])
      );
    } else if (q.data && q.data.top_states) {
      renderTable(
        data,
        ["State", "Cases", "CyberTip %", "Charge mapped %"],
        q.data.top_states.map(r => [r.state, String(r.cases), String(r.cybertip_pct), String(r.charge_mapped_pct)])
      );
    } else if (q.data && q.data.top_unmapped_charges) {
      renderTable(data, ["Charge string", "Count"], q.data.top_unmapped_charges.map(r => [r.charge, String(r.count)]));
    } else if (q.data && q.data.top_leverage_nodes) {
      renderTable(
        data,
        ["Node", "Type", "Cases", "Severe cases", "Severe share %"],
        q.data.top_leverage_nodes.map(r => [r.node, r.type, String(r.cases), String(r.severe_cases), String(r.severe_share_of_node_pct)])
      );
      renderBars(data, q.data.top_leverage_nodes.slice(0, 10).map(r => ({ label: r.node.replace("resource/", ""), value: r.severe_cases })), "label", "value");
    } else if (q.data && q.data.sparql_findings) {
      renderTable(
        data,
        ["Finding", "Result"],
        q.data.sparql_findings.map(r => [r.title, String(r.result)])
      );
    } else {
      data.appendChild(el("pre", null, JSON.stringify(q.data || {}, null, 2)));
    }

    const cases = document.querySelector("#cases");
    cases.innerHTML = "";
    const list = el("div");
    (q.supporting_cases || []).forEach((cid, i) => {
      if (i > 0) list.appendChild(document.createTextNode(" · "));
      list.appendChild(caseLink(cid));
    });
    cases.appendChild(list);
  }

  main().catch(err => {
    const finding = document.querySelector("#finding");
    if (finding) finding.textContent = "Failed to load this question page. " + err.message;
  });
})();

