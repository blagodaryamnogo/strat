// Renders analysis.json + reviews.json. No numbers are computed here except filtering/counting rows.
const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const pct = (v) => (v == null ? "N/A" : v.toFixed(1) + "%");
const sgn = (v) => (v == null ? "N/A" : (v > 0 ? "+" : "") + v);
const capNote = (c) => !c.capped_stars || !c.capped_stars.length ? "" : c.comparable === false
  ? `<br><span class="muted"><b>Not ranked:</b> ${c.capped_stars.join("/")}★ buckets capped at retrieval; star mix reflects the cap, not customers</span>`
  : `<br><span class="muted">${c.capped_stars.join("/")}★ bucket capped at retrieval: NPS is a lower bound</span>`;
const bucket = (r) => (r === 5 ? "promoter" : r === 4 ? "passive" : "detractor");
let A, R, sortKey = "nps", sortDir = -1, method = "baseline";

Promise.all([fetch("analysis.json").then((r) => r.json()), fetch("reviews.json").then((r) => r.json()), fetch("startup.html").then((r) => r.text())])
  .then(([a, r, startup]) => { A = a; R = r; init(startup); })
  .catch((e) => { $("#status").innerHTML = `<div class="alert">Failed to load data: ${esc(e)}</div>`; });

function init(startup) {
  if (A.status !== "ok")
    $("#status").innerHTML = `<div class="alert"><b>Data status: ${esc(A.status)}.</b> Amazon US review collection was blocked in the build environment (HTTP 403 for www.woot.com). No reviews were fabricated; unscored values show N/A. See the collection log in the repository.</div>`;
  const scored = A.competitors.filter((c) => c.nps != null);
  const top = scored[0];
  $("#kpis").innerHTML = [
    ["Competitors", A.competitors.length], ["Reviews analyzed", A.total_reviews],
    ["Highest baseline NPS", top ? `${sgn(top.nps)} <small>${esc(top.competitor)}</small>` : "N/A"],
    ["Wedge status", esc(A.wedge.status.replace(/_/g, " "))],
  ].map(([k, v]) => `<div class="card"><b>${v}</b><span>${k}</span></div>`).join("");
  $("#source-line").textContent = `Source: Amazon US written reviews via Woot's public review endpoint (mrlong0129/amazon-review-scraper). Analysis generated ${A.generated_at.slice(0, 10)}. ${A.comparability_note}`;
  $("#vol-note").textContent = "X-axis: " + A.volume_metric + ".";
  $("#limits").innerHTML = (A.limitations || []).map((l) => `<li>${esc(l)}</li>`).join("");
  $("#startup").innerHTML = startup;
  renderTable(); renderSens(); initExplorer();
  document.querySelectorAll("#comp-table th[data-k]").forEach((th) => th.addEventListener("click", () => {
    sortDir = sortKey === th.dataset.k ? -sortDir : -1; sortKey = th.dataset.k; renderTable();
  }));
  document.querySelectorAll(".toggle button").forEach((b) => b.addEventListener("click", () => { method = b.dataset.m; renderSens(); }));
}

function renderTable() {
  const rows = [...A.competitors].sort((a, b) => {
    const x = a[sortKey], y = b[sortKey];
    if (x == null) return 1; if (y == null) return -1;
    return (x > y ? 1 : x < y ? -1 : 0) * sortDir;
  });
  $("#comp-table tbody").innerHTML = rows.map((c) => `<tr data-c="${esc(c.competitor)}">
    <td>${esc(c.competitor)}</td><td>${esc(c.product_name)}<br><span class="muted">ASIN ${esc(c.asin)}</span>${capNote(c)}</td><td class="n">${c.n}</td>
    <td class="n">${pct(c.promoter_pct)}</td><td class="n">${pct(c.passive_pct)}</td><td class="n">${pct(c.detractor_pct)}</td>
    <td class="n" data-nps><b>${sgn(c.nps)}</b></td><td class="n">${sgn(c.alt_nps)}</td>
    <td><a href="${esc(c.listing_url)}" target="_blank" rel="noopener">Amazon listing</a></td></tr>`).join("");
  document.querySelectorAll("#comp-table tbody tr").forEach((tr) => tr.addEventListener("click", (e) => {
    if (e.target.tagName === "A") return;
    const c = A.competitors.find((x) => x.competitor === tr.dataset.c), s = c.star_counts;
    $("#calc").classList.add("show");
    $("#calc").textContent = c.n === 0 ? `${c.competitor}: 0 valid reviews -> NPS = N/A (not zero).`
      : `${c.competitor} (${c.asin})  n = ${c.n}\nStars 5/4/3/2/1: ${s[5]}/${s[4]}/${s[3]}/${s[2]}/${s[1]}\n` +
        `Promoters ${c.promoters}/${c.n} = ${c.promoter_pct.toFixed(4)}%   Passives ${c.passives}/${c.n} = ${c.passive_pct.toFixed(4)}%   Detractors ${c.detractors}/${c.n} = ${c.detractor_pct.toFixed(4)}%\n` +
        `Baseline NPS = ${c.promoter_pct.toFixed(4)} - ${c.detractor_pct.toFixed(4)} = ${c.nps_exact.toFixed(4)} -> ${sgn(c.nps)}   (95% CI ${c.ci95_low.toFixed(1)} to ${c.ci95_high.toFixed(1)})\n` +
        `Alternative NPS = ${c.alt_nps_exact.toFixed(4)} -> ${sgn(c.alt_nps)}   change = ${c.delta_exact.toFixed(4)} = 4-star share` +
        (c.below_min_n ? `\nNote: n below the ${A.min_n_target}-review target.` : "") +
        (c.capped_stars && c.capped_stars.length ? `\nRetrieval cap hit in ${c.capped_stars.join("/")}★ bucket(s): ${c.comparable === false ? "NPS not comparable, not ranked." : "NPS is a lower bound."}` : "");
  }));
}

function renderSens() {
  document.querySelectorAll(".toggle button").forEach((b) => b.classList.toggle("on", b.dataset.m === method));
  $("#chart-sens").src = method === "baseline" ? "charts/nps_baseline.svg" : "charts/nps_alternative.svg";
  const alt = method === "alternative";
  $("#sens-table tbody").innerHTML = A.competitors.map((c) => `<tr><td>${esc(c.competitor)}</td>
    <td class="n ${alt ? "" : "hl"}">${sgn(c.nps)}</td><td class="n ${alt ? "hl" : ""}">${sgn(c.alt_nps)}</td>
    <td class="n">${c.delta_exact == null ? "N/A" : "+" + c.delta_exact.toFixed(1)}</td><td class="n">${pct(c.four_star_pct)}</td>
    <td class="n">${c.rank ?? "–"} → ${c.alt_rank ?? "–"}${c.rank_change ? ` <b>(${c.rank_change > 0 ? "up" : "down"} ${Math.abs(c.rank_change)})</b>` : ""}</td></tr>`).join("");
}

function reviewCard(r, label) {
  return `<div class="${label ? "quote" : "review"}">${label ? `<b>${label}</b><br>` : ""}<div class="meta">${esc(r.competitor)} · ${r.rating}★ (${bucket(r.rating)}) · ${esc(r.review_date || "date n/a")} · ${esc(r.author || "author n/a")}${r.verified_purchase ? " · Verified Purchase" : ""} · id ${esc(r.review_id)}</div>
    ${r.title ? `<b>${esc(r.title)}</b><br>` : ""}${esc(r.review_text || "(no text)")}
    <div class="meta">Source: ${esc(r.collection_source)} · ${esc(r.verification_status.replace(/_/g, " "))} · <a href="${esc(r.direct_review_url || r.source_product_url)}" target="_blank" rel="noopener">${r.direct_review_url ? "review link" : "product page (no review permalink available)"}</a></div></div>`;
}

function initExplorer() {
  const byId = Object.fromEntries(R.map((r) => [r.review_id, r]));
  const ex = A.excerpts;
  $("#excerpts").innerHTML = "<h3>Representative excerpts</h3>" + [["5★ Promoter", ex.promoter_5], ["4★ Passive", ex.passive_4], ["1–3★ Detractor", ex.detractor_1_3]]
    .map(([l, id]) => (id ? reviewCard(byId[id], l) : `<div class="quote"><b>${l}</b>: no genuine review available — none shown.</div>`)).join("");
  A.competitors.forEach((c) => $("#f-comp").insertAdjacentHTML("beforeend", `<option value="${esc(c.competitor)}">${esc(c.competitor)} — ${esc(c.product_name)}</option>`));
  A.themes.forEach((t, i) => $("#f-theme").insertAdjacentHTML("beforeend", `<option value="${i}">${esc(t.theme)}</option>`));
  document.querySelectorAll(".filters select, .filters input").forEach((el) => el.addEventListener("input", renderReviews));
  renderReviews();
}

function renderReviews() {
  const comp = $("#f-comp").value, star = $("#f-star").value, b = $("#f-bucket").value, from = $("#f-from").value, to = $("#f-to").value, ti = $("#f-theme").value;
  const rx = ti === "" ? null : new RegExp(A.themes[+ti].pattern, "i");
  const rows = R.filter((r) => (!comp || r.competitor === comp) && (!star || r.rating === +star) && (!b || bucket(r.rating) === b) &&
    (!from || (r.review_date && r.review_date >= from)) && (!to || (r.review_date && r.review_date <= to)) &&
    (!rx || rx.test(`${r.title || ""} ${r.review_text || ""}`)));
  $("#r-count").textContent = `${rows.length} of ${R.length} stored reviews` + (rows.length > 200 ? " (first 200 shown)" : "");
  $("#reviews").innerHTML = rows.length ? rows.slice(0, 200).map((r) => reviewCard(r)).join("") : `<p class="muted">No stored reviews match.</p>`;
}
