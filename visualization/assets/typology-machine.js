/**
 * Typology state machine, interactive L*_{g,A} swimlane (Noesis light palette).
 */
(function () {
  "use strict";

  const AFFORDANCE_COLORS = {
    Anonymity: "#6b8f5e",
    Ephemerality: "#d4a03c",
    UnmonitoredCommunication: "#6b5b8a",
    ContactDiscovery: "#6b8f5e",
    DistributionInfrastructure: "#4a7a9b",
    Coordination: "#c45c4a",
    CoercionLeverage: "#c45c4a",
    ImpersonationOfAuthority: "#6b8f5e",
    PaymentRailAbuse: "#4a7a9b",
    BlockchainObfuscation: "#4a7a9b",
    PhysicalConvergence: "#c45c4a",
  };

  const NODE_W = 182;
  const NODE_H = 108;
  const COL_W = 244;
  const ROW_H = 182;
  const LEFT_PAD = 160;
  const TOP_PAD = 44;

  let panelEl = null;
  let backdropEl = null;

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function affordanceColor(name) {
    return AFFORDANCE_COLORS[name] || "#8a9aa6";
  }

  function arrowPath(x1, y1, x2, y2) {
    const mx = (x1 + x2) / 2;
    return `M${x1},${y1} L${mx},${y1} L${mx},${y2} L${x2},${y2}`;
  }

  function addFlowDots(parent, pathD, color) {
    const g = parent.append("g").attr("class", "flow-dots");
    const svgNs = "http://www.w3.org/2000/svg";
    [0, 1.35].forEach((begin) => {
      const circle = g.append("circle").attr("r", 3).attr("fill", color).attr("class", "flow-dot");
      const motion = document.createElementNS(svgNs, "animateMotion");
      motion.setAttribute("dur", "2.6s");
      motion.setAttribute("repeatCount", "indefinite");
      motion.setAttribute("begin", `${begin}s`);
      motion.setAttribute("path", pathD);
      circle.node().appendChild(motion);
    });
  }

  function wrapLabel(text, maxLen) {
    if (!text || text.length <= maxLen) return [text || ""];
    const words = text.split(" ");
    const lines = [];
    let line = "";
    words.forEach((word) => {
      const next = line ? `${line} ${word}` : word;
      if (next.length > maxLen && line) {
        lines.push(line);
        line = word;
      } else {
        line = next;
      }
    });
    if (line) lines.push(line);
    return lines.slice(0, 3);
  }

  function shortCourtCitation(text) {
    const raw = String(text || "");
    if (!raw) return "";
    if (raw.includes("D.D.C.")) {
      const left = raw.split("·")[0].trim();
      return `${left}, D.D.C.`;
    }
    return raw;
  }

  function nodeFill(phase) {
    if (phase.is_fundamental) return "rgba(212, 160, 60, 0.18)";
    if (phase.is_terminal) return "#efe6d7";
    return "#f6f1e7";
  }

  function nodeStroke(phase, accent) {
    if (phase.is_fundamental) return "rgba(212, 160, 60, 0.75)";
    if (phase.is_variant) return "rgba(107, 91, 74, 0.45)";
    if (phase.is_terminal) return "rgba(107, 91, 74, 0.34)";
    return accent;
  }

  function nodeTextColor(phase) {
    return "#1c1b19";
  }

  function nodeMetaColor(phase, accent) {
    return accent;
  }

  function nodeBlurbColor(phase) {
    return "rgba(28, 27, 25, 0.7)";
  }

  function transitionForPhase(payload, phaseId, direction) {
    const transitions = payload.transitions || [];
    if (direction === "in") {
      return transitions.find((t) => t.to_id === phaseId);
    }
    return transitions.find((t) => t.from_id === phaseId);
  }

  function openPanel(phase, payload) {
    const transIn = transitionForPhase(payload, phase.id, "in");
    const transOut = transitionForPhase(payload, phase.id, "out");

    const badges = [];
    if (phase.is_fundamental) {
      badges.push('<span class="panel-badge">Backbone invariant · Law 2</span>');
    }
    if (phase.is_variant) {
      badges.push('<span class="panel-badge">Variant phase · goal-dependent</span>');
    }
    if (phase.is_terminal) {
      badges.push('<span class="panel-badge">Terminal state</span>');
    }

    const transInHtml = transIn
      ? `<li><span class="affordance-pill" style="background:${affordanceColor(transIn.affordance_name)}22;color:${affordanceColor(transIn.affordance_name)}">${escapeHtml(transIn.affordance_label || "n/a")}</span>${escapeHtml(transIn.misuse_description || "")}</li>`
      : "<li>n/a</li>";

    const transOutHtml = transOut
      ? `<li><span class="affordance-pill" style="background:${affordanceColor(transOut.affordance_name)}22;color:${affordanceColor(transOut.affordance_name)}">${escapeHtml(transOut.affordance_label || "n/a")}</span>${escapeHtml(transOut.misuse_description || "")}</li>`
      : "<li>n/a</li>";

    panelEl.innerHTML = `
      <h3>${escapeHtml(phase.label)}</h3>
      ${
        phase.ontology_id
          ? `<div class="panel-type">${escapeHtml(phase.ontology_id)}</div>`
          : phase.state_label && phase.state_label !== phase.label
            ? `<div class="panel-type">${escapeHtml(phase.state_label)}</div>`
            : ""
      }
      ${badges.length ? `<div class="panel-section">${badges.join(" ")}</div>` : ""}
      <div class="panel-section">
        <h4>Description</h4>
        <p>${escapeHtml(phase.comment || phase.blurb || "n/a")}</p>
      </div>
      ${
        phase.conditioning_mode
          ? `<div class="panel-section"><h4>Conditioning mode</h4><p>${escapeHtml(phase.conditioning_mode.replace(/_/g, " "))}</p></div>`
          : ""
      }
      <div class="panel-section">
        <h4>Transition in: affordance misuse</h4>
        <ul>${transInHtml}</ul>
      </div>
      <div class="panel-section">
        <h4>Transition out: affordance misuse</h4>
        <ul>${transOutHtml}</ul>
      </div>
      <div class="panel-section">
        <h4>Instantiated case</h4>
        <p>${escapeHtml(payload.citation || "")}</p>
      </div>
    `;
    panelEl.classList.add("open");
    backdropEl.classList.add("open");
  }

  function closePanel() {
    panelEl.classList.remove("open");
    backdropEl.classList.remove("open");
  }

  function renderLegend(payload, el) {
    if (!el) return;
    const used = new Set();
    (payload.transitions || []).forEach((t) => {
      if (t.affordance_name) used.add(t.affordance_name);
    });
    const items = Array.from(used)
      .map(
        (name) =>
          `<span class="legend-item"><span class="dot" style="background:${affordanceColor(name)}"></span>${escapeHtml(
            (payload.transitions.find((t) => t.affordance_name === name) || {}).affordance_label || name
          )}</span>`
      )
      .join("");
    el.innerHTML = `
      <span class="legend-title">Affordance →</span>
      ${items}
      <span class="legend-item legend-backbone"><span class="dot"></span>Backbone phase</span>
    `;
  }

  function renderMachine(payload, host, instanceId) {
    if (!host || !payload) return;
    host.innerHTML = "";

    const phases = payload.phases || [];
    const accent = payload.accent || "#4a7a9b";
    const width = LEFT_PAD + phases.length * COL_W + 48;
    const height = TOP_PAD + ROW_H + 36;
    const cy = TOP_PAD + ROW_H / 2;
    const uid = instanceId || `m${Math.random().toString(36).slice(2, 8)}`;
    const arrowId = `typ-machine-arrow-${uid}`;
    const railClipId = `typ-machine-left-rail-clip-${uid}`;

    const svg = d3
      .select(host)
      .append("svg")
      .attr("class", "typ-machine-svg")
      .attr("width", width)
      .attr("height", height)
      .attr("viewBox", `0 0 ${width} ${height}`);

    const defs = svg.append("defs");
    defs
      .append("marker")
      .attr("id", arrowId)
      .attr("viewBox", "0 -4 8 8")
      .attr("refX", 7)
      .attr("refY", 0)
      .attr("markerWidth", 5)
      .attr("markerHeight", 5)
      .attr("orient", "auto")
      .append("path")
      .attr("d", "M0,-4L8,0L0,4")
      .attr("fill", "#8a9aa6");

    // Keep row metadata text strictly in the left rail so it never
    // bleeds under phase cards when citations are long.
    defs
      .append("clipPath")
      .attr("id", railClipId)
      .append("rect")
      .attr("x", 18)
      .attr("y", TOP_PAD - 8)
      .attr("width", Math.max(0, LEFT_PAD - 28))
      .attr("height", ROW_H + 20);

    phases.forEach((phase, i) => {
      if (!phase.is_fundamental) return;
      svg
        .append("rect")
        .attr("class", "fundamental-col")
        .attr("x", LEFT_PAD + i * COL_W - 4)
        .attr("y", TOP_PAD - 10)
        .attr("width", COL_W - 12)
        .attr("height", ROW_H)
        .attr("rx", 6);
    });

    phases.forEach((phase, i) => {
      svg
        .append("text")
        .attr("class", "col-header")
        .attr("x", LEFT_PAD + i * COL_W + NODE_W / 2)
        .attr("y", TOP_PAD - 14)
        .attr("text-anchor", "middle")
        .text(
          phase.short_type === "Phase"
            ? "Variant"
            : String(phase.short_type || phase.label || "").replace(/Phase$/, "")
        );
    });

    const gRow = svg.append("g").attr("class", "machine-row");

    gRow
      .append("rect")
      .attr("x", 10)
      .attr("y", cy - 36)
      .attr("width", 4)
      .attr("height", 72)
      .attr("fill", accent)
      .attr("rx", 2);

    gRow
      .append("text")
      .attr("class", "row-modality")
      .attr("x", 22)
      .attr("y", cy - 10)
      .attr("fill", accent)
      .attr("clip-path", `url(#${railClipId})`)
      .text(payload.modality_label || "CASE");

    const cite = shortCourtCitation(payload.citation || "");
    const citeShort = cite.length > 52 ? `${cite.slice(0, 50)}…` : cite;
    gRow
      .append("text")
      .attr("class", "row-citation")
      .attr("x", 22)
      .attr("y", cy + 8)
      .attr("clip-path", `url(#${railClipId})`)
      .text(citeShort);

    const laid = phases.map((phase, i) => ({
      phase,
      x: LEFT_PAD + i * COL_W,
    }));

    const edgesG = gRow.append("g").attr("class", "edges");
    for (let i = 0; i < laid.length - 1; i++) {
      const a = laid[i];
      const b = laid[i + 1];
      const x1 = a.x + NODE_W;
      const y1 = cy;
      const x2 = b.x;
      const y2 = cy;
      const trans = (payload.transitions || [])[i] || {};
      const aff = trans.affordance_name || "";
      const color = affordanceColor(aff);
      const pathD = arrowPath(x1, y1, x2, y2);

      edgesG
        .append("path")
        .attr("d", pathD)
        .attr("fill", "none")
        .attr("stroke", color)
        .attr("stroke-width", 2)
        .attr("marker-end", `url(#${arrowId})`);

      const lx = (x1 + x2) / 2;
      const label = trans.affordance_label || "";
      if (label) {
        const edgeClipId = `edge-label-clip-${uid}-${i}`;
        const gapWidth = Math.max(0, x2 - x1);
        defs
          .append("clipPath")
          .attr("id", edgeClipId)
          .append("rect")
          .attr("x", x1 + 2)
          .attr("y", cy - 8)
          .attr("width", Math.max(0, gapWidth - 4))
          .attr("height", 20);

        edgesG
          .append("text")
          .attr("class", "edge-label")
          .attr("x", lx)
          .attr("y", cy + 10)
          .attr("text-anchor", "middle")
          .attr("fill", "rgba(28, 27, 25, 0.35)")
          .attr("clip-path", `url(#${edgeClipId})`)
          .text(label);
      }

      addFlowDots(edgesG, pathD, color);
    }

    const nodesG = gRow.append("g").attr("class", "nodes");
    laid.forEach(({ phase, x }) => {
      const nx = x;
      const ny = cy - NODE_H / 2;

      const ng = nodesG
        .append("g")
        .attr("class", "stage-node")
        .attr("transform", `translate(${nx},${ny})`)
        .on("click", (event) => {
          event.stopPropagation();
          openPanel(phase, payload);
        });

      ng
        .append("rect")
        .attr("width", NODE_W)
        .attr("height", NODE_H)
        .attr("rx", 8)
        .attr("fill", nodeFill(phase))
        .attr("stroke", nodeStroke(phase, accent))
        .attr("stroke-width", 1.5);

      // Card eyebrow: human short name only when it differs from the serif title.
      // Never paint prefixed ontology ids (ex:InitialAccess) into the card face.
      const eyebrow =
        phase.short_type &&
        phase.short_type !== "Phase" &&
        phase.short_type !== phase.label
          ? phase.short_type
          : "";
      const titleY = eyebrow ? 40 : 28;
      if (eyebrow) {
        ng
          .append("text")
          .attr("class", "node-class")
          .attr("x", 10)
          .attr("y", 18)
          .attr("fill", nodeMetaColor(phase, accent))
          .text(eyebrow);
      }

      if (phase.is_fundamental) {
        ng
          .append("text")
          .attr("class", "badge-fundamental")
          .attr("x", NODE_W - 8)
          .attr("y", 16)
          .attr("text-anchor", "end")
          .attr("fill", "rgba(74, 93, 107, 0.95)")
          .text("B");
      } else if (phase.is_variant) {
        ng
          .append("text")
          .attr("class", "badge-variant")
          .attr("x", NODE_W - 8)
          .attr("y", 16)
          .attr("text-anchor", "end")
          .attr("fill", "rgba(107, 91, 74, 0.82)")
          .text("V");
      }

      const titleLines = wrapLabel(phase.label, 22);
      titleLines.forEach((line, li) => {
        ng
          .append("text")
          .attr("class", "node-label")
          .attr("x", 10)
          .attr("y", titleY + li * 14)
          .attr("fill", nodeTextColor(phase))
          .text(line);
      });

      const blurbLines = wrapLabel(phase.blurb, 28);
      blurbLines.slice(0, 2).forEach((line, li) => {
        ng
          .append("text")
          .attr("class", "node-blurb")
          .attr("x", 10)
          .attr("y", titleY + 38 + li * 11)
          .attr("fill", nodeBlurbColor(phase))
          .text(line);
      });
    });
  }

  function showD3Fallback(wraps) {
    wraps.forEach((wrap) => {
      const canvasHost = wrap.querySelector(".typ-machine-canvas");
      if (!canvasHost || canvasHost.querySelector("svg")) return;
      canvasHost.innerHTML =
        '<p class="typ-machine-fallback">State machine could not render (graphics library failed to load). Refresh, or check that /viz-assets/d3.v7.min.js is reachable.</p>';
    });
  }

  function init(attempt) {
    const wraps = document.querySelectorAll(".typ-machine-wrap");
    if (!wraps.length) return;
    if (typeof d3 === "undefined") {
      const n = typeof attempt === "number" ? attempt : 0;
      if (n < 40) {
        window.setTimeout(() => init(n + 1), 50);
        return;
      }
      console.error("D3 required for typology state machine");
      showD3Fallback(wraps);
      return;
    }

    panelEl = document.getElementById("typ-machine-panel");
    backdropEl = document.getElementById("typ-machine-backdrop");
    if (!panelEl || !backdropEl) return;

    backdropEl.addEventListener("click", closePanel);
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") closePanel();
    });

    wraps.forEach((wrap, idx) => {
      const embedded = wrap.querySelector(".typ-machine-payload");
      if (!embedded || !embedded.textContent.trim()) return;

      let payload;
      try {
        payload = JSON.parse(embedded.textContent);
      } catch (err) {
        console.error("Invalid typology machine payload", err);
        return;
      }

      const canvasHost = wrap.querySelector(".typ-machine-canvas");
      const legendEl = wrap.querySelector(".typ-machine-legend");
      renderLegend(payload, legendEl);
      renderMachine(payload, canvasHost, `i${idx}`);
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => init(0));
  } else {
    init(0);
  }
})();
