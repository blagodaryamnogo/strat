// Star-histogram entry. Checks hand-typed Amazon histograms with the same rules as
// pipeline/histograms.py and produces data/raw/histograms/star_histograms.csv.
// The preview NPS shown here is computed only from the typed values and is labelled as a
// preview; report numbers still come from analysis.json after the pipeline is re-run.
(() => {
  const $h = (s) => document.querySelector(s);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const STARS = [5, 4, 3, 2, 1];
  const PCT = STARS.map((s) => `pct_${s}`);
  const FIELDS = [...PCT, "total_ratings", "average_rating", "recorded_on", "recorded_by", "notes"];
  const REQUIRED = [...PCT, "total_ratings", "recorded_on", "recorded_by"];
  const COLS = ["competitor", "asin", "listing_url", ...FIELDS];
  const DRAFT_KEY = "srs-histogram-draft-v1";
  let products = [], rows = {}, db = null, userApi = null;

  const store = {
    get() { try { return JSON.parse(localStorage.getItem(DRAFT_KEY) || "{}"); } catch { return {}; } },
    set(v) { try { localStorage.setItem(DRAFT_KEY, JSON.stringify(v)); } catch { /* storage unavailable: draft not kept */ } },
  };
  const int = (v) => { v = String(v ?? "").trim().replace(/,/g, "").replace(/%$/, ""); return /^\d+$/.test(v) ? parseInt(v, 10) : null; };
  const roundHalfAway = (x) => Math.floor(Math.abs(x) + 0.5) * (x >= 0 ? 1 : -1);
  const sgn = (v) => (v > 0 ? "+" : "") + v;
  const today = () => { const d = new Date(); return new Date(d - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10); };

  // Mirrors pipeline/histograms.py load() + score().
  function check(r) {
    if (!REQUIRED.some((k) => String(r[k] ?? "").trim())) return { state: "empty" };
    const missing = REQUIRED.filter((k) => !String(r[k] ?? "").trim());
    if (missing.length) return { state: "error", msg: "Missing: " + missing.map(label).join(", ") };
    const pct = Object.fromEntries(STARS.map((s) => [s, int(r[`pct_${s}`])]));
    const total = int(r.total_ratings);
    const bad = STARS.filter((s) => pct[s] == null || pct[s] > 100).map((s) => `${s}★`).concat(total ? [] : ["total ratings"]);
    if (bad.length) return { state: "error", msg: "Not a whole number in range: " + bad.join(", ") };
    const sum = STARS.reduce((a, s) => a + pct[s], 0);
    if (sum < 97 || sum > 103) return { state: "error", msg: `Percentages sum to ${sum}; expected about 100 (check for a typo)` };
    const d = String(r.recorded_on).trim();
    if (!/^\d{4}-\d{2}-\d{2}$/.test(d) || isNaN(Date.parse(d))) return { state: "error", msg: "Recorded on must be a date (YYYY-MM-DD)" };
    const sh = Object.fromEntries(STARS.map((s) => [s, (pct[s] / sum) * 100]));
    const det = sh[3] + sh[2] + sh[1];
    const avg = String(r.average_rating ?? "").trim();
    return { state: "ok", nps: roundHalfAway(sh[5] - det), alt: roundHalfAway(sh[5] + sh[4] - det), total,
             note: avg && !/^\d(\.\d)?$/.test(avg) ? "Average ignored (use a form like 4.7)." : "" };
  }
  function label(k) {
    return { total_ratings: "total ratings", recorded_on: "recorded on", recorded_by: "recorded by" }[k] || k.replace("pct_", "") + "★";
  }

  function csvCell(v) { v = String(v ?? ""); return /[",\n\r]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v; }
  function csv() {
    const lines = [COLS.join(",")];
    for (const p of products) {
      const r = rows[p.asin];
      lines.push([p.competitor, p.asin, p.listing_url, ...FIELDS.map((k) => (k === "total_ratings" ? String(r[k] ?? "").replace(/,/g, "") : r[k]))].map(csvCell).join(","));
    }
    return lines.join("\n") + "\n";
  }

  function fromCommitted(c) {
    const h = c.histogram;
    if (!h) return {};
    return { ...Object.fromEntries(STARS.map((s) => [`pct_${s}`, String(h.pct[s])])), total_ratings: String(h.total_ratings),
             average_rating: h.average_rating == null ? "" : String(h.average_rating), recorded_on: h.recorded_on,
             recorded_by: h.recorded_by, notes: h.notes || "" };
  }

  function render() {
    $h("#hist-table tbody").innerHTML = products.map((p) => `<tr data-asin="${esc(p.asin)}">
      <td><b>${esc(p.competitor)}</b><br><a href="${esc(p.listing_url)}" target="_blank" rel="noopener">Open listing ↗</a> <span class="muted">${esc(p.asin)}</span></td>
      ${STARS.map((s) => `<td class="star" data-l="${s}★ %"><input class="pct" inputmode="numeric" data-k="pct_${s}" aria-label="${esc(p.competitor)} ${s}-star percent" placeholder="%"></td>`).join("")}
      <td data-l="Total ratings"><input class="num" inputmode="numeric" data-k="total_ratings" aria-label="${esc(p.competitor)} total ratings" placeholder="e.g. 12345"></td>
      <td data-l="Average"><input class="avg" inputmode="decimal" data-k="average_rating" aria-label="${esc(p.competitor)} average rating" placeholder="4.7"></td>
      <td data-l="Recorded on"><input type="date" data-k="recorded_on" aria-label="${esc(p.competitor)} recorded on"></td>
      <td data-l="Recorded by"><input class="who" data-k="recorded_by" aria-label="${esc(p.competitor)} recorded by" placeholder="initials"></td>
      <td data-l="Notes"><input class="note" data-k="notes" aria-label="${esc(p.competitor)} notes" placeholder="optional"></td>
      <td class="hist-status" aria-live="polite"></td></tr>`).join("");
    document.querySelectorAll("#hist-table tbody tr").forEach((tr) => {
      const r = rows[tr.dataset.asin];
      tr.querySelectorAll("input").forEach((inp) => {
        inp.value = r[inp.dataset.k] ?? "";
        inp.addEventListener("input", () => {
          r[inp.dataset.k] = inp.value;
          if (inp.dataset.k !== "recorded_on" && !r.recorded_on && PCT.includes(inp.dataset.k)) { r.recorded_on = today(); tr.querySelector("[data-k=recorded_on]").value = r.recorded_on; }
          if (inp.dataset.k !== "recorded_by" && !r.recorded_by && store.get()._who && PCT.includes(inp.dataset.k)) { r.recorded_by = store.get()._who; tr.querySelector("[data-k=recorded_by]").value = r.recorded_by; }
          refresh();
        });
      });
    });
    refresh();
  }

  function refresh() {
    let ok = 0;
    for (const tr of document.querySelectorAll("#hist-table tbody tr")) {
      const res = check(rows[tr.dataset.asin]);
      const cell = tr.querySelector(".hist-status");
      cell.className = "hist-status " + res.state;
      if (res.state === "ok") {
        ok++;
        cell.innerHTML = `<b data-preview>${sgn(res.nps)}</b> <span class="muted">preview NPS (alt. ${sgn(res.alt)})</span>${res.note ? `<br><span class="muted">${esc(res.note)}</span>` : ""}`;
      } else cell.innerHTML = res.state === "empty" ? `<span class="muted">Not entered</span>` : `<span class="err">${esc(res.msg)}</span>`;
    }
    $h("#hist-summary").innerHTML = `<b>${ok} of ${products.length}</b> rows valid. ` + (ok === products.length
      ? "All five are ready: once applied, every product is scored from its histogram."
      : "The report switches to histogram NPS only when all five are valid; until then it stays on the written-review sample.");
    $h("#hist-csv").value = csv();
    const draft = Object.fromEntries(products.map((p) => [p.asin, rows[p.asin]]));
    const who = products.map((p) => rows[p.asin].recorded_by).find((v) => v && v.trim());
    store.set({ ...draft, _who: who || store.get()._who || "" });
  }

  function say(msg, bad) { const m = $h("#hist-msg"); m.textContent = msg; m.className = bad ? "err" : "muted"; }

  async function download() {
    const data = csv();
    const dl = window.claude ? await window.claude.use("downloads").catch(() => null) : null;
    if (dl) {
      try { await dl.save({ filename: "star_histograms.csv", data }); say("Saved star_histograms.csv."); }
      catch (e) { say(e && e.code === "declined" ? "Download cancelled." : "Download is not available here; use Copy CSV instead.", e && e.code !== "declined"); }
      return;
    }
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([data], { type: "text/csv" }));
    a.download = "star_histograms.csv";
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
    say("Downloaded star_histograms.csv. Replace data/raw/histograms/star_histograms.csv with it and run make all.");
  }

  async function copy() {
    const t = $h("#hist-csv");
    try { await navigator.clipboard.writeText(t.value); say("CSV copied."); }
    catch { t.closest("details").open = true; t.select(); say("Copy blocked by the browser: the CSV is selected below; press Ctrl/Cmd+C.", true); }
  }

  // claude.ai preview only: shared store Claude reads to apply the entries to the repository.
  async function saveForClaude() {
    const valid = products.filter((p) => check(rows[p.asin]).state === "ok");
    if (!valid.length) { say("No valid rows to save yet.", true); return; }
    const uid = userApi ? await userApi.id().catch(() => null) : null;
    try {
      for (const p of valid) {
        const r = rows[p.asin];
        await db.doc(`histograms/${p.asin}`).set({ asin: p.asin, competitor: p.competitor, ...Object.fromEntries(FIELDS.map((k) => [k, String(r[k] ?? "")])),
                                                   saved_at: new Date().toISOString(), saved_by_id: uid || "" });
      }
      const skipped = products.length - valid.length;
      say(`Saved ${valid.length} valid row${valid.length > 1 ? "s" : ""} for Claude` + (skipped ? ` (${skipped} not saved: not entered or invalid)` : "") +
          ". Ask Claude to apply the saved histograms.");
    } catch (e) {
      say(e && e.code === "invalid_argument" ? "You don't have permission to save entries on this page." : "Saving failed; try again in a moment.", true);
    }
  }

  async function connectClaude() {
    if (!window.claude) return;
    db = await window.claude.use("db").catch(() => null);
    if (!db) return;
    userApi = await window.claude.use("user").catch(() => null);
    $h("#hist-save").hidden = false;
    $h("#hist-save").addEventListener("click", saveForClaude);
    try {
      let loaded = 0;
      for (const p of products) {
        const snap = await db.doc(`histograms/${p.asin}`).get();
        if (snap.exists) { const d = snap.data(); rows[p.asin] = Object.fromEntries(FIELDS.map((k) => [k, String(d[k] ?? "")])); loaded++; }
      }
      if (loaded) { render(); say(`Loaded ${loaded} saved row${loaded > 1 ? "s" : ""} from this page's shared entries.`); }
    } catch { /* keep local values */ }
  }

  fetch("analysis.json").then((r) => r.json()).then((a) => {
    const draft = store.get();
    products = a.competitors.map((c) => ({ competitor: c.competitor, asin: c.asin, listing_url: c.listing_url }))
      .sort((x, y) => x.competitor.localeCompare(y.competitor));
    for (const c of a.competitors) {
      const blank = Object.fromEntries(FIELDS.map((k) => [k, ""]));
      rows[c.asin] = { ...blank, ...fromCommitted(c), ...(draft[c.asin] || {}) };
    }
    $h("#hist-applied").textContent = a.primary_metric === "histogram"
      ? "Applied: the report currently uses histogram NPS from the committed file."
      : `Applied: ${a.competitors.filter((c) => c.histogram).length} of ${a.competitors.length} histograms are in the committed file; the report uses the written-review sample.`;
    render();
    $h("#hist-download").addEventListener("click", download);
    $h("#hist-copy").addEventListener("click", copy);
    $h("#hist-clear").addEventListener("click", () => {
      if (!confirm("Clear all typed values on this page? (Committed and saved entries are not affected.)")) return;
      for (const p of products) rows[p.asin] = Object.fromEntries(FIELDS.map((k) => [k, ""]));
      render(); say("Cleared.");
    });
    connectClaude();
  }).catch(() => { $h("#hist-summary").textContent = "Could not load the product list."; });
})();
