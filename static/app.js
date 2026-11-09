"use strict";
// 화면 조각을 넣을 때 빈 칸(null·false)은 건너뛴다(그대로 넣으면 "null" 글자가 보임)
for (const m of ["append", "replaceChildren"]) {
  const orig = Element.prototype[m];
  Element.prototype[m] = function (...kids) { return orig.apply(this, kids.flat(Infinity).filter(k => k !== null && k !== undefined && k !== false)); };
}
let S = null, GO = null, CUR = null, PHOTOS = [], LASTINC = null, USEWX = false, MSGS = null, ONLYTODO = false;
const LV = { bad: "작업 전 조치 완료", warn: "작업 중 관리", ok: "현재 조치 유지" };

async function load() {
  S = await api("GET", "/api/state");
  renderDash(); renderList(); renderInc(); renderLib(); fillTasks();
  if (FLOW.step === 1) renderCatalog();
}

function basisChip(b) {
  if (!b) return null;
  return el("span", { class: "chip", title: b.text, onclick: () => modal(`${b.reg} ${b.label}`, el("pre", { class: "doc" }, b.text),
    el("p", { class: "small muted" }, `파일: ${b.file} · ${b.loc}`)) }, `${shortName(b.reg)} ${b.label}`);
}

// ------------------------------------------------------------ 현황
function renderDash() {
  const d = S.dash, box = $("#tab-dash");
  box.innerHTML = "";
  box.append(el("div", { class: "panel" }, el("h2", {}, "안전 현황"),
    el("div", { class: "kpis" },
      el("div", { class: "stat" }, el("b", {}, d.assessments), el("span", { class: "lbl" }, "위험성평가")),
      el("div", { class: "stat bad" }, el("b", {}, d.n_open_high), el("span", { class: "lbl" }, "작업 전 끝내야 할 조치(미완료)")),
      el("div", { class: "stat warn" }, el("b", {}, d.overdue.length), el("span", { class: "lbl" }, "기한 지난 조치")),
      el("div", { class: "stat warn" }, el("b", {}, d.reassess.length), el("span", { class: "lbl" }, "수시평가 필요"))),
    el("p", { class: "small muted", style: { marginTop: "10px" } }, `기관 자료: 위험요인 ${S.kb.hazards}종 · 평가 대상 작업 ${S.kb.tasks}개 · 아차사고 ${S.kb.incidents}건 · 규정 ${S.kb.reg || "없음"}`)));
  box.append(el("div", { id: "brief" }));
  renderBrief();
  box.append(el("div", { class: "panel", id: "msgs" }, el("div", { class: "row" }, el("h3", { style: { flex: 1, margin: 0 } }, "오늘의 긴급재난문자"),
      el("button", { class: "small", id: "msgs-btn", onclick: e => renderMsgs(e.currentTarget) }, MSGS ? "다시 확인" : "재난문자 확인")),
    el("p", { class: "small muted" }, "우리 지역에 온 재난문자(폭염·강풍·호우 등)와 겹치는 위험요인이 있는 평가를 찾아, 수시평가 필요로 표시하고 작업 전 회의(TBM)에 넣습니다."),
    el("div", { id: "msgs-body" })));
  if (!d.assessments) {
    box.append(el("div", { class: "panel" }, el("p", {}, "아직 평가가 없습니다. '새 위험성평가'에서 작업을 적어 보세요."),
      el("button", { class: "primary", onclick: () => GO("new") }, "새 위험성평가")));
  }
  const P = S.periodic, ST = { ok: "ok", warn: "warn", bad: "bad" };
  if (P.tasks.length) {
    const done = P.tasks.filter(t => t.level === "ok").length;
    box.append(el("div", { class: "panel", id: "periodic" },
      el("div", { class: "row" }, el("h3", { style: { flex: 1, margin: 0 } }, `${P.year}년 정기 평가 대상 작업 ${done}/${P.tasks.length} 완료`),
        P.basis.basis ? basisChip(P.basis.basis) : null,
        el("button", { class: "small", onclick: () => download("/api/ledger-xlsx", {}) }, "평가 대장(엑셀)")),
      el("div", { class: "pbar", style: { marginTop: "10px" } }, el("i", { style: { width: (done / P.tasks.length * 100) + "%" } })),
      el("table", { class: "t", style: { marginTop: "10px" } }, el("tr", {}, ["시설", "작업", "작업 주기", "상태", "마지막 평가", ""].map(h => el("th", {}, h))),
        P.tasks.map((t, i) => el("tr", {}, el("td", {}, t.fac), el("td", {}, t.work), el("td", {}, t.cycle),
          el("td", {}, el("span", { class: "tag " + ST[t.level] }, t.state)), el("td", {}, t.date || "-"),
          el("td", {}, t.aid && t.level !== "bad" ? el("button", { class: "small", onclick: () => openA(t.aid) }, "열기")
            : el("button", { class: "small primary", onclick: () => startTask(i) }, "평가하기")))))));
  }
  if (d.reassess.length) box.append(el("div", { class: "panel" }, el("h3", {}, "수시평가 필요(같은 작업의 아차사고 또는 오늘 재난문자)"),
    d.reassess.map(r => el("div", { class: "finding" }, el("i", { class: "dot warn" }), el("div", {}, el("div", { class: "ttl" }, `${r.fac} · ${r.work}`),
      el("button", { class: "small", onclick: () => openA(r.id) }, "평가 열기"))))));
  if (d.open_high.length) box.append(el("div", { class: "panel" }, el("h3", {}, "작업 전에 끝내야 할 조치"),
    el("table", { class: "t" }, el("tr", {}, ["작업", "위험요인", "위험성", "조치", "담당", "기한"].map(h => el("th", {}, h))),
      d.open_high.map(x => el("tr", { style: { cursor: "pointer" }, onclick: () => openA(x.aid) }, el("td", {}, `${x.fac} · ${x.work}`), el("td", {}, x.item),
        el("td", {}, el("span", { class: "tag bad" }, x.R)), el("td", {}, x.measure), el("td", {}, x.owner || "-"),
        el("td", { style: { color: x.due && x.due < S.today ? "var(--bad)" : "" } }, x.due || "-"))))));
}

// ------------------------------------------------------------ 공공데이터: 날씨·재난문자
function srcTag(r) { return el("span", { class: "tag " + (r.live ? "info" : "gray") }, r.live ? r.source : "예시 자료"); }

function wxBox(w, extra) {
  const warns = w.warnings || w.active || [];
  return el("div", { class: "q wx" }, el("div", { class: "row" }, el("b", { style: { flex: 1 } }, `${w.region} 기상 · ${w.time}`), srcTag(w)),
    el("div", {}, `기온 ${w.ta}℃ · 습도 ${w.rh}% → 체감온도 `, el("b", {}, `${w.feel}℃`), el("span", { class: "small muted" }, " (기상청 여름철 체감온도 식)")),
    el("div", {}, "발표 중인 특보: ", warns.length ? warns.map(x => el("span", { class: "tag " + (x.level === "경보" ? "bad" : "warn"), style: { marginRight: "4px" } }, x.kind + x.level)) : "없음"),
    (w.stops || []).map(t => el("div", { style: { color: "var(--bad)", fontWeight: 700 } }, "작업 중지: " + t)),
    w.note ? el("div", { class: "small muted" }, w.note) : null, extra || null);
}

async function loadWx() {
  const btn = $("#n-wx");
  busy(btn, true, "불러오는 중");
  try {
    const w = await api("GET", "/api/feeds/weather");
    $("#n-temp").value = w.feel; USEWX = true;
    $("#n-wx-box").replaceChildren(wxBox(w, el("div", { class: "small muted" }, "평가를 만들면 이 체감온도와 특보로 작업 시작 여부를 함께 판정합니다.")));
  } finally { busy(btn, false); }
}

async function renderMsgs(btn) {
  busy(btn, true, "확인 중");
  try { MSGS = await api("GET", "/api/feeds/messages"); } finally { busy(btn, false); }
  const box = $("#msgs-body");
  const hits = MSGS.items.reduce((n, m) => n + m.hits.filter(h => !h.done).length, 0);
  box.replaceChildren(
    el("div", { class: "row small" }, el("span", { class: "muted", style: { flex: 1 } }, `${MSGS.region} · 오늘 ${MSGS.items.length}건`), srcTag(MSGS)),
    MSGS.note ? el("p", { class: "small muted" }, MSGS.note) : "",
    ...(MSGS.items.length ? MSGS.items.map(m => el("div", { class: "finding" }, el("i", { class: "dot " + (m.hits.length ? "warn" : "ok") }),
      el("div", { style: { flex: 1 } }, el("div", { class: "ttl" }, `${m.time} · ${m.kind || "안내"} ${m.step ? "· " + m.step : ""}`), el("div", {}, m.text),
        m.hits.length ? el("div", { class: "small", style: { marginTop: "4px" } }, "다시 볼 평가: ",
          m.hits.map(h => el("span", { class: "chip", style: { maxWidth: "none" }, onclick: () => openA(h.id) }, `${h.fac} · ${h.work} (${h.hazards.join(", ")})${h.done ? " · 수시평가 표시함" : ""}`)))
          : el("div", { class: "small muted" }, "겹치는 위험요인이 있는 평가가 없습니다.")))) : [el("div", { class: "empty" }, "오늘 이 지역에 온 재난문자가 없습니다.")]),
    hits ? el("button", { class: "primary", id: "msgs-apply", style: { marginTop: "10px" }, onclick: async () => {
      const r = await api("POST", "/api/feeds/messages/apply", {});
      toast(`${r.added}건의 평가에 '수시평가 필요'를 표시했습니다`);
      await load(); await renderMsgs($("#msgs-btn"));
    } }, `평가 ${hits}건에 수시평가 필요 표시하고 TBM에 넣기`) : "");
}

// ------------------------------------------------------------ 새 평가
function fillTasks() {
  const sel = $("#task-pick");
  sel.replaceChildren(el("option", { value: "" }, "직접 입력"), ...S.tasks.map((t, i) => el("option", { value: i }, `${t.fac} · ${t.work} (${t.cycle})`)));
}

function startTask(i) {
  $("#task-pick").value = i;
  $("#task-pick").dispatchEvent(new Event("change"));
  $("#n-text").value = "";
  GO("new");
}

async function runNew() {
  const btn = $("#n-run");
  busy(btn, true, "평가 만드는 중");
  try { await flowCreate(); flowGo(4); }
  finally { busy(btn, false); }
}

// ------------------------------------------------------------ 작업 고르기 → 위험요인 조회 → TBM → 위험성평가
const FLOW = { cat: null, work: null, sel: new Set(), aid: null, sig: "", mode: "risk", step: 1, n: 8, side: [] };
const KIND_ORDER = ["제거", "대체", "공학적", "관리적", "보호구"];
const KIND_CLS = { "제거": "k1", "대체": "k2", "공학적": "k3", "관리적": "k4", "보호구": "k5" };
function kindTag(k) { return k ? el("span", { class: "mk " + (KIND_CLS[k] || "k4"), title: "위험성 감소 우선순위: 제거 → 대체 → 공학적 → 관리적 → 보호구" }, k) : null; }
function hzName(c) { const h = S.hazards.find(x => x.code === c); return h ? h.name : c; }
function flowInputs() { return { fac: $("#n-fac").value, dept: $("#n-dept").value, work: $("#n-work").value, text: $("#n-text").value, temp: $("#n-temp").value }; }
function flowSig() { return JSON.stringify([flowInputs(), [...FLOW.sel].sort(), PHOTOS.map(p => p.name), USEWX]); }

function renderCatalog() {
  const box = $("#cat-box");
  if (!box || !S) return;
  const cats = [...new Set(S.catalog.map(c => c.cat))];
  if (!FLOW.cat) FLOW.cat = cats[0];
  const works = [...new Set(S.catalog.filter(c => c.cat === FLOW.cat).map(c => c.work))];
  if (!works.includes(FLOW.work)) FLOW.work = works[0];
  const cnt = cat => S.catalog.filter(c => c.cat === cat && FLOW.sel.has(c.id)).length;
  const wcnt = w => S.catalog.filter(c => c.work === w && FLOW.sel.has(c.id)).length;
  const steps = S.catalog.filter(c => c.work === FLOW.work);
  const picked = S.catalog.filter(c => FLOW.sel.has(c.id));
  box.replaceChildren(
    el("div", { class: "row" }, el("h3", { style: { margin: 0, flex: 1 } }, "작업 분류에서 단계 고르기"),
      S.catalog_demo ? el("span", { class: "tag warn", title: "기관 자료에 작업 분류 표가 없어 시연용 분류를 씁니다. '기준·자료'에서 기관 작업 분류 엑셀을 넣으면 바뀝니다." }, "시연용 분류") : null,
      el("span", { class: "small muted" }, `고른 단계 ${picked.length}개`),
      picked.length ? el("button", { class: "small", onclick: () => { FLOW.sel.clear(); FLOW.side = []; renderCatalog(); } }, "모두 풀기") : null),
    el("p", { class: "small muted" }, "분류 → 작업 → 단계 순서로 고르면 단계마다 기관 위험요인 목록의 위험 상황이 따라옵니다. 숫자는 그 단계의 위험 상황 수입니다."),
    el("div", { class: "cat-grid" },
      el("div", { class: "cat-col" }, el("div", { class: "cat-h" }, "분류"), cats.map(c => el("button", { class: "cat-it" + (c === FLOW.cat ? " on" : ""), onclick: () => { FLOW.cat = c; FLOW.work = null; renderCatalog(); } },
        el("span", {}, c), cnt(c) ? el("b", { class: "cat-n" }, cnt(c)) : null))),
      el("div", { class: "cat-col" }, el("div", { class: "cat-h" }, "작업"), works.map(w => el("button", { class: "cat-it" + (w === FLOW.work ? " on" : ""), onclick: () => { FLOW.work = w; renderCatalog(); } },
        el("span", {}, w), wcnt(w) ? el("b", { class: "cat-n" }, wcnt(w)) : null))),
      el("div", { class: "cat-col" }, el("div", { class: "cat-h" }, "단계"),
        steps.map(st => el("label", { class: "cat-step" + (FLOW.sel.has(st.id) ? " on" : "") },
          el("input", { type: "checkbox", checked: FLOW.sel.has(st.id), onchange: e => { e.target.checked ? FLOW.sel.add(st.id) : FLOW.sel.delete(st.id); renderCatalog(); } }),
          el("span", { style: { flex: 1 } }, st.step), el("span", { class: "tag " + (st.rows.length >= 2 ? "warn" : "gray") }, `위험 ${st.rows.length}`))),
        el("div", { class: "row small", style: { marginTop: "6px" } },
          el("button", { class: "small", onclick: () => { steps.forEach(st => FLOW.sel.add(st.id)); renderCatalog(); } }, "이 작업 단계 모두 고르기")))),
    picked.length ? el("div", { class: "cat-picked" }, el("span", { class: "small muted" }, "고른 단계: "),
      picked.map(st => el("span", { class: "chip" }, `${st.work} · ${st.step} `, el("button", { class: "x", "aria-label": `${st.step} 빼기`, onclick: () => { FLOW.sel.delete(st.id); renderCatalog(); } }, "×")))) : null,
    FLOW.side.length ? el("div", { class: "small muted", style: { marginTop: "6px" } }, "설명에 함께 나온 작업(고르지 않음): ",
      FLOW.side.map(w => el("span", { class: "chip", title: "눌러서 이 작업 단계도 고르기", onclick: () => { w.steps.forEach(x => FLOW.sel.add(x)); FLOW.side = FLOW.side.filter(v => v !== w); renderCatalog(); } }, `+ ${w.work} ('${w.words.join("', '")}')`))) : null);
}

async function flowMatch() {
  const btn = $("#n-match");
  busy(btn, true, "찾는 중");
  try {
    const r = await api("POST", "/api/catalog/match", { work: $("#n-work").value, text: $("#n-text").value });
    const main = r.works.find(w => w.primary);
    if (!main) { $("#n-match-out").textContent = "작업 분류에서 맞는 작업을 찾지 못했습니다. 아래에서 직접 고르세요."; return; }
    main.steps.forEach(x => FLOW.sel.add(x));
    const st = S.catalog.find(c => c.id === main.steps[0]);
    FLOW.cat = st.cat; FLOW.work = st.work; FLOW.side = r.works.filter(w => !w.primary);
    const c = r.conditions, cond = [c.height != null ? `높이 ${c.height}m` : null, c.alone ? "1인 작업" : null, c.people ? `${c.people}인 작업` : null,
      c.temp != null ? `체감온도 ${c.temp}℃` : null, c.open ? "운영 중" : null, c.outdoor ? "실외" : null].filter(Boolean);
    $("#n-match-out").textContent = `'${main.words.join("', '")}' → ${main.work} 단계 ${main.steps.length}개를 골랐습니다` + (cond.length ? ` · 읽은 조건: ${cond.join(", ")}` : "");
    renderCatalog();
  } finally { busy(btn, false); }
}

function setupMic() {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  const b = $("#n-mic");
  if (!SR || !b) return;
  b.hidden = false;
  b.addEventListener("click", () => {
    const r = new SR(); r.lang = "ko-KR"; r.interimResults = false;
    b.disabled = true; b.textContent = "듣는 중… 말씀하세요";
    r.onresult = e => { const t = e.results[0][0].transcript; $("#n-text").value = ($("#n-text").value + " " + t).trim(); flowMatch(); };
    r.onend = () => { b.disabled = false; b.textContent = "말로 적기"; };
    r.onerror = e => toast("음성 인식을 쓰지 못했습니다(" + e.error + "). 글로 적어 주세요.", true);
    r.start();
  });
}

function lookupRows() {
  const rows = [];
  for (const st of S.catalog.filter(c => FLOW.sel.has(c.id)))
    st.rows.forEach((r, i) => rows.push({ where: `${st.work} · ${st.step}`, first: i === 0, n: st.rows.length, situation: r.situation, code: r.code, src: st.src }));
  const have = new Set(rows.map(r => r.code));
  const t = `${$("#n-work").value} ${$("#n-text").value}`;
  for (const h of S.hazards) {
    const w = h.words.find(x => x && t.includes(x));
    if (w && !have.has(h.code)) { rows.push({ where: "작업 설명", first: true, n: 1, situation: `설명 속 '${w}'`, code: h.code, src: h.src }); have.add(h.code); }
  }
  return rows;
}

function renderLookup() {
  const box = $("#flow-2");
  const rows = lookupRows();
  const law = FLOW.mode === "law";
  const tb = el("table", { class: "t lookup" }, el("tr", {}, ["공종·단계", "위험요인", law ? "법령·규정 근거" : "감소대책(우선순위 순)"].map(h => el("th", {}, h))),
    rows.map(r => {
      const h = S.hazards.find(x => x.code === r.code);
      const R = h ? h.L * h.S : 0;
      return el("tr", {},
        r.first ? el("td", { rowspan: r.n, class: "lk-where" }, r.where) : null,
        el("td", {}, el("div", {}, r.situation), h ? el("div", { class: "small" }, el("span", { class: "tag " + (R >= S.kb.rules[0].value ? "bad" : R >= S.kb.rules[1].value ? "warn" : "ok") }, `${h.code} ${h.name}`), el("span", { class: "muted" }, ` 기본 ${h.L}×${h.S}=${R}`)) : el("span", { class: "tag warn" }, `${r.code}: 위험요인 목록에 없음`)),
        el("td", {}, !h ? "-" : law
          ? el("div", { class: "row small" }, el("span", {}, h.law || "-"), h.law ? el("button", { class: "small", onclick: e => toggleLaw(e.target, h.code) }, "법령 원문") : null, citeChips([h.src]))
          : el("ul", { class: "lk-m" }, h.measures.map(m => [kindOf(m), m]).sort((x, y) => KIND_ORDER.indexOf(x[0]) - KIND_ORDER.indexOf(y[0])).map(([k, m]) => el("li", {}, kindTag(k), " ", m)))));
    }));
  box.replaceChildren(el("div", { class: "panel" },
    el("div", { class: "row" }, el("h2", { style: { margin: 0, flex: 1 } }, "위험요인 조회"),
      el("div", { class: "seg", role: "group", "aria-label": "보기 기준" },
        el("button", { class: law ? "" : "on", "aria-pressed": !law, onclick: () => { FLOW.mode = "risk"; renderLookup(); } }, "위험 기준"),
        el("button", { class: law ? "on" : "", "aria-pressed": law, onclick: () => { FLOW.mode = "law"; renderLookup(); } }, "법령 기준"))),
    el("p", { class: "small muted" }, `고른 단계 ${FLOW.sel.size}개와 작업 설명에서 찾은 위험 상황 ${rows.length}건입니다. 가능성×중대성은 목록의 기본값이고, 높이·인원·아차사고 반영은 위험성평가에서 합니다.`),
    rows.length ? el("div", { class: "tbl-scroll" }, tb) : el("div", { class: "empty" }, "고른 단계가 없습니다. 1단계에서 작업 단계를 고르거나 작업 설명을 적어 주세요."),
    el("div", { class: "row", style: { marginTop: "12px" } }, el("button", { onclick: () => flowGo(1) }, "← 작업 고르기"), el("span", { style: { flex: 1 } }),
      el("button", { id: "to-tbm", class: "primary", disabled: !rows.length, onclick: async e => { busy(e.target, true, "평가 초안 만드는 중"); try { await flowCreate(); flowGo(3); } finally { busy(e.target, false); } } }, "TBM 일지로"),
      el("button", { disabled: !rows.length, onclick: async e => { busy(e.target, true, "평가 만드는 중"); try { await flowCreate(); flowGo(4); } finally { busy(e.target, false); } } }, "위험성평가로"))));
}

function kindOf(t) {  // 서버(assess.kind_of)와 같은 규칙: 조회 화면에서만 씀
  const R = [["공학적", /방호|덮개|환기|칸막이|라바콘|차단봉|방염포|잠금|차단 후|떨어짐 방지|난간|국소배기/], ["관리적", /금지/],
    ["보호구", /착용|보호구|마스크|보안경|보호안경|안전화|안전모/], ["제거", /제거|없애|치우|운영시간 외|나눠 운반/], ["대체", /대차|고소작업대|작업발판|A형 사다리|바꿔/]];
  for (const [k, rx] of R) if (rx.test(t)) return k;
  return "관리적";
}

async function flowCreate() {
  const sig = flowSig();
  if (FLOW.aid && FLOW.sig === sig) return;
  const i = flowInputs();
  const a = await api("POST", "/api/assess", Object.assign(i, { photos: PHOTOS, use_weather: USEWX, steps: [...FLOW.sel] }));
  FLOW.aid = a.id; FLOW.sig = sig;
  await load();
}

async function renderTBMSheet() {
  const box = $("#flow-3");
  const r = await api("GET", `/api/assess/${FLOW.aid}/tbm`);
  const sh = r.sheet;
  let lines = r.lines;
  const ol = el("ol", { class: "a4-lines" }, lines.map(l => el("li", {}, l)));
  const mode = el("span", { class: "small muted" }, "규칙 문안");
  const sign = el("tbody");
  const drawSign = () => sign.replaceChildren(...Array.from({ length: FLOW.n }, (_, k) => el("tr", {}, el("td", {}, k + 1), el("td", {}), el("td", {}, "양호 / 이상"), el("td", {}, "착용 / 미착용"), el("td", {}))));
  drawSign();
  const n = el("input", { type: "number", min: 3, max: 30, value: FLOW.n, style: { width: "70px" }, "aria-label": "참석자 줄 수", onchange: e => { FLOW.n = Math.max(3, Math.min(30, +e.target.value || 8)); drawSign(); } });
  const aiBtn = el("button", { class: "small", onclick: async () => {
    busy(aiBtn, true, "문안 쓰는 중");
    try { const x = await api("POST", `/api/assess/${FLOW.aid}/tbm/ai`); lines = x.lines; ol.replaceChildren(...lines.map(l => el("li", {}, l))); mode.textContent = x.mode + (x.dropped ? " · " + x.dropped : ""); }
    finally { busy(aiBtn, false); }
  } }, S.llm ? "AI로 말하기 쉽게 다시 쓰기" : "규칙 문안(모델 미연결)");
  box.replaceChildren(
    el("div", { class: "panel no-print" }, el("div", { class: "row" }, el("h2", { style: { margin: 0, flex: 1 } }, "작업 전 안전점검회의(TBM) 일지"),
      el("span", { class: "small muted" }, "참석자 줄"), n, aiBtn, mode),
      el("p", { class: "small muted" }, "A4 한 장으로 인쇄해 현장에서 읽고 서명받습니다. 위험요인은 확인된 것만, 위험성 높은 순서로 넣었습니다. 회의에서 새로 나온 위험은 4단계 위험성평가에 더하세요."),
      el("div", { class: "row" }, el("button", { class: "primary", onclick: () => { document.body.classList.add("print-a4"); window.print(); setTimeout(() => document.body.classList.remove("print-a4"), 500); } }, "인쇄(A4)"),
        exportButtons(`/api/assess/${FLOW.aid}/tbm`, () => ({ n: FLOW.n, lines })), el("span", { style: { flex: 1 } }),
        el("button", { onclick: () => flowGo(2) }, "← 위험요인 조회"), el("button", { class: "primary", id: "to-assess", onclick: () => flowGo(4) }, "위험성평가로"))),
    el("div", { class: "a4", id: "tbm-a4" },
      el("h1", {}, "작업 전 안전점검회의(TBM) 일지"),
      el("table", { class: "a4-t" }, el("tr", {}, el("th", {}, "일시"), el("td", {}, sh.date + "   :"), el("th", {}, "시설"), el("td", {}, sh.fac || "")),
        el("tr", {}, el("th", {}, "작업"), el("td", {}, sh.work), el("th", {}, "작업 책임자"), el("td", {}))),
      sh.steps.length ? el("div", { class: "a4-chips" }, el("b", {}, "오늘 작업 "), sh.steps.map(x => el("span", { class: "chip" }, x))) : null,
      el("h2", {}, "위험요인과 대책"),
      el("table", { class: "a4-t" }, el("tr", {}, ["번", "위험요인 · 위험 상황", "위험성", "대책(우선순위 순)"].map(h => el("th", {}, h))),
        sh.rows.map((x, k) => el("tr", {}, el("td", {}, k + 1), el("td", {}, el("b", {}, x.name), x.situations.map(s => el("div", { class: "small" }, s))),
          el("td", { class: "c" }, el("span", { class: "risk sm " + x.level }, x.risk)), el("td", {}, x.measures.map(m => el("div", {}, kindTag(m.kind), " ", m.text)))))),
      el("h2", {}, "전달 내용"), ol,
      el("h2", {}, "참석자 확인"),
      el("table", { class: "a4-t sign" }, el("thead", {}, el("tr", {}, ["번", "성명", "건강 상태", "보호구", "서명"].map(h => el("th", {}, h)))), sign),
      r.basis ? el("p", { class: "small muted" }, `※ 근거: ${r.basis.reg} ${r.basis.label}(${r.basis.title})`) : null));
}

async function flowGo(n) {
  if (n >= 3 && !FLOW.aid) { toast("먼저 위험요인을 조회해 평가 초안을 만드세요", true); n = FLOW.sel.size || $("#n-text").value ? 2 : 1; }
  FLOW.step = n;
  for (let i = 1; i <= 4; i++) $(`#flow-${i}`).hidden = i !== n;
  $$("#flow-steps button").forEach(b => { const s = +b.dataset.s; b.classList.toggle("on", s === n); b.classList.toggle("done", s < n); b.disabled = s >= 3 && !FLOW.aid; b.setAttribute("aria-current", s === n ? "step" : "false"); });
  if (n === 1) renderCatalog();
  if (n === 2) renderLookup();
  if (n === 3) await renderTBMSheet();
  if (n === 4) {
    $("#flow-4").append($("#detail"));
    CUR = await api("GET", `/api/assess/${FLOW.aid}`);
    renderDetail();
  }
  if (GO) GO("new");
  $("#flow-steps").scrollIntoView({ behavior: "smooth", block: "start" });
}


// ------------------------------------------------------------ 사진 위험 제보(전 직원 참여)
const RP = { photo: null, filter: "all", open: null, last: null, data: null };
async function renderPhoto() {
  const box = $("#tab-photo");
  const d = RP.data = await api("GET", "/api/reports");
  const keepY = window.scrollY;  // 다시 그릴 때 사진이 읽히는 동안 높이가 줄어 화면이 위로 튀지 않게
  box.style.minHeight = box.offsetHeight + "px";
  setTimeout(() => { box.style.minHeight = ""; }, 1500);
  const sm = d.summary;
  const prev = el("div", { class: "rp-prev" }, RP.photo ? el("img", { src: `data:image/jpeg;base64,${RP.photo.b64}`, alt: "올릴 사진" }) : el("span", { class: "muted small" }, "사진을 고르면 여기 보입니다"));
  const file = el("input", { type: "file", id: "rp-file", accept: "image/*", capture: "environment", hidden: true, onchange: async e => {
    const f = e.target.files[0]; if (!f) return;
    const [x] = await readFiles([f]); RP.photo = { name: x.path, b64: x.b64 }; renderPhoto();
  } });
  const text = el("input", { id: "rp-text", class: "wide", placeholder: "예: 풀사이드 배수구 주변 물이 고여 미끄러움", value: RP.text || "", oninput: e => { RP.text = e.target.value; } });
  const who = el("input", { id: "rp-who", class: "wide", placeholder: "비우면 익명", value: RP.who || "", oninput: e => { RP.who = e.target.value; } });
  const fac = el("select", { id: "rp-fac" }, el("option", { value: "" }, "사진 위치로 자동"), d.facilities.map(f => el("option", { value: f }, f)));
  const send = el("button", { class: "primary big", id: "rp-send", disabled: !RP.photo, onclick: async () => {
    busy(send, true, "사진 살펴보는 중");
    try {
      const r = await api("POST", "/api/reports", { photo: RP.photo, text: text.value, reporter: who.value, fac: fac.value });
      RP.photo = null; RP.text = ""; RP.last = r.id; RP.open = r.id; toast("제보했습니다. 안전담당자가 확인합니다.");
      await renderPhoto(); $("#rp-detail") && $("#rp-detail").scrollIntoView({ behavior: "smooth", block: "start" });
    } finally { busy(send, false); }
  } }, "제보하기");
  const det = d.detector.ok ? `사물 인식: ${d.detector.name}` : `사물 인식 꺼짐(${d.detector.why})`;
  const kpi = (lbl, v, cls) => el("div", { class: "stat" + (cls ? " " + cls : "") }, el("div", { class: "lbl" }, lbl), el("b", {}, v));
  const items = d.items.filter(r => RP.filter === "all" || (RP.filter === "doing" ? ["확인", "조치 중"].includes(r.status) : r.status === RP.filter));
  const max = Math.max(1, ...sm.by_fac.map(x => x[1]));
  box.replaceChildren(
    el("div", { class: "rp-top" },
      el("div", { class: "panel rp-form" },
        el("h2", {}, "본 위험, 사진 한 장으로 알려 주세요"),
        el("p", { class: "small muted" }, "안전담당자만의 일이 아닙니다. 수영장·체육관·주차장·사무실 어디든, 위험해 보이면 찍어서 올리면 됩니다. 사진에 담긴 촬영 시각과 위치로 시설을 자동으로 찾고, 위험요인 후보를 골라 안전담당자에게 넘깁니다."),
        el("div", { class: "rp-pick" }, file, el("label", { for: "rp-file", class: "rp-cam", role: "button", tabindex: 0, onkeydown: e => { if (e.key === "Enter") file.click(); } },
          el("svg", { viewBox: "0 0 24 24", "aria-hidden": "true", html: '<path d="M4 8h3l2-3h6l2 3h3v11H4z"/><circle cx="12" cy="13" r="3.5"/>' }), "사진 찍기·고르기"), prev),
        el("div", { class: "row small", style: { marginTop: "6px" } }, el("span", { class: "muted" }, "시연용 사진:"),
          (RP.samples || []).map(x => el("button", { class: "small", onclick: () => { RP.photo = x; RP.text = x.name.startsWith("수영장") ? "풀사이드 배수구 주변 물이 고여 미끄러움. 청소 호스가 바닥에 둔 채 있음" : "진출입로 정산기 앞 차로에서 점검 중, 라바콘 없음"; renderPhoto(); } }, x.name.replace(/\.jpg$/, "")))),
        el("label", { class: "f" }, "무엇이 위험한가요?(한 줄)"), text,
        el("div", { class: "grid2" }, el("div", {}, el("label", { class: "f" }, "이름"), who), el("div", {}, el("label", { class: "f" }, "시설"), fac)),
        el("div", { class: "row", style: { marginTop: "12px" } }, send, el("span", { class: "small muted" }, "위치 정보는 시설을 찾는 데만 쓰고, 저장하는 사진에서는 지웁니다."))),
      el("div", { class: "panel rp-side" },
        el("h3", {}, "참여 현황"),
        el("div", { class: "kpis rp-kpis" }, kpi("이번 달 제보", sm.month + "건"), el("div", { class: "stat" }, el("div", { class: "lbl" }, "참여 직원"), el("b", {}, sm.people + "명"), sm.anon ? el("div", { class: "small muted" }, `익명 제보 ${sm.anon}건`) : null),
          kpi("확인 기다림", sm.waiting + "건", sm.waiting ? "warn" : ""), kpi("조치 중", sm.doing + "건" + (sm.overdue ? ` · 기한 지남 ${sm.overdue}` : ""), sm.overdue ? "bad" : "")),
        el("h3", {}, "시설별 제보"),
        sm.by_fac.length ? sm.by_fac.map(([f, n]) => el("div", { class: "rp-bar" }, el("span", {}, f), el("i", { style: { width: `${n / max * 100}%` } }), el("b", {}, n))) : el("div", { class: "small muted" }, "아직 제보가 없습니다."),
        sm.by_hz.length ? [el("h3", {}, "많이 나온 위험"), sm.by_hz.map(([h, n]) => el("div", { class: "small" }, `${h} ${n}건`))] : null,
        el("p", { class: "small muted", style: { marginTop: "10px" } }, `판독: 설명 낱말 · ${d.llm ? "AI 판독(연결됨)" : "AI 판독(모델 미연결)"} · ${det}`, d.fac_demo ? " · 시설 위치는 시연용 좌표" : ""))),
    el("div", { class: "panel" },
      el("div", { class: "row" }, el("h2", { style: { margin: 0, flex: 1 } }, "안전담당 취합"),
        el("div", { class: "seg", role: "group", "aria-label": "처리 상태" }, [["all", "전체"], ["접수", "확인 기다림"], ["doing", "조치 중"], ["완료", "완료"], ["반려", "반려"]].map(([k, l]) =>
          el("button", { class: RP.filter === k ? "on" : "", onclick: () => { RP.filter = k; renderPhoto(); } }, l)))),
      el("p", { class: "small muted" }, "후보 위험요인을 '맞음/아님'으로 확인하고 담당·기한을 정합니다. 작업으로 고쳐야 하면 위험성평가 초안을 바로 만들 수 있습니다."),
      items.length ? el("div", { class: "rp-grid" }, items.map(r => el("button", { class: "rp-card" + (RP.open === r.id ? " on" : ""), onclick: () => { RP.open = RP.open === r.id ? null : r.id; renderPhoto(); } },
        el("img", { src: `/api/photo/${r.photo}`, alt: "", loading: "lazy" }),
        el("div", { class: "rp-meta" }, el("b", {}, r.fac || "시설 모름"), el("span", { class: "tag " + ({ "접수": "warn", "확인": "info", "조치 중": "info", "완료": "ok", "반려": "gray" })[r.status] }, r.status)),
        el("div", { class: "small rp-t" }, r.text || "(설명 없음)"),
        el("div", { class: "small muted" }, `${r.shot || r.at} · ${r.reporter}`),
        el("div", {}, r.hazards.filter(h => h.ok !== false).slice(0, 3).map(h => el("span", { class: "chip" }, h.name)))))) : el("div", { class: "empty" }, "이 상태의 제보가 없습니다.")),
    RP.open ? reportDetail(d.items.find(r => r.id === RP.open)) : null);
  window.scrollTo(0, keepY);
}

function reportDetail(r) {
  if (!r) return null;
  const up = async body => { await api("POST", `/api/reports/${r.id}`, body); await renderPhoto(); };
  const stage = el("div", { class: "rp-stage" }, el("img", { src: `/api/photo/${r.photo}`, alt: "제보 사진" }),
    r.objects.map(o => el("i", { class: "rp-box", style: { left: o.box[0] * 100 + "%", top: o.box[1] * 100 + "%", width: (o.box[2] - o.box[0]) * 100 + "%", height: (o.box[3] - o.box[1]) * 100 + "%" } }, el("em", {}, `${o.label} ${Math.round(o.score * 100)}%`))));
  const owner = el("input", { type: "text", value: r.owner, placeholder: "담당(예: 시설팀 김○○)" });
  const due = el("input", { type: "date", value: r.due });
  const memo = el("input", { type: "text", class: "wide", value: r.memo, placeholder: "조치 내용(예: 배수구 덮개 교체, 미끄럼 방지 매트 설치)" });
  const add = el("select", {}, el("option", { value: "" }, "빠진 위험요인 더하기…"), S.hazards.filter(h => !r.hazards.some(x => x.code === h.code)).map(h => el("option", { value: h.code }, `${h.code} ${h.name}`)));
  return el("div", { class: "panel", id: "rp-detail" },
    el("div", { class: "row" }, el("h2", { style: { margin: 0, flex: 1 } }, `${r.fac || "시설 모름"} 제보`), el("span", { class: "small muted" }, `${r.id} · 올린 날 ${r.at} · ${r.reporter}`)),
    el("div", { class: "rp-split" }, stage,
      el("div", {},
        el("div", { class: "row", style: { gap: "6px" } },
          el("span", { class: "chip" }, r.shot ? `촬영 ${r.shot}` : "촬영 시각 정보 없음"),
          el("span", { class: "chip" }, r.fac ? `${r.fac} · ${r.fac_by || "직접 입력"}` : "시설 모름"),
          r.gps ? el("span", { class: "chip", title: "저장한 사진에서는 위치 정보를 지웠습니다" }, "위치 정보 지움") : null),
        el("p", {}, r.text || "(설명 없음)"),
        el("div", { class: "small muted" }, "판독: " + r.engine.join(" + ") + (r.objects.length ? ` · 찾은 물건 ${r.objects.map(o => o.label).join(", ")}` : "")),
        r.notes.map(n => el("div", { class: "small muted" }, "※ " + n)),
        el("h3", {}, "위험요인 후보"),
        r.hazards.length ? r.hazards.map(h => el("div", { class: "rp-hz" + (h.ok === true ? " yes" : h.ok === false ? " no" : "") },
          el("div", { class: "row" }, el("b", { style: { flex: 1 } }, `${h.code} ${h.name}`), h.by.map(b => el("span", { class: "tag " + (b === "AI 판독" ? "warn" : b === "사물 인식" ? "info" : "gray") }, b)),
            el("button", { class: "small" + (h.ok === true ? " primary" : ""), onclick: () => up({ hazards: [{ code: h.code, ok: h.ok === true ? null : true }] }) }, "맞음"),
            el("button", { class: "small", onclick: () => up({ hazards: [{ code: h.code, ok: h.ok === false ? null : false }] }) }, "아님")),
          h.what.length ? el("div", { class: "small muted" }, h.what.join(" / ")) : null,
          el("div", { class: "small" }, h.measures.map(m => el("span", { class: "rp-m" }, kindTag(m.kind), " ", m.text))))) : el("div", { class: "q" }, "후보를 찾지 못했습니다. 사진을 보고 아래에서 위험요인을 더해 주세요."),
        el("div", { class: "row", style: { marginTop: "8px" } }, add, el("button", { class: "small", onclick: () => add.value && up({ add_code: add.value }) }, "더하기")))),
    el("div", { class: "row rp-act" }, el("b", {}, "처리"), owner, due, memo,
      el("button", { onclick: () => up({ owner: owner.value, due: due.value, memo: memo.value, status: r.status === "접수" || r.status === "확인" ? "조치 중" : r.status }) }, "담당·기한 저장"),
      el("button", { class: "primary", onclick: () => up({ memo: memo.value, status: "완료" }) }, "조치 완료"),
      el("button", { onclick: () => up({ status: "반려" }) }, "반려"),
      r.aid ? el("button", { onclick: () => openA(r.aid) }, "연결된 평가 열기")
        : el("button", { class: "primary", onclick: async () => { const x = await api("POST", `/api/reports/${r.id}/assess`); await load(); openA(x.aid); } }, "위험성평가 초안 만들기"),
      el("span", { style: { flex: 1 } }),
      el("button", { class: "danger small", onclick: async () => { if (!confirm("이 제보를 지울까요? 되돌릴 수 없습니다.")) return; await api("DELETE", `/api/reports/${r.id}`); RP.open = null; renderPhoto(); } }, "삭제")));
}

// ------------------------------------------------------------ 안전 성과: 체계도·연간/월간/주간 실적·결재 대기·공종 담당·협력업체 DB
const PF = { unit: "month", anchor: null, data: null, vend: null, openV: null, edit: false };
const won = n => n >= 1e8 ? (n / 1e8).toFixed(1).replace(/\.0$/, "") + "억 원" : n >= 1e4 ? Math.round(n / 1e4).toLocaleString() + "만 원" : n.toLocaleString() + "원";
function shiftAnchor(dir) {
  const d = new Date(PF.anchor + "T00:00:00");
  if (PF.unit === "year") d.setFullYear(d.getFullYear() + dir);
  else if (PF.unit === "month") { d.setDate(1); d.setMonth(d.getMonth() + dir); }
  else d.setDate(d.getDate() + 7 * dir);
  const z = n => String(n).padStart(2, "0");
  PF.anchor = `${d.getFullYear()}-${z(d.getMonth() + 1)}-${z(d.getDate())}`;
  renderPerf();
}
function sysDiagram(p) {
  const c = p.cfg, n = p.counts, w = st => p.waiting.filter(x => x.stage === st).length;
  const owners = c.owners.filter(o => o.name);
  const node = (cls, title, who, big, sub) => el("div", { class: "sd-node " + cls }, el("div", { class: "sd-t" }, title), who ? el("div", { class: "sd-who" }, who) : null,
    big != null ? el("div", { class: "sd-big" }, big) : null, sub ? el("div", { class: "sd-sub" }, sub) : null);
  const arrow = lbl => el("div", { class: "sd-arrow", "aria-hidden": "true" }, el("span", {}, lbl || ""));
  return el("div", { class: "panel sd" },
    el("div", { class: "row" }, el("h2", { style: { margin: 0, flex: 1 } }, "안전관리 체계도"), c.demo ? el("span", { class: "tag gray" }, "이름은 시연용 예시") : null),
    el("p", { class: "small muted" }, "누가 무엇을 올리고, 누가 검토·합의·승인하며, 그 기록이 어떻게 성과로 모이는지 한 장으로 봅니다. 숫자는 지금 저장된 기록에서 바로 셉니다."),
    el("div", { class: "sd-in" },
      node("in", "전 직원", "사진 한 장으로 위험 제보", `${n.reports}건`, `조치 중·대기 ${n.reports_open}건`),
      node("in", "공종 담당", `${owners.length}개 공종 · ${[...new Set(owners.map(o => o.name))].length}명`, `${n.assess}건`, "위험성평가·TBM 작성"),
      node("in", "아차사고", "현장 보고", `${n.incidents}건`, "같은 작업 평가에 수시평가 표시"),
      node("in", "협력업체", "수선유지·협력부서 보고서", `${n.vendors}곳`, `작업 ${n.vendor_jobs}건 · 위험 작업은 협의 대상`)),
    el("div", { class: "sd-down", "aria-hidden": "true" }),
    el("div", { class: "sd-flow" },
      node("st", "작성", "공종 담당", null, "위험요인 확인 후 검토 요청"), arrow(),
      node("st", "검토", `${c.reviewer_dept || "안전팀"} ${c.reviewer || "(미지정)"}`, w("검토 대기"), "대기"), arrow(),
      node("st" + (c.agree ? "" : " off"), "합의", c.agree ? `${c.agree_dept || "협력부서"} ${c.agree}` : "지정 안 함(건너뜀)", c.agree ? w("합의 대기") : null, c.agree ? "대기" : ""), arrow(),
      node("st", "승인", `${c.approver_dept || "승인권자"} ${c.approver || "(미지정)"}`, w("승인 대기"), "대기"), arrow(),
      node("st done", "확정", "작업 시작", p.approval.approved, `${p.label} 승인`)),
    el("div", { class: "sd-down", "aria-hidden": "true" }),
    el("div", { class: "sd-out" },
      node("db", "안전 활동 DB", "평가·승인·감소대책·TBM·제보·조치·아차사고", `${p.total}건`, `${p.label} 활동`),
      node("db", "연간 · 월간 · 주간 성과", "아래 표와 엑셀로", `${p.measures.total ? Math.round(p.measures.done / p.measures.total * 100) : 0}%`, "감소대책 완료율")));
}
const GCLR = { "평가·결재": "#1f4e9c", "안전조치 완료": "#2a9d6a", "TBM·점검·교육": "#8a5cd0", "제보·아차사고": "#e08a1e" };
const GNAMES = Object.keys(GCLR);
const svgEl = (tag, attrs, ...kids) => { const e = document.createElementNS("http://www.w3.org/2000/svg", tag); for (const [k, v] of Object.entries(attrs || {})) if (v != null) e.setAttribute(k, v); kids.flat().forEach(k => k != null && e.append(k)); return e; };
function kindGroup(p, k) { for (const [g, ks] of Object.entries(p.groups_def)) if (ks.includes(k)) return g; return GNAMES[0]; }
function gLegend(vals) { return el("div", { class: "pf-legend small" }, GNAMES.map(g => el("span", {}, el("i", { style: { background: GCLR[g] } }), g, vals ? el("b", {}, ` ${vals[g]}`) : null))); }
function tipBox(wrap) {
  const tip = el("div", { class: "pf-tip", hidden: true });
  wrap.append(tip);
  return (html, x, y) => { if (html == null) { tip.hidden = true; return; } tip.innerHTML = html; tip.hidden = false;
    const w = wrap.clientWidth; tip.style.left = Math.min(Math.max(x + 12, 0), w - tip.offsetWidth - 4) + "px"; tip.style.top = Math.max(y - tip.offsetHeight - 8, 0) + "px"; };
}
function cumChart(p) {
  const W = 720, H = 250, L = 40, R = 110, T = 14, B = 28, n = p.cum.length;
  const tot = p.cum.map(c => GNAMES.reduce((a, g) => a + c[g], 0));
  const max = Math.max(4, ...tot), nice = Math.pow(10, Math.floor(Math.log10(max))), top = Math.ceil(max / nice) * nice;
  const x = i => L + (n === 1 ? (W - L - R) / 2 : i * (W - L - R) / (n - 1)), y = v => T + (H - T - B) * (1 - v / top);
  const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, class: "pf-svg", role: "img", "aria-label": `${p.label} 안전 활동 누적: 총 ${tot[n - 1] || 0}건` });
  for (let k = 0; k <= 4; k++) { const v = top * k / 4; svg.append(svgEl("line", { x1: L, x2: W - R, y1: y(v), y2: y(v), class: "pf-grid" + (k ? "" : " base") }), svgEl("text", { x: L - 8, y: y(v) + 4, class: "pf-ax", "text-anchor": "end" }, String(Math.round(v)))); }
  const step = Math.ceil(n / 12);
  p.trend.forEach((t, i) => { if (i % step === 0 || i === n - 1) svg.append(svgEl("text", { x: x(i), y: H - 8, class: "pf-ax", "text-anchor": "middle" }, t.label)); });
  const today = (S && S.today) || p.to, last = Math.max(0, p.trend.filter(t => t.from <= today).length - 1);  // 오늘 이후 구간은 그리지 않음
  const cum = p.cum.slice(0, last + 1);
  let base = cum.map(() => 0);
  const ends = [];
  GNAMES.forEach(g => {
    const topv = cum.map((c, i) => base[i] + c[g]);
    const pts = topv.map((v, i) => `${x(i)},${y(v)}`).join(" "), back = base.map((v, i) => `${x(i)},${y(v)}`).reverse().join(" ");
    svg.append(svgEl("polygon", { points: pts + " " + back, fill: GCLR[g], "fill-opacity": .2 }), svgEl("polyline", { points: pts, fill: "none", stroke: GCLR[g], "stroke-width": 2, "stroke-linejoin": "round" }));
    ends.push({ g, v: cum[last][g], y: y((topv[last] + base[last]) / 2) });
    base = topv;
  });
  if (last < n - 1) svg.append(svgEl("text", { x: x(last) + 6, y: T + 10, class: "pf-ax" }, "오늘"), svgEl("line", { x1: x(last), x2: x(last), y1: T, y2: H - B, class: "pf-grid" }));
  // 오른쪽 끝 직접 라벨(겹치지 않게 위아래로 밀어 냄)
  ends.splice(0, ends.length, ...ends.filter(e => e.v > 0));
  ends.sort((a, b) => a.y - b.y).forEach((e, i, arr) => { if (i && e.y - arr[i - 1].y < 13) e.y = arr[i - 1].y + 13; });
  ends.forEach(e => svg.append(svgEl("text", { x: x(last) + 6, y: e.y + 4, class: "pf-end" }, `${e.g} ${e.v}`)));
  const cross = svgEl("line", { y1: T, y2: H - B, class: "pf-cross", visibility: "hidden" });
  svg.append(cross);
  const wrap = el("div", { class: "pf-chart" }, svg);
  const tip = tipBox(wrap);
  svg.addEventListener("mousemove", e => {
    const r = svg.getBoundingClientRect(), sx = (e.clientX - r.left) * W / r.width;
    const i = Math.max(0, Math.min(last, Math.round((sx - L) / ((W - L - R) / Math.max(1, n - 1)))));
    cross.setAttribute("x1", x(i)); cross.setAttribute("x2", x(i)); cross.setAttribute("visibility", "visible");
    const c = p.cum[i];
    tip(`<b>${p.trend[i].label}까지 누적 ${tot[i]}건</b>` + GNAMES.map(g => `<div><i style="background:${GCLR[g]}"></i>${g} <b>${c[g]}</b></div>`).join(""), (e.clientX - r.left), (e.clientY - r.top));
  });
  svg.addEventListener("mouseleave", () => { cross.setAttribute("visibility", "hidden"); tip(null); });
  return wrap;
}
function donut(p) {
  const tot = GNAMES.reduce((a, g) => a + p.groups[g], 0), R = 70, r = 46, C = 90;
  const svg = svgEl("svg", { viewBox: "0 0 180 180", class: "pf-donut", role: "img", "aria-label": "활동 구성 " + GNAMES.map(g => `${g} ${p.groups[g]}건`).join(", ") });
  if (!tot) svg.append(svgEl("circle", { cx: C, cy: C, r: (R + r) / 2, fill: "none", stroke: "var(--line)", "stroke-width": R - r }));
  let a0 = -Math.PI / 2;
  const wrap = el("div", { class: "pf-chart pf-donut-w" }, svg);
  const tip = tipBox(wrap);
  GNAMES.forEach(g => {
    const v = p.groups[g]; if (!v) return;
    const a1 = a0 + v / tot * Math.PI * 2, gap = tot === v ? 0 : 0.02;
    const pt = (rad, a) => `${C + rad * Math.cos(a)},${C + rad * Math.sin(a)}`, large = a1 - a0 - gap > Math.PI ? 1 : 0;
    const d = tot === v ? `M${C},${C - R}A${R},${R} 0 1 1 ${C - .01},${C - R}L${C - .01},${C - r}A${r},${r} 0 1 0 ${C},${C - r}Z`
      : `M${pt(R, a0 + gap / 2)}A${R},${R} 0 ${large} 1 ${pt(R, a1 - gap / 2)}L${pt(r, a1 - gap / 2)}A${r},${r} 0 ${large} 0 ${pt(r, a0 + gap / 2)}Z`;
    const path = svgEl("path", { d, fill: GCLR[g], class: "pf-seg" });
    path.addEventListener("mousemove", e => { const b = wrap.getBoundingClientRect(); tip(`<b>${g}</b><div>${v}건 · ${Math.round(v / tot * 100)}%</div>`, e.clientX - b.left, e.clientY - b.top); });
    path.addEventListener("mouseleave", () => tip(null));
    svg.append(path); a0 = a1;
  });
  svg.append(svgEl("text", { x: C, y: C - 2, class: "pf-dn", "text-anchor": "middle" }, String(tot)), svgEl("text", { x: C, y: C + 18, class: "pf-ax", "text-anchor": "middle" }, "건"));
  wrap.append(el("div", { class: "pf-dlist" }, GNAMES.map(g => el("div", {}, el("i", { style: { background: GCLR[g] } }), el("span", {}, g), el("b", {}, p.groups[g]), el("em", {}, tot ? Math.round(p.groups[g] / tot * 100) + "%" : "-")))));
  return wrap;
}
function heatmap(p) {
  const d0 = new Date(p.from + "T00:00:00"), d1 = new Date(p.to + "T00:00:00");
  const start = new Date(d0); start.setDate(start.getDate() - ((start.getDay() + 6) % 7));
  const days = [];
  for (let d = new Date(start); d <= d1; d.setDate(d.getDate() + 1)) days.push(new Date(d));
  const weeks = Math.ceil(days.length / 7), big = weeks <= 6;  // 월간·주간은 달력 모양(가로 요일), 연간은 잔디 모양(세로 요일)
  const cs = big ? 44 : 12, gp = big ? 6 : 3, L = big ? 0 : 22, T = 16;
  const W = big ? 7 * (cs + gp) : L + weeks * (cs + gp), H = big ? T + weeks * (cs + gp) : T + 7 * (cs + gp);
  const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, class: "pf-heat", style: `max-width:${big ? W * 1.3 : W * 1.6}px`, role: "img", "aria-label": `${p.label} 날짜별 안전 활동 건수` });
  const z = n => String(n).padStart(2, "0"), iso = d => `${d.getFullYear()}-${z(d.getMonth() + 1)}-${z(d.getDate())}`;
  const lv = c => !c ? "var(--fill)" : c === 1 ? "#c9d8ef" : c === 2 ? "#8fb0de" : c <= 4 ? "#4f7fc4" : "#1f4e9c";
  if (big) "월화수목금토일".split("").forEach((t, i) => svg.append(svgEl("text", { x: i * (cs + gp) + cs / 2, y: 11, class: "pf-ax", "text-anchor": "middle" }, t)));
  else "월수금".split("").forEach((t, i) => svg.append(svgEl("text", { x: 0, y: T + (i * 2) * (cs + gp) + cs * .75, class: "pf-ax sm" }, t)));
  const wrap = el("div", { class: "pf-chart pf-heat-w" }, svg);
  const tip = tipBox(wrap);
  let lastM = -1;
  const today = (S && S.today) || p.to;
  days.forEach((d, i) => {
    const key = iso(d), wk = Math.floor(i / 7), dw = i % 7, inside = d >= d0 && d <= d1, future = key > today, c = p.daily[key] || 0;
    if (!big && dw === 0 && d.getMonth() !== lastM && inside) { lastM = d.getMonth(); svg.append(svgEl("text", { x: L + wk * (cs + gp), y: 10, class: "pf-ax sm" }, `${d.getMonth() + 1}월`)); }
    if (!inside || (future && !big)) return;
    const cx = big ? dw * (cs + gp) : L + wk * (cs + gp), cy = big ? T + 4 + wk * (cs + gp) : T + dw * (cs + gp);
    const r = svgEl("rect", { x: cx, y: cy, width: cs, height: cs, rx: big ? 8 : 3, fill: future ? "none" : lv(c), stroke: future ? "var(--line)" : null, "stroke-dasharray": future ? "3 3" : null, class: "pf-cell" });
    if (!future) { r.addEventListener("mousemove", e => { const b = wrap.getBoundingClientRect(); tip(`<b>${key}</b><div>안전 활동 ${c}건</div>`, e.clientX - b.left, e.clientY - b.top); }); r.addEventListener("mouseleave", () => tip(null)); }
    svg.append(r);
    if (big) {
      svg.append(svgEl("text", { x: cx + 6, y: cy + 14, class: "pf-cn" + (c >= 3 ? " inv" : "") }, String(d.getDate())));
      if (c) svg.append(svgEl("text", { x: cx + cs - 6, y: cy + cs - 7, "text-anchor": "end", class: "pf-cc" + (c >= 3 ? " inv" : "") }, `${c}건`));
    }
  });
  const active = Object.keys(p.daily).length;
  wrap.append(el("div", { class: "pf-heat-leg small muted", style: { maxWidth: big ? W * 1.3 + "px" : "" } }, `활동한 날 ${active}일`, el("span", { style: { flex: 1 } }), "적음", [0, 1, 2, 3, 5].map(c => el("i", { style: { background: lv(c) } })), "많음"));
  return wrap;
}
function recentFeed(p) {
  if (!p.recent.length) return el("div", { class: "empty" }, "이 기간에 끝낸 안전조치가 없습니다.");
  return el("ol", { class: "pf-feed" }, p.recent.map(x => el("li", {},
    el("span", { class: "pf-fd" }, x.date.slice(5).replace("-", ".")), el("i", { style: { background: GCLR["안전조치 완료"] } }),
    el("div", {}, el("div", { class: "pf-ft" }, x.title), el("div", { class: "small muted" }, [x.kind, x.fac, x.who].filter(Boolean).join(" · "), x.imported ? " · 가져온 실적" : "")))));
}
function importStrip(p) {
  const file = el("input", { type: "file", id: "led-file", accept: ".xlsx,.csv", hidden: true, onchange: async e => {
    const files = await readFiles([...e.target.files]); if (!files.length) return;
    const r = await api("POST", "/api/activities/upload", { files }); r.added.forEach(a => toast(a.error ? `${a.name}: ${a.error}` : `${a.name}: 실적 ${a.rows}건을 가져왔습니다`, !!a.error)); renderPerf();
  } });
  return el("div", { class: "pf-import" },
    el("span", { class: "small" }, el("b", {}, "기존 실적 대장"), " 엑셀(날짜·활동·시설·공종·담당·내용)로 관리하던 점검·교육·TBM·개선 실적도 함께 쌓습니다."),
    p.import_files.map(f => el("span", { class: "chip" }, `${f.name} · ${f.rows}건`)),
    el("span", { style: { flex: 1 } }),
    el("label", { for: "led-file", class: "btn-like small", role: "button", tabindex: 0, onkeydown: e => { if (e.key === "Enter") file.click(); } }, "실적 대장 올리기"), file,
    el("button", { class: "small", id: "led-sample", onclick: async () => { const r = await api("POST", "/api/activities/sample"); toast(`시연용 실적 ${r.added[0].rows}건을 가져왔습니다`); renderPerf(); } }, "시연 실적 넣기"),
    p.import_files.length ? el("button", { class: "small", onclick: async () => { await api("DELETE", "/api/activities/import"); renderPerf(); } }, "가져온 실적 지우기") : null);
}
function trendChart(p) {
  const tots = p.trend.map(t => Object.values(t.counts).reduce((a, b) => a + b, 0)), max = Math.max(1, ...tots);
  const wrap = el("div", { class: "pf-chart" });
  const tip = tipBox(wrap);
  wrap.prepend(el("div", { class: "pf-trend", role: "img", "aria-label": `${p.label} 구간별 안전 활동` },
    p.trend.map((t, i) => {
      const gv = GNAMES.map(g => [g, p.groups_def[g].reduce((a, k) => a + (t.counts[k] || 0), 0)]);
      const col = el("div", { class: "pf-col" },
        el("div", { class: "pf-n" }, tots[i] || ""),
        el("div", { class: "pf-stack", style: { height: `${tots[i] / max * 100}%` } }, gv.filter(x => x[1]).map(([g, v]) => el("i", { style: { flex: v, background: GCLR[g] } }))),
        el("div", { class: "pf-l" }, t.label));
      col.addEventListener("mousemove", e => { const b = wrap.getBoundingClientRect(); tip(`<b>${t.label} (${t.from.slice(5)}~${t.to.slice(5)}) ${tots[i]}건</b>` + gv.map(([g, v]) => `<div><i style="background:${GCLR[g]}"></i>${g} <b>${v}</b></div>`).join(""), e.clientX - b.left, e.clientY - b.top); });
      col.addEventListener("mouseleave", () => tip(null));
      return col;
    })));
  return wrap;
}
function ownerTable(p) {
  const c = p.cfg;
  if (!PF.edit) {
    const stat = Object.fromEntries(p.by_owner.map(x => [x.cat, x]));
    return el("div", {},
      el("div", { class: "tbl-scroll" }, el("table", { class: "t" }, el("tr", {}, ["공종", "담당", "부서", "평가", "승인", "미완료 감소대책"].map(h => el("th", {}, h))),
        c.owners.map(o => { const s = stat[o.cat] || {}; return el("tr", {}, el("td", {}, o.cat), el("td", {}, o.name || el("span", { class: "muted" }, "미지정")), el("td", {}, o.dept),
          el("td", {}, s.total || 0), el("td", {}, s.approved || 0), el("td", {}, s.open ? el("span", { class: "tag warn" }, s.open) : 0)); }),
        stat["공종 미지정"] ? el("tr", {}, el("td", {}, "공종 미지정"), el("td", { colspan: 2, class: "muted" }, "작업 분류를 고르지 않은 평가"), el("td", {}, stat["공종 미지정"].total), el("td", {}, stat["공종 미지정"].approved), el("td", {}, stat["공종 미지정"].open)) : null)),
      el("div", { class: "small muted" }, `결재선: 공종 담당(작성) → ${c.reviewer_dept} ${c.reviewer || "미지정"}(검토) → ${c.agree ? `${c.agree_dept} ${c.agree}(합의) → ` : ""}${c.approver_dept} ${c.approver || "미지정"}(승인)`),
      el("button", { class: "small", style: { marginTop: "8px" }, id: "pf-edit", onclick: () => { PF.edit = true; renderPerf(); } }, "담당자·결재선 바꾸기"));
  }
  const inp = (v, ph) => el("input", { type: "text", value: v || "", placeholder: ph });
  const rows = c.owners.map(o => ({ cat: o.cat, name: inp(o.name, "이름"), dept: inp(o.dept, "부서") }));
  const f = { reviewer: inp(c.reviewer, "이름"), reviewer_dept: inp(c.reviewer_dept, "부서"), agree: inp(c.agree, "비우면 합의 단계 건너뜀"), agree_dept: inp(c.agree_dept, "부서"),
    approver: inp(c.approver, "이름"), approver_dept: inp(c.approver_dept, "직위·부서") };
  return el("div", {},
    el("div", { class: "tbl-scroll" }, el("table", { class: "t pf-edit" }, el("tr", {}, ["공종(작업 분류)", "담당", "부서"].map(h => el("th", {}, h))),
      rows.map(r => el("tr", {}, el("td", {}, r.cat), el("td", {}, r.name), el("td", {}, r.dept))),
      [["검토(안전팀)", "reviewer"], ["합의(협력부서)", "agree"], ["승인", "approver"]].map(([l, k]) => el("tr", {}, el("th", {}, l), el("td", {}, f[k]), el("td", {}, f[k + "_dept"]))))),
    el("div", { class: "row", style: { marginTop: "8px" } },
      el("button", { class: "primary", id: "pf-save", onclick: async () => {
        await api("POST", "/api/safety-cfg", Object.assign(Object.fromEntries(Object.entries(f).map(([k, v]) => [k, v.value])), { owners: rows.map(r => ({ cat: r.cat, name: r.name.value, dept: r.dept.value })) }));
        PF.edit = false; toast("담당자와 결재선을 저장했습니다. 새로 결재를 시작하는 평가부터 적용됩니다."); renderPerf();
      } }, "저장"), el("button", { onclick: () => { PF.edit = false; renderPerf(); } }, "취소")));
}
function vendorBox(v) {
  const file = el("input", { type: "file", id: "vd-file", multiple: true, accept: ".xlsx,.hwpx,.docx,.pdf,.txt,.csv", hidden: true, onchange: async e => {
    const files = await readFiles([...e.target.files]); if (!files.length) return;
    const r = await api("POST", "/api/vendors/upload", { files });
    PF.vend = r; r.added.forEach(a => toast(a.error ? `${a.name}: ${a.error}` : `${a.name}: 작업 ${a.jobs}건을 읽었습니다`, !!a.error)); renderPerf();
  } });
  const t = v.total;
  return el("div", { class: "panel", id: "vd" },
    el("div", { class: "row" }, el("h2", { style: { margin: 0, flex: 1 } }, "협력업체 DB"),
      el("label", { for: "vd-file", class: "btn-like", role: "button", tabindex: 0, onkeydown: e => { if (e.key === "Enter") file.click(); } }, "보고서 올리기"), file,
      el("button", { id: "vd-sample", onclick: async () => { PF.vend = await api("POST", "/api/vendors/sample"); toast("시연용 보고서 3개를 읽었습니다"); renderPerf(); } }, "시연 보고서 넣기"),
      v.vendors.length ? el("button", { onclick: () => download("/api/vendors/xlsx", {}) }, "엑셀") : null),
    el("p", { class: "small muted" }, "협력부서 작업 완료 보고, 수선유지 실적 표(엑셀·한글·워드·PDF)를 올리면 업체명·공사명·금액·기간·시설을 읽어 업체별로 모읍니다. 읽은 값마다 원문 위치가 붙고, 공사명·안전 비고에 중대성 3 위험요인 낱말이 있으면 '위험 작업'으로 표시해 도급 작업 안전보건 협의 대상을 바로 봅니다."),
    v.docs.length ? el("div", { class: "row small", style: { gap: "6px" } }, v.docs.map(d => el("span", { class: "chip" + (d.error ? " bad" : "") , title: d.error || "" }, `${d.name} · ${d.error ? "읽지 못함" : d.jobs + "건"}`,
      el("button", { class: "x", "aria-label": `${d.name} 빼기`, onclick: async () => { PF.vend = await api("DELETE", `/api/vendors/${d.id}`); renderPerf(); } }, "×")))) : null,
    v.vendors.length ? [
      el("div", { class: "kpis", style: { margin: "12px 0" } },
        [["업체", t.vendors + "곳"], ["작업", t.jobs + "건"], ["금액 합계", won(t.amount)], ["위험 작업 업체", t.risky + "곳", t.risky ? "warn" : ""]].map(([l, x, c]) => el("div", { class: "stat" + (c ? " " + c : "") }, el("div", { class: "lbl" }, l), el("b", {}, x)))),
      el("div", { class: "tbl-scroll" }, el("table", { class: "t vd-t" }, el("tr", {}, ["업체", "작업", "금액", "시설", "발주 부서", "최근 작업", "위험 작업(협의 대상)"].map(h => el("th", {}, h))),
        v.vendors.map(x => [el("tr", { class: "vd-row" + (PF.openV === x.key ? " on" : ""), onclick: () => { PF.openV = PF.openV === x.key ? null : x.key; renderPerf(); } },
          el("td", {}, el("b", {}, x.name)), el("td", {}, x.count + "건"), el("td", {}, won(x.amount)), el("td", {}, x.facs.join(", ")), el("td", {}, x.depts.join(", ")), el("td", {}, x.last),
          el("td", {}, x.risky.length ? x.risky.map(r => el("span", { class: "tag warn", style: { marginRight: "4px" } }, r.name)) : el("span", { class: "muted" }, "-"))),
          PF.openV === x.key ? el("tr", { class: "vd-jobs" }, el("td", { colspan: 7 }, x.jobs.map(j => el("div", { class: "vd-job" },
            el("b", {}, j.work), el("span", {}, `${j.start}${j.end && j.end !== j.start ? " ~ " + j.end : ""}`), el("span", {}, won(j.amount)), el("span", {}, j.fac), el("span", { class: "muted" }, j.note),
            el("span", { class: "chip", title: j.src.quote }, `${j.src.file} ${j.src.loc}`))))) : null]))),
    ] : el("div", { class: "empty" }, "아직 올린 보고서가 없습니다. '시연 보고서 넣기'로 모의 수선유지 실적·작업 완료 보고를 읽어 볼 수 있습니다."));
}
async function renderPerf() {
  const box = $("#tab-perf");
  if (!PF.anchor) PF.anchor = (S && S.today) || new Date(Date.now() - new Date().getTimezoneOffset() * 6e4).toISOString().slice(0, 10);
  const keepY = window.scrollY;
  box.style.minHeight = box.offsetHeight + "px"; setTimeout(() => { box.style.minHeight = ""; }, 1200);
  const [p, v] = await Promise.all([api("GET", `/api/performance?unit=${PF.unit}&anchor=${PF.anchor}`), PF.vend ? Promise.resolve(PF.vend) : api("GET", "/api/vendors")]);
  PF.data = p; PF.vend = v;
  const kpi = (lbl, val, sub, cls) => el("div", { class: "stat" + (cls ? " " + cls : "") }, el("div", { class: "lbl" }, lbl), el("b", {}, val), sub ? el("div", { class: "small muted" }, sub) : null);
  const md = p.measures, rp = p.reports;
  const maxF = Math.max(1, ...p.by_fac.map(x => x[1]));
  box.replaceChildren(
    sysDiagram(p),
    el("div", { class: "panel" },
      el("div", { class: "row" }, el("h2", { style: { margin: 0, flex: 1 } }, "안전 활동 성과"),
        el("div", { class: "seg", role: "group", "aria-label": "기간 단위" }, [["year", "연간"], ["month", "월간"], ["week", "주간"]].map(([k, l]) =>
          el("button", { class: PF.unit === k ? "on" : "", "data-unit": k, onclick: () => { PF.unit = k; renderPerf(); } }, l))),
        el("button", { class: "small", "aria-label": "이전 기간", onclick: () => shiftAnchor(-1) }, "‹"), el("b", { class: "pf-label" }, p.label),
        el("button", { class: "small", "aria-label": "다음 기간", onclick: () => shiftAnchor(1) }, "›"),
        el("button", { onclick: () => download("/api/performance/xlsx", { unit: PF.unit, anchor: PF.anchor }) }, "엑셀")),
      el("p", { class: "small muted" }, "안전 활동 DB는 따로 입력하지 않습니다. 위험성평가·결재·감소대책 완료·TBM 일지·사진 제보·조치·아차사고 기록과 가져온 실적 대장에서 날짜별로 다시 셉니다(시연용 아차사고·실적 대장은 모의자료)."),
      el("div", { class: "kpis" },
        kpi("안전 활동", p.total + "건", `참여 ${p.people}명(실명)`),
        kpi("감소대책 완료율", md.total ? Math.round(md.done / md.total * 100) + "%" : "-", `${md.done}/${md.total}개 · 기간 안 평가`, md.total && md.done < md.total ? "warn" : ""),
        kpi("사진 제보 조치", `${rp.done}/${rp.total}건`, rp.avg_days != null ? `평균 ${rp.avg_days}일 만에 완료` : "완료된 제보 없음"),
        kpi("평가 승인", `${p.approval.approved}/${p.approval.total}건`, `결재 진행 ${p.approval.waiting}건`, p.approval.waiting ? "warn" : "")),
      importStrip(p),
      el("div", { class: "pf-grid" },
        el("div", {}, el("h3", {}, `안전조치 실적이 쌓이는 모습 · ${p.label} 누적`), cumChart(p), gLegend()),
        el("div", {}, el("h3", {}, "활동 구성"), donut(p))),
      el("h3", {}, "안전 활동 달력"), heatmap(p),
      el("div", { class: "pf-grid" },
        el("div", {}, el("h3", {}, PF.unit === "year" ? "월별 활동" : PF.unit === "month" ? "주별 활동" : "요일별 활동"), trendChart(p), gLegend(p.groups)),
        el("div", {}, el("h3", {}, "최근 끝낸 안전조치"), recentFeed(p))),
      el("div", { class: "pf-grid3" },
        el("div", {}, el("h3", {}, "활동별"), el("table", { class: "t pf-kind" }, Object.entries(p.by_kind).map(([k, n]) => el("tr", {}, el("td", {}, el("i", { class: "dot", style: { background: GCLR[kindGroup(p, k)] } }), k), el("td", { class: "num" }, n + "건"))))),
        el("div", {}, el("h3", {}, "시설별"), p.by_fac.length ? p.by_fac.slice(0, 7).map(([f, n]) => el("div", { class: "rp-bar" }, el("span", {}, f), el("i", { style: { width: `${n / maxF * 100}%` } }), el("b", {}, n))) : el("div", { class: "small muted" }, "기간 안 활동이 없습니다.")),
        el("div", {}, el("h3", {}, "공종별"), p.by_cat.length ? (() => { const mc = Math.max(...p.by_cat.map(x => x[1])); return p.by_cat.slice(0, 8).map(([c, n]) => el("div", { class: "rp-bar" }, el("span", {}, c), el("i", { style: { width: `${n / mc * 100}%`, background: "#8a5cd0" } }), el("b", {}, n))); })() : el("div", { class: "small muted" }, "공종이 적힌 활동이 없습니다."))),
      p.rows.length ? el("details", { class: "pf-rows" }, el("summary", {}, `활동 기록 ${p.rows.length}건 보기`),
        el("div", { class: "tbl-scroll" }, el("table", { class: "t" }, el("tr", {}, ["날짜", "활동", "시설", "공종", "담당·제보자", "내용"].map(h => el("th", {}, h))),
          p.rows.slice(0, 100).map(x => el("tr", {}, el("td", {}, x.date), el("td", {}, el("i", { class: "dot", style: { background: GCLR[kindGroup(p, x.kind)] } }), x.kind), el("td", {}, x.fac), el("td", {}, x.cat), el("td", {}, x.who), el("td", {}, x.title, x.imported ? el("span", { class: "tag gray", style: { marginLeft: "6px" } }, "가져온 실적") : null)))))) : null),
    el("div", { class: "pf-two" },
      el("div", { class: "panel" }, el("h2", {}, "결재 대기"),
        p.waiting.length ? el("div", { class: "tbl-scroll" }, el("table", { class: "t" }, el("tr", {}, ["단계", "작업", "처리할 사람", ""].map(h => el("th", {}, h))),
          p.waiting.map(x => el("tr", {}, el("td", {}, el("span", { class: "tag " + (x.stage === "반려" ? "bad" : "warn") }, x.stage)), el("td", {}, `${x.fac} · ${x.work}`), el("td", {}, x.who),
            el("td", {}, el("button", { class: "small", onclick: () => openA(x.id) }, "열기")))))) : el("div", { class: "empty" }, "결재를 기다리는 평가가 없습니다.")),
      el("div", { class: "panel" }, el("h2", {}, "공종별 담당자"), ownerTable(p))),
    vendorBox(v));
  window.scrollTo(0, keepY);
}

function approvalPanel(a) {
  const ap = a.approval, sg = ap.stage;
  const cur = ap.line.find(x => x.result !== "완료");
  const memo = el("input", { type: "text", class: "wide", id: "ap-memo", placeholder: "의견(선택)" });
  const name = el("input", { type: "text", id: "ap-name", value: cur && !ap.rejected ? cur.name : "", placeholder: "처리자 이름" });
  const go = async action => {
    try { CUR = await api("POST", `/api/assess/${a.id}/approve`, { action, name: name.value, memo: memo.value }); renderDetail(); S = await api("GET", "/api/state"); renderDash(); renderList(); toast(`결재: ${CUR.approval.stage}`); }
    catch (e) { /* api()가 알림을 띄움 */ }
  };
  const label = { "작성": "검토 요청", "검토": "검토 완료", "합의": "합의", "승인": "승인" };
  return el("div", { class: "panel ap" },
    el("div", { class: "row" }, el("h3", { style: { margin: 0, flex: 1 } }, "결재"), el("span", { class: "tag " + (sg === "승인" ? "ok" : sg === "반려" ? "bad" : sg === "작성 중" ? "gray" : "warn") }, sg)),
    el("div", { class: "ap-line" }, ap.line.map(x => el("div", { class: "ap-step" + (x.result === "완료" ? " done" : x.result === "반려" ? " rej" : x === cur ? " cur" : "") },
      el("div", { class: "ap-s" }, x.step), el("div", { class: "ap-r small muted" }, x.role), el("div", { class: "ap-n" }, x.name || "미지정"),
      el("div", { class: "ap-at small" }, x.result ? `${x.result} ${x.at.slice(5)}` : x === cur ? "차례" : ""), x.memo ? el("div", { class: "small muted" }, x.memo) : null))),
    sg === "승인" ? el("div", { class: "row" }, el("span", { class: "small muted" }, "승인되어 평가가 확정되었습니다."), el("button", { class: "small", onclick: () => go("reset") }, "다시 작성(결재 새로)"))
      : ap.rejected ? el("div", { class: "row" }, el("span", { class: "small", style: { color: "var(--bad)" } }, "반려되었습니다. 고친 뒤 다시 작성해 결재를 올리세요."), name, el("button", { class: "primary", onclick: () => go("reset") }, "다시 작성"))
      : el("div", { class: "row" }, name, memo, el("button", { class: "primary", id: "ap-next", onclick: () => go("next") }, label[cur.step]),
        cur.step !== "작성" ? el("button", { onclick: () => go("reject") }, "반려") : null),
    el("div", { class: "small muted" }, "작성 → 검토 요청은 확인 안 한 위험요인이 없어야, 승인은 위험성 높음 항목의 감소대책을 마쳐야 할 수 있습니다. 결재선은 '안전 성과' 탭의 공종별 담당자 표에서 정합니다."),
    ap.history.length ? el("details", {}, el("summary", { class: "small" }, `결재 이력 ${ap.history.length}건`), ap.history.slice().reverse().map(h => el("div", { class: "small" }, `${h.at} · ${h.name || "-"} · ${h.what}${h.memo ? " · " + h.memo : ""}`))) : null);
}

// ------------------------------------------------------------ 목록·상세
function renderList() {
  const box = $("#list-box");
  box.innerHTML = "";
  if (!S.assessments.length) { box.append(el("div", { class: "panel empty" }, "평가가 없습니다.")); return; }
  box.append(el("div", { class: "panel" }, el("h2", {}, "평가 목록"),
    el("div", { class: "tbl-scroll" }, el("table", { class: "t list-t" }, el("tr", {}, ["", "평가일", "시설", "작업", "최고 위험성", "미완료 조치", "결재", "상태"].map(h => el("th", {}, h))),
      S.assessments.map(a => el("tr", {}, el("td", {}, el("button", { class: "small", "aria-label": `${a.fac} ${a.work} 평가 열기`, onclick: () => openA(a.id) }, "열기")),
        el("td", {}, a.created), el("td", {}, a.fac), el("td", {}, a.work),
        el("td", {}, el("span", { class: "tag " + (a.top >= 6 ? "bad" : a.top >= 3 ? "warn" : "ok") }, a.top)),
        el("td", {}, a.stats.open), el("td", {}, el("span", { class: "tag " + (a.stage === "승인" ? "ok" : a.stage === "반려" ? "bad" : a.stage === "작성 중" ? "gray" : "warn") }, a.stage)), el("td", {}, a.status, a.reassess ? el("span", { class: "tag warn", style: { marginLeft: "6px" } }, "수시평가 필요") : null)))))));
}

async function openA(id) {
  CUR = await api("GET", `/api/assess/${id}`);
  $("#tab-list").append($("#detail"));
  GO("list");
  renderDetail();
  $("#detail").scrollIntoView({ behavior: "smooth" });
}

async function save(patch) {
  CUR = await api("POST", `/api/assess/${CUR.id}/update`, patch);
  renderDetail();
  S = await api("GET", "/api/state"); renderDash(); renderList();
}

function renderDetail() {
  const a = CUR, st = a.stats, box = $("#detail");
  box.innerHTML = "";
  const c = a.conditions;
  const condChips = [c.height != null ? `높이 ${c.height}m` : null, c.alone ? "1인 작업" : null, c.people ? `${c.people}인 작업` : null,
    c.temp != null ? `체감온도 ${c.temp}℃` : null, c.open ? "운영 중" : null, c.outdoor ? "실외" : null].filter(Boolean);
  box.append(el("div", { class: "panel" },
    el("div", { class: "row" }, el("h2", { style: { flex: 1, margin: 0 } }, `${a.fac} · ${a.work}`),
      el("span", { class: "small muted" }, `${a.created} · ${a.engine} · ${a.status}`)),
    el("p", { class: "small" }, a.text),
    condChips.length ? el("div", { class: "small muted" }, "읽은 조건: ", condChips.map(x => el("span", { class: "chip" }, x))) : null,
    el("div", { class: "verdict " + (st.empty ? "warn" : st.ready ? "ok" : "bad"), style: { marginTop: "12px" } },
      el("div", {}, el("div", { class: "big" }, st.empty ? "평가가 끝나지 않음" : st.ready ? "작업 시작 가능" : "작업 전 조치 필요"),
        el("div", { class: "desc" }, st.empty ? "평가표에 들어간 위험요인이 없습니다. 아래 '빠진 위험요인 추가'로 위험요인을 넣어 주세요." : st.ready ? "작업 전에 끝내야 할 감소대책을 모두 마쳤습니다. 작업 중 관리 항목은 계속 지켜 주세요."
          : [st.blocked.length ? `위험성 ${a.rules.high} 이상인 ${st.blocked.join(", ")}의 감소대책을 마치기 전에는 작업을 시작하지 않습니다(규정 기준). ` : "",
            (st.weather_stops || []).length ? `기상특보: ${st.weather_stops.join(" / ")}(산업안전보건기준에 관한 규칙, 악천후·강풍 시 작업 중지).` : ""].join("")))),
    a.weather ? wxBox(a.weather, el("button", { class: "small", style: { marginTop: "6px" }, onclick: async () => { CUR = await api("POST", `/api/assess/${a.id}/weather`, {}); renderDetail(); } }, "날씨 다시 확인")) : null,
    a.questions.map(q => el("div", { class: "q" }, "확인 필요: " + q)),
    a.permits.length ? el("div", { class: "q", style: { background: "var(--bad-soft)", color: "var(--bad)" } }, "작업 전 허가: ",
      a.permits.map(p => el("span", {}, p.name, " ", basisChip(p.basis)))) : null,
    a.reassess.length ? el("div", { class: "q" }, el("b", {}, "수시평가 필요: "), a.reassess.map(r => el("div", {}, `${r.date} ${r.kind || "아차사고"} - ${r.text} `, basisChip(r.basis))),
      el("button", { class: "small", style: { marginTop: "6px" }, onclick: () => save({ clear_reassess: true }) }, "다시 평가했음(표시 지우기)")) : null,
    a.notes.length ? el("div", { class: "small muted", style: { marginTop: "6px" } }, a.notes.map(n => el("div", {}, "※ " + n))) : null,
    a.photos.length ? el("div", { class: "photos", style: { marginTop: "10px" } }, a.photos.map(p => el("img", { src: `/api/photo/${p}`, alt: "현장 사진" }))) : null,
    el("div", { class: "row", style: { marginTop: "14px" } },
      el("span", { class: "small muted" }, "위험성평가표:"), exportButtons(`/api/assess/${a.id}/export`),
      el("button", { class: "primary", onclick: () => openSheetEditor(true) }, "미리보기·고쳐서 내려받기"),
      el("button", { onclick: () => download(`/api/assess/${a.id}/xlsx`, {}) }, "엑셀"),
      el("button", { onclick: showTBM }, "작업 전 회의(TBM)"),
      el("span", { style: { flex: 1 } }),
      el("button", { class: "danger small", title: "이 평가를 지웁니다(되돌릴 수 없음)", onclick: async () => {
        if (!confirm(`'${a.fac} · ${a.work}' 평가를 지울까요? 지우면 되돌릴 수 없습니다.`)) return;
        await api("DELETE", `/api/assess/${a.id}`); CUR = null; box.innerHTML = ""; await load(); toast("평가를 지웠습니다");
      } }, "평가 삭제"))),
    el("div", { id: "rep-edit" }));
  box.append(approvalPanel(a));

  const ls = a.method !== "3";
  const todo = it => !it.confirmed || it.measures.some(m => !m.done && (!m.owner || !m.due));
  if (a.items.length) box.append(el("div", { class: "panel method-bar" }, el("div", { class: "row" },
    el("b", {}, "평가 기법"),
    el("div", { class: "seg", role: "group", "aria-label": "평가 기법" },
      el("button", { class: ls ? "on" : "", "aria-pressed": ls, onclick: () => ls || save({ method: "LS" }) }, "빈도·강도법(가능성×중대성)"),
      el("button", { class: ls ? "" : "on", "aria-pressed": !ls, onclick: () => ls && save({ method: "3" }) }, "3단계 판단법(상·중·하)")),
    el("span", { style: { flex: 1 } }),
    el("label", { class: "small" }, el("input", { type: "checkbox", id: "only-todo", checked: ONLYTODO, onchange: e => { ONLYTODO = e.target.checked; renderDetail(); } }),
      ` 미입력만 보기(${a.items.filter(todo).length})`)),
    el("p", { class: "small muted", style: { margin: "6px 0 0" } }, ls
      ? "가능성·중대성과 개선 후 값은 현장이 직접 판단해 고칩니다. 무사히가 넣은 값은 위험요인 목록·작업 조건·아차사고로 계산한 출발점입니다."
      : "상·중·하는 현장이 직접 판단합니다. 처음 값은 빈도·강도 계산에서 옮겨 왔습니다(상은 작업 전 대책 완료).")));
  const openM = a.items.reduce((n, it) => n + it.measures.filter(m => !m.done && (!m.owner || !m.due)).length, 0);
  if (a.items.length) {
    const who = el("input", { type: "text", placeholder: "담당(예: 시설팀 김○○)", "aria-label": "한꺼번에 넣을 담당", style: { width: "200px" } });
    const when = el("input", { type: "date", "aria-label": "한꺼번에 넣을 기한" });
    box.append(el("div", { class: "panel bulk-assign" }, el("div", { class: "row" },
      el("b", {}, "담당·기한 한꺼번에 넣기"), el("span", { class: "small muted" }, `담당이나 기한이 빈 미완료 감소대책 ${openM}건`),
      el("span", { style: { flex: 1 } }), who, when,
      el("button", { class: "primary small", onclick: () => {
        if (!who.value.trim() && !when.value) { toast("담당이나 기한을 적으세요", true); return; }
        save({ items: a.items.map(it => ({ code: it.code, measures: it.measures.map(m => m.done ? {} : Object.assign({},
          who.value.trim() && !m.owner ? { owner: who.value.trim() } : {}, when.value && !m.due ? { due: when.value } : {})) })) });
        toast("빈 칸에 넣었습니다");
      } }, "빈 칸에 넣기"))));
  }

  for (const it of a.items) {
    if (ONLYTODO && !todo(it)) continue;
    const sel = (k, cur, label) => el("select", { "aria-label": label, onchange: e => save({ items: [{ code: it.code, [k]: +e.target.value }] }) },
      [1, 2, 3].map(v => el("option", { value: v, selected: cur === v }, k.startsWith("grade") ? { 3: "상", 2: "중", 1: "하" }[v] : v)));
    box.append(el("div", { class: `hz ${it.level}${it.confirmed ? "" : " unconf"}` },
      el("div", { class: "row" }, el("span", { class: "risk " + it.level }, ls ? it.R : { 3: "상", 2: "중", 1: "하" }[it.G]),
        el("div", { style: { flex: 1 } }, el("h3", {}, it.name), el("div", { class: "small muted" }, `${it.code} · ${it.type} · ${it.level_label} · 개선 후 ${it.R_after}`)),
        ls ? el("span", { class: "ls small" }, "가능성 ", sel("L", it.L, "가능성"), " 중대성 ", sel("S", it.S, "중대성"),
          el("span", { class: "after" }, " 개선 후 ", sel("La_set", it.La, "개선 후 가능성"), "×", sel("Sa_set", it.Sa, "개선 후 중대성")))
          : el("span", { class: "ls small" }, "위험성 ", sel("grade", it.G, "위험성 상중하"), el("span", { class: "after" }, " 개선 후 ", sel("grade_after", it.G_after, "개선 후 상중하"))),
        el("span", { class: "tag " + (it.by === "낱말" || it.by === "작업 분류" ? "info" : it.by === "사진(모델)" ? "warn" : "gray") }, it.by)),
      !it.confirmed ? el("div", { class: "q" }, `사진에서 모델이 본 위험입니다: "${it.photo || it.quote}". 현장에서 확인한 뒤 평가표에 넣으세요. `,
        el("button", { class: "small primary", onclick: () => save({ items: [{ code: it.code, confirmed: true }] }) }, "확인함"),
        " ", el("button", { class: "small", onclick: async () => { CUR = await api("POST", `/api/assess/${a.id}/remove`, { code: it.code }); renderDetail(); } }, "아님(빼기)")) : null,
      (it.steps || []).length ? el("div", { class: "reason" }, "작업 단계: ", it.steps.map(x => el("span", { class: "chip", title: x.situation, onclick: () => showSource(x.src) }, `${x.step} - ${x.situation}`))) : null,
      it.quote && it.by !== "사진(모델)" && it.by !== "작업 분류" ? el("div", { class: "reason" }, `근거 문구: "${it.quote}"`) : null,
      it.photo && it.by !== "사진(모델)" ? el("div", { class: "reason" }, `사진에서도 확인(모델): ${it.photo}`) : null,
      it.reasons.map(r => el("div", { class: "reason" }, "· " + r.text, " ", r.src ? citeChips([r.src]) : null)),
      el("div", { style: { marginTop: "8px" } }, it.measures.map((m, i) => el("div", { class: "meas" + (m.done ? " done" : "") },
        el("input", { type: "checkbox", checked: m.done, onchange: e => save({ items: [{ code: it.code, measures: it.measures.map((_, j) => j === i ? { done: e.target.checked } : {}) }] }) }),
        el("span", {}, kindTag(m.kind), " ", m.text),
        el("input", { type: "text", value: m.owner, placeholder: "담당", onchange: e => save({ items: [{ code: it.code, measures: it.measures.map((_, j) => j === i ? { owner: e.target.value } : {}) }] }) }),
        el("input", { type: "date", value: m.due, onchange: e => save({ items: [{ code: it.code, measures: it.measures.map((_, j) => j === i ? { due: e.target.value } : {}) }] }) })))),
      el("div", { class: "row small", style: { marginTop: "8px" } }, el("span", { class: "muted" }, "관련 기준: " + (it.law || "-")), basisChip(it.basis),
        citeChips([it.src]), it.law ? el("button", { class: "small", onclick: e => toggleLaw(e.target, it.code) }, "법령 원문") : null, el("span", { style: { flex: 1 } }),
        el("button", { class: "small", onclick: async () => { CUR = await api("POST", `/api/assess/${a.id}/remove`, { code: it.code }); renderDetail(); } }, "빼기"))));
  }
  const have = new Set(a.items.map(i => i.code));
  const add = el("select", { id: "add-code" }, el("option", { value: "" }, "위험요인 고르기…"), S.hazards.filter(h => !have.has(h.code)).map(h => el("option", { value: h.code }, `${h.code} ${h.name}`)));
  const word = el("input", { id: "add-word", type: "text", placeholder: "작업 설명 속 어떤 말 때문인가요? (예: 트러스)", style: { flex: 1, minWidth: "260px" } });
  box.append(el("div", { class: "panel" }, el("h3", {}, "빠진 위험요인 추가"),
    el("p", { class: "small muted" }, "목록의 낱말로 못 찾은 위험을 넣습니다. 이 작업 설명에 있는 말을 함께 적으면 그 말을 위험요인의 '찾는 낱말'에 보태, 다음 평가부터 자동으로 찾습니다(원본 엑셀은 그대로, 보탠 낱말은 '기준·자료'에서 뺄 수 있음)."),
    el("div", { class: "row" }, add, word,
      el("button", { class: "primary", id: "add-btn", onclick: async () => {
        if (!add.value) { toast("위험요인을 고르세요", true); return; }
        CUR = await api("POST", `/api/assess/${a.id}/add`, { code: add.value, word: word.value });
        if (word.value) toast(`'${word.value}'를 찾는 낱말에 보탰습니다`);
        S = await api("GET", "/api/state"); renderDetail(); renderLib(); renderDash(); renderList();
      } }, "추가"))));
}

async function showTBM() {
  const r = await api("GET", `/api/assess/${CUR.id}/tbm`);
  const list = el("ol", { class: "tbm" }, r.lines.map(l => el("li", {}, l)));
  const mode = el("div", { class: "small muted" }, "규칙 문안");
  const btn = el("button", { class: "small primary", onclick: async () => {
    busy(btn, true, "문안 쓰는 중");
    try { const x = await api("POST", `/api/assess/${CUR.id}/tbm/ai`); list.replaceChildren(...x.lines.map(l => el("li", {}, l))); mode.textContent = x.mode + (x.dropped ? " · " + x.dropped : ""); }
    finally { busy(btn, false); }
  } }, S.llm ? "AI로 말하기 쉽게 다시 쓰기" : "규칙 문안(모델 미연결)");
  modal("작업 전 안전점검회의(TBM) 낭독 문안",
    el("div", { class: "row" }, btn, mode), list,
    r.basis ? el("p", { class: "small muted" }, "근거: ", basisChip(r.basis)) : null,
    el("div", { class: "row" }, el("span", { class: "small muted" }, "서명 기록지:"), exportButtons(`/api/assess/${CUR.id}/tbm`)));
}

// ------------------------------------------------------------ 오늘 작업 브리핑(기상청·재난문자·아차사고 종합 해석)
const BR_LV = { stop: "bad", fix: "bad", care: "warn", go: "ok" };
async function renderBrief() {
  const box = $("#brief");
  if (!box) return;
  box.replaceChildren(el("div", { class: "panel" }, el("span", { class: "spinner" }), " 날씨·재난문자와 견주는 중"));
  let r;
  try { r = await api("GET", "/api/briefing"); } catch (e) { box.replaceChildren(); return; }
  const txt = el("div", { class: "ans", style: { marginTop: "10px", whiteSpace: "pre-line" } }, r.ai ? r.ai.text : r.rule);
  const mode = el("div", { class: "small muted" }, r.ai ? r.ai.mode + (r.ai.dropped ? " · " + r.ai.dropped : "") : "규칙 기반");
  const btn = el("button", { class: "primary", onclick: async () => {
    busy(btn, true, "브리핑 쓰는 중");
    try { const x = await api("POST", "/api/briefing/ai"); txt.textContent = x.text; mode.textContent = x.mode + (x.dropped ? " · " + x.dropped : ""); }
    finally { busy(btn, false); }
  } }, S.llm ? "AI 브리핑 쓰기" : "브리핑(규칙)");
  const chip = (on, name) => el("span", { class: "tag " + (on ? "ok" : "gray") }, name + (on ? " 실시간" : " 예시 자료"));
  const w = r.weather;
  box.replaceChildren(el("div", { class: "panel" },
    el("div", { class: "row" }, el("div", { style: { flex: 1 } }, el("h2", { style: { margin: 0 } }, "오늘 작업 브리핑"), el("p", { class: "tagline", style: { margin: "2px 0 0" } }, "재난 앞에서도 안전하게, 언제나 무사히")), btn),
    el("p", { class: "small muted" }, `기상청 체감온도·기상특보, 긴급재난문자, 같은 작업의 아차사고, 끝나지 않은 작업 전 조치를 평가마다 엮어 오늘 멈출 작업과 조심할 작업을 고릅니다. 판정은 규칙(특보 작업 중지, 체감온도 ${r.th.heat_rest}℃·${r.th.heat_stop}℃ 기준)으로 하고, AI는 그 결과로 우선순위를 씁니다.`),
    el("div", { class: "row", style: { gap: "6px", flexWrap: "wrap" } }, chip(r.src.weather, "기상청"), chip(r.src.messages, "재난문자"),
      el("span", { class: "tag info" }, `아차사고 ${r.src.incidents}건`),
      el("span", { class: "small muted" }, `체감온도 ${w.feel}℃ · 특보 ${(w.active || []).map(x => x.kind + x.level).join(", ") || "없음"}`)),
    txt, mode,
    r.rows.length ? el("div", { class: "tbl-scroll", style: { marginTop: "10px" } }, el("table", { class: "t" },
      el("tr", {}, ["판정", "작업", "최고 위험성", "이유", ""].map(h => el("th", {}, h))),
      ...r.rows.map(x => el("tr", {}, el("td", {}, el("span", { class: "tag " + BR_LV[x.level] }, x.label)), el("td", {}, `${x.fac} · ${x.work}`),
        el("td", {}, x.top), el("td", { class: "small" }, x.why.join(" / ")), el("td", {}, el("button", { class: "small", onclick: () => openA(x.id) }, "열기")))))) : null));
}

// ------------------------------------------------------------ 물어보기(이어 묻기)
const EX = ["사다리 작업 안전 기준은?", "폭염 때 실외 작업은 어떻게 해?", "밀폐공간 들어가기 전에 뭘 해야 해?", "오늘 시작 못 하는 작업 있어?", "약품 다룰 때 조심할 건?", "위험성 몇 점부터 작업 전에 조치해야 해?", "산업안전보건법 제38조는?", "중대재해처벌법 경영책임자 의무는?"];
let CONV = [];
function askTurn(t) {
  const r = t.r;
  if (!r) return el("div", { class: "panel chat-turn" }, el("div", { class: "chat-q" }, t.q), el("div", {}, el("span", { class: "spinner" }), " 규정·위험요인에서 찾는 중"));
  return el("div", { class: "panel chat-turn" },
    el("div", { class: "row" }, el("div", { class: "chat-q", style: { flex: 1 } }, t.q), el("span", { class: "tag " + (/모델/.test(r.mode) ? "ok" : "gray") }, r.mode)),
    r.carried ? el("p", { class: "small muted" }, `앞 질문의 '${r.carried}'를 이어서 봤습니다.`) : null,
    el("div", { class: "small", style: { marginTop: "6px", color: r.grounded ? "var(--muted)" : "var(--warn)" } },
      r.grounded ? "근거 확인: " + Object.entries(r.grounds || {}).map(([k, v]) => `${k} ${v}건`).join(" · ") : "근거를 찾지 못해 추측으로 답하지 않았습니다."),
    el("div", { class: "ans", style: { marginTop: "8px", whiteSpace: "pre-line" } }, r.answer),
    r.general && /모델/.test(r.mode) ? el("p", { class: "small muted" }, "※ 질문에 딱 맞는 조문·위험요인이 없어 기관 위험요인 목록 전체로 답했습니다.") : null,
    r.dropped ? el("p", { class: "small", style: { color: "var(--warn)" } }, "※ " + r.dropped) : null,
    r.masked && r.masked.length ? el("p", { class: "small muted" }, `※ 질문의 개인정보(${r.masked.join(", ")})를 ○○○로 가린 뒤 처리했습니다.`) : null,
    r.sources.length ? el("div", { class: "small muted", style: { marginTop: "8px" } }, "근거: ", citeChips(r.sources)) : null,
    r.facts.length ? el("details", { style: { marginTop: "8px" } }, el("summary", { class: "small muted" }, `답에 쓴 사실 ${r.facts.length}개 (숫자·기준은 모두 여기서만 가져옴)`),
      el("ul", { class: "small" }, r.facts.map(f => el("li", {}, f)))) : null);
}
function drawConv() {
  $("#ask-out").replaceChildren(...CONV.map(askTurn),
    CONV.length ? el("div", { class: "row small muted", style: { justifyContent: "space-between" } },
      el("span", {}, `이어서 물어보면 앞 질문의 위험요인을 이어받습니다. 예: "그럼 2m 넘으면?"`),
      el("button", { class: "small", onclick: () => { CONV = []; drawConv(); } }, "새 대화")) : null);
}
async function ask(q) {
  q = (q || $("#q").value).trim();
  if (!q) return;
  $("#q").value = "";
  const history = CONV.filter(t => t.r).slice(-4).map(t => ({ q: t.q, a: t.r.answer }));
  const turn = { q };
  CONV.push(turn); drawConv();
  try { turn.r = await api("POST", "/api/ask", { q, history }); }
  catch (e) { CONV.pop(); $("#q").value = q; drawConv(); throw e; }
  drawConv();
  const last = $("#ask-out").lastElementChild.previousElementSibling;
  if (last) last.scrollIntoView({ behavior: "smooth", block: "start" });
}

// ------------------------------------------------------------ 평가표 미리보기·고치기·사진(좌우 분할)
let REP = null, REPX = null;
function sheetCtx() {
  return { sel: "#rep-edit", title: "위험성평가표 고치기", url: `/api/assess/${CUR.id}/export`, open: openSheetEditor,
    desc: `위험성평가 결과로 만든 평가표 초안입니다${S.llm ? ". AI가 쓴 문장은 평가 결과와 숫자·위험요인 코드를 대조해, 근거에 없는 것이 있으면 버리고 규칙 문장을 씁니다" : ". 모델을 연결하면 AI가 해설·종합 의견을 씁니다"}. 고치면 오른쪽 미리보기에 바로 반영됩니다.`,
    tools: () => [el("button", { class: "small", onclick: e => aiExplainItems(e.currentTarget) }, S.llm ? "위험요인마다 AI 해설 넣기" : "위험요인 해설 넣기(규칙)"),
      el("button", { class: "small", onclick: e => aiOpinion(e.currentTarget) }, S.llm ? "AI로 종합 의견 쓰기" : "종합 의견 넣기(규칙)"),
      el("button", { class: "small", onclick: () => addPhotos(REP.length) }, "현장 사진 넣기(맨 끝)")] };
}
async function openSheetEditor(reset) {
  if (!REP || reset || REPX?.sel !== "#rep-edit") REP = (await api("GET", `/api/assess/${CUR.id}/preview`)).blocks;
  REPX = sheetCtx();
  drawReportEditor();
  $("#rep-edit").scrollIntoView({ behavior: "smooth", block: "start" });
}
function readImage(file) {
  return new Promise((ok, bad) => {
    if (!/^image\/(png|jpeg|gif)$/.test(file.type)) return bad(new Error("PNG·JPG·GIF 사진만 넣을 수 있습니다"));
    if (file.size > 8 * 1024 * 1024) return bad(new Error("사진 한 장은 8MB까지 넣을 수 있습니다"));
    const r = new FileReader(); r.onload = () => ok(r.result); r.onerror = () => bad(r.error); r.readAsDataURL(file);
  });
}
function addPhotos(at) {
  const inp = el("input", { type: "file", accept: "image/png,image/jpeg,image/gif", multiple: true, hidden: true, onchange: async () => {
    try {
      const imgs = [];
      for (const f of inp.files) imgs.push(["image", await readImage(f), f.name.replace(/\.[^.]+$/, "")]);
      REP.splice(at, 0, ...imgs); drawReportEditor(); toast(`사진 ${imgs.length}장을 넣었습니다`);
    } catch (e) { toast(e.message, true); }
    inp.remove();
  } });
  document.body.append(inp); inp.click();
}
const BK_LABEL = { title: "제목", h1: "장 제목", h2: "소제목", h3: "소제목", p: "문단", bullet: "○ 항목", note: "※ 참고", summary: "핵심 요약", table: "표", image: "사진" };
function reportPreview() {
  const go = i => () => { const t = document.getElementById("rbe-" + i); if (t) { t.scrollIntoView({ behavior: "smooth", block: "center" }); const f = t.querySelector("textarea,input"); if (f) f.focus({ preventScroll: true }); } };
  return el("div", { class: "rep-doc" }, ...REP.map((b, i) => {
    const k = b[0];
    let body;
    if (k === "title") body = el("div", { class: "rb-title" }, b[1]);
    else if (k === "h1" || k === "h2" || k === "h3") body = el("div", { class: "rb-h2" }, "□ " + b[1]);
    else if (k === "bullet") body = el("div", { class: "rb-bullet" }, "○ " + b[1]);
    else if (k === "note") body = el("div", { class: "rb-note" }, b[1]);
    else if (k === "p") body = el("div", { class: "rb-p" }, b[1]);
    else if (k === "summary") body = el("div", { class: "rb-summary" }, ...b[1].map(x => el("div", { class: "rb-bullet" }, "○ " + x)));
    else if (k === "table") body = el("div", { class: "tbl-scroll" }, el("table", { class: "rb-table" }, el("tr", {}, ...b[1].map(h => el("th", {}, h))), ...b[2].map(r => el("tr", {}, ...r.map(c => el("td", { style: { whiteSpace: "pre-line" } }, String(c)))))));
    else if (k === "image") body = el("figure", { class: "rb-fig" }, el("img", { src: b[1], alt: b[2] || "현장 사진" }), b[2] ? el("figcaption", {}, "<그림> " + b[2]) : null);
    return el("div", { class: "rb", onclick: go(i), title: "눌러서 왼쪽에서 고치기" }, body);
  }));
}
function refreshPreview() {
  const pv = $("#rep-pv");
  if (!pv) return;
  const top = pv.scrollTop;
  pv.replaceChildren(reportPreview());
  pv.scrollTop = top;
}
function reportFields() {
  const area = (val, set, rows) => {
    const t = el("textarea", { rows: rows || Math.min(8, Math.max(2, Math.ceil(String(val).length / 46))) }, String(val));
    t.addEventListener("input", () => { set(t.value); refreshPreview(); });
    return t;
  };
  const line = (val, set) => { const t = el("input", { value: val }); t.addEventListener("input", () => { set(t.value); refreshPreview(); }); return t; };
  const tools = i => el("span", { class: "rbe-tools" },
    S.llm && ["p", "note", "bullet"].includes(REP[i][0]) ? el("button", { class: "small", title: "뜻과 숫자는 그대로 두고 공문체로 다듬습니다", onclick: e => aiPolish(i, e.currentTarget) }, "AI 다듬기") : null,
    el("button", { class: "icon-btn", title: "위로", disabled: i === 0, onclick: () => { [REP[i - 1], REP[i]] = [REP[i], REP[i - 1]]; drawReportEditor(); } }, "↑"),
    el("button", { class: "icon-btn", title: "아래로", disabled: i === REP.length - 1, onclick: () => { [REP[i + 1], REP[i]] = [REP[i], REP[i + 1]]; drawReportEditor(); } }, "↓"),
    el("button", { class: "small", onclick: () => { REP.splice(i + 1, 0, ["p", ""]); drawReportEditor(); } }, "+ 문단"),
    el("button", { class: "small", onclick: () => addPhotos(i + 1) }, "+ 사진"),
    el("button", { class: "small danger", onclick: () => { REP.splice(i, 1); drawReportEditor(); } }, "삭제"));
  return REP.map((b, i) => {
    const k = b[0];
    let body;
    if (k === "title" || k === "h1" || k === "h2" || k === "h3") body = line(b[1], v => (b[1] = v));
    else if (k === "p" || k === "bullet" || k === "note") body = area(b[1], v => (b[1] = v));
    else if (k === "summary") body = area(b[1].join("\n"), v => (b[1] = v.split("\n")), b[1].length + 1);
    else if (k === "table") body = el("div", { class: "tbl-scroll" }, el("table", { class: "rbe-table" },
      el("tr", {}, ...b[1].map((h, c) => el("th", {}, line(h, v => (b[1][c] = v))))),
      ...b[2].map(r => el("tr", {}, ...r.map((cv, c) => el("td", {}, line(String(cv), v => (r[c] = v))))))));
    else if (k === "image") body = el("div", { class: "row", style: { gap: "10px", alignItems: "center" } }, el("img", { class: "rbe-thumb", src: b[1], alt: "" }),
      el("label", { style: { flex: 1 } }, el("div", { class: "small muted" }, "그림 설명"), line(b[2] || "", v => (b[2] = v))));
    return el("div", { class: "rbe", id: "rbe-" + i }, el("div", { class: "rbe-head" }, el("span", { class: "tag gray" }, BK_LABEL[k] || k), el("span", { style: { flex: 1 } }), tools(i)), body);
  });
}
async function aiPolish(i, btn) {
  busy(btn, true, "다듬는 중");
  try {
    const r = await api("POST", "/api/report/polish", { text: REP[i][1] });
    if (/모델/.test(r.mode)) { REP[i][1] = r.text; toast("문단을 다듬었습니다(사실 대조 통과)"); drawReportEditor(); } else toast(r.dropped || "원문을 그대로 둡니다");
  } finally { busy(btn, false); }
}
async function aiExplainItems(btn) {
  const items = CUR.items.filter(i => i.confirmed);
  if (!items.length) { toast("평가표에 들어간 위험요인이 없습니다"); return; }
  const sec = [["h2", "위험요인 해설"]];
  let ok = 0;
  try {
    for (const [n, it] of items.entries()) {
      busy(btn, true, `해설 쓰는 중 ${n + 1}/${items.length}`);
      const r = await api("POST", `/api/assess/${CUR.id}/explain`, { code: it.code });
      sec.push(["bullet", `${n + 1}. ${it.name}: ${r.text}`]);
      if (/모델/.test(r.mode)) ok++;
    }
    const old = REP.findIndex(b => b[0] === "h2" && b[1] === "위험요인 해설");
    if (old >= 0) { let e = old + 1; while (e < REP.length && REP[e][0] === "bullet") e++; REP.splice(old, e - old, ...sec); }
    else { const at = REP.findIndex(b => b[0] === "h2" && /판단 이유/.test(b[1])); REP.splice(at >= 0 ? at : 6, 0, ...sec); }
    toast(`위험요인 ${items.length}건 해설을 넣었습니다` + (ok < items.length ? ` (모델 ${ok}건, 규칙 ${items.length - ok}건)` : ""));
    drawReportEditor();
  } finally { busy(btn, false); }
}
async function aiOpinion(btn) {
  busy(btn, true, "종합 의견 쓰는 중");
  try {
    const r = await api("POST", `/api/assess/${CUR.id}/opinion`);
    const sec = [["h2", "종합 의견"], ...r.lines.map(x => ["bullet", x])];
    const old = REP.findIndex(b => b[0] === "h2" && b[1] === "종합 의견");
    if (old >= 0) { let e = old + 1; while (e < REP.length && REP[e][0] === "bullet") e++; REP.splice(old, e - old, ...sec); }
    else { const at = REP.findIndex(b => b[0] === "h2" && b[1] === "평가 참여자 확인"); REP.splice(at >= 0 ? at : REP.length, 0, ...sec); }
    toast(`종합 의견 ${r.lines.length}개 항목을 넣었습니다(${r.mode})` + (r.dropped ? " · " + r.dropped : "")); drawReportEditor();
  } finally { busy(btn, false); }
}
function drawReportEditor() {
  const host = REPX && $(REPX.sel);
  if (!host || !REP) return;
  const nImg = REP.filter(b => b[0] === "image").length;
  const left = el("div", { class: "rep-left" },
    el("div", { class: "rep-ai" }, el("b", {}, "AI 초안"), el("p", { class: "small muted" }, REPX.desc),
      el("div", { class: "row", style: { gap: "6px", flexWrap: "wrap" } }, ...REPX.tools())),
    ...reportFields());
  const right = el("div", { class: "rep-right" }, el("div", { class: "rep-right-head small muted" }, `미리보기 · 블록을 누르면 왼쪽 칸으로 이동${nImg ? ` · 사진 ${nImg}장` : ""}`), el("div", { id: "rep-pv" }, reportPreview()));
  host.replaceChildren(el("div", { class: "panel" },
    el("div", { class: "row" }, el("h2", { style: { flex: 1, margin: 0 } }, REPX.title),
      el("span", { class: "small muted" }, "내려받기:"), exportButtons(REPX.url, () => ({ blocks: REP })),
      el("button", { class: "small", onclick: () => REPX.open(true) }, "처음 내용으로"),
      el("button", { class: "small", onclick: () => { REP = null; host.replaceChildren(); } }, "닫기")),
    el("div", { class: "rep-split" }, left, right)));
}

// ------------------------------------------------------------ 아차사고
function incResult(r) {
  return el("div", { class: "verdict " + (r.hits.length ? "warn" : "ok"), style: { marginTop: "14px" } }, el("div", {},
    el("div", { class: "big" }, r.hits.length ? `수시평가 필요 ${r.hits.length}건` : "등록했습니다"),
    el("div", { class: "desc" }, "분류한 위험요인: " + (r.codes.map(c => c.name).join(", ") || "없음"),
      r.masked && r.masked.length ? el("div", {}, `개인정보(${r.masked.join(", ")})를 ○○○로 가려 저장했습니다.`) : null,
      r.hits.length ? el("div", {}, "다시 평가할 작업: ", r.hits.map(h => el("span", { class: "chip", onclick: () => openA(h.id) }, `${h.fac} · ${h.work}`)), " ", basisChip(r.basis)) : null)));
}

function renderInc() {
  const box = $("#tab-inc");
  box.innerHTML = "";
  const f = { date: el("input", { type: "date", value: S.today }), fac: el("input", { class: "wide", placeholder: "예: 종합체육센터" }),
    work: el("input", { class: "wide", placeholder: "예: 수영장 염소 약품 투입" }), text: el("textarea", { class: "wide", rows: 2, placeholder: "무슨 일이 있었나요? 예: 약품을 붓다가 튀어 눈 근처에 묻을 뻔함" }),
    result: el("input", { class: "wide", placeholder: "예: 다침 없음" }) };
  const out = el("div");
  if (LASTINC) out.append(incResult(LASTINC));
  box.append(el("div", { class: "panel" }, el("h2", {}, "아차사고 등록"),
    el("p", { class: "small muted" }, "등록하면 같은 시설·같은 작업의 기존 평가에 '수시평가 필요'를 표시하고, 앞으로 그 작업을 평가할 때 가능성을 올리는 근거로 씁니다."),
    el("div", { class: "grid3" }, el("div", {}, el("label", { class: "f" }, "발생일"), f.date), el("div", {}, el("label", { class: "f" }, "시설"), f.fac), el("div", {}, el("label", { class: "f" }, "작업"), f.work)),
    el("label", { class: "f" }, "내용"), f.text, el("label", { class: "f" }, "결과"), f.result,
    el("div", { class: "row", style: { marginTop: "12px" } },
      el("button", { class: "primary", onclick: async () => {
        const r = await api("POST", "/api/incidents", { date: f.date.value, fac: f.fac.value, work: f.work.value, text: f.text.value, result: f.result.value });
        LASTINC = r;
        await load();
      } }, "등록"),
      el("button", { onclick: () => { f.fac.value = "종합체육센터"; f.work.value = "수영장 염소 약품 투입"; f.text.value = "약품 투입기 호스가 빠져 약품이 바닥에 흘렀고, 닦다가 냄새를 맡고 기침함. 환기팬이 꺼져 있었음"; f.result.value = "다침 없음(휴식)"; } }, "예시 채우기")),
    out));
  const stTag = f => el("span", { class: "tag " + (f.status === "완료" ? "ok" : f.status === "조치 중" ? "warn" : "gray") }, f.status + (f.open ? ` · 남은 조치 ${f.open}` : ""));
  box.append(el("div", { class: "panel" }, el("h3", {}, `아차사고 기록 ${S.incidents.length}건`),
    el("p", { class: "small muted" }, "'조치·결과보고'를 누르면 조치 기록·조치 전후 사진을 남기고, 결과보고서를 미리 보며 고쳐 한글·워드로 받습니다."),
    el("div", { class: "tbl-scroll" }, el("table", { class: "t" }, el("tr", {}, ["발생일", "시설", "작업", "내용", "분류", "처리", "출처", ""].map(h => el("th", {}, h))),
      S.incidents.map(i => el("tr", {}, el("td", {}, i.date), el("td", {}, i.fac), el("td", {}, i.work), el("td", {}, i.text),
        el("td", {}, (i.codes || []).join(", ")), el("td", {}, stTag(i.fu)), el("td", {}, i.src ? citeChips([i.src]) : el("span", { class: "tag info" }, "화면 등록")),
        el("td", {}, el("button", { class: "small inc-open", onclick: () => openInc(i.id) }, "조치·결과보고"))))))));
  box.append(el("div", { id: "inc-detail" }), el("div", { id: "inc-rep" }));
  if (INC) drawInc();
  if (INC && REP && REPX?.sel === "#inc-rep") drawReportEditor();
}

// ------------------------------------------------------------ 아차사고 조치·결과보고
let INC = null;
async function openInc(id) {
  INC = await api("GET", `/api/incidents/${id}`);
  if (REPX?.sel === "#inc-rep") REP = null;
  drawInc();
  $("#inc-detail").scrollIntoView({ behavior: "smooth", block: "start" });
}
async function saveInc(patch, msg) {
  INC = await api("POST", `/api/incidents/${INC.incident.id}/followup`, patch);
  S = await api("GET", "/api/state");
  renderInc(); renderDash();
  if (msg) toast(msg);
}
function drawInc() {
  const host = $("#inc-detail");
  if (!host || !INC) return;
  const { incident: i, followup: f, hazards, related } = INC;
  const acts = f.actions.map(m => ({ ...m }));
  const rows = el("div");
  const drawActs = () => rows.replaceChildren(...acts.map((m, n) => el("div", { class: "row inc-act", style: { gap: "8px", alignItems: "center", marginBottom: "6px" } },
    el("input", { type: "checkbox", checked: m.done, title: "완료", onchange: e => (m.done = e.target.checked) }),
    el("input", { value: m.text, placeholder: "조치 내용", style: { flex: 3 }, oninput: e => (m.text = e.target.value) }),
    el("input", { value: m.owner, placeholder: "담당", style: { flex: 1 }, oninput: e => (m.owner = e.target.value) }),
    el("input", { type: "date", value: m.due, style: { flex: 1 }, oninput: e => (m.due = e.target.value) }),
    m.completed ? el("span", { class: "small muted" }, "완료 " + m.completed) : null,
    el("button", { class: "small danger", onclick: () => { acts.splice(n, 1); drawActs(); } }, "삭제"))));
  drawActs();
  const cause = el("textarea", { class: "wide", rows: 3, placeholder: "비워 두면 보고서에 규칙으로 만든 원인 초안이 들어갑니다" }, f.cause);
  const body = () => ({ actions: acts.filter(m => m.text.trim()), cause: cause.value });
  const photoBtn = stage => {
    const inp = el("input", { type: "file", accept: "image/png,image/jpeg", multiple: true, hidden: true, onchange: async () => {
      try {
        await saveInc(body());
        for (const x of await readFiles([...inp.files].slice(0, 4))) INC = await api("POST", `/api/incidents/${i.id}/photo`, { name: x.path, b64: x.b64, stage });
        S = await api("GET", "/api/state"); renderInc(); toast(`조치 ${stage === "before" ? "전" : "후"} 사진을 넣었습니다`);
      } catch (e) { toast(e.message, true); }
    } });
    return el("span", {}, el("button", { class: "small", onclick: () => inp.click() }, `+ 조치 ${stage === "before" ? "전" : "후"} 사진`), inp);
  };
  host.replaceChildren(el("div", { class: "panel inc-panel" },
    el("div", { class: "row" }, el("h2", { style: { flex: 1, margin: 0 } }, `조치 기록 · ${i.fac} ${i.work}`),
      el("span", { class: "small muted" }, "처리 상태"),
      el("select", { id: "inc-status", onchange: async e => { try { await saveInc({ ...body(), status: e.target.value }, e.target.value === "완료" ? "완료했습니다. 같은 작업 평가의 감소대책에 반영했습니다" : "상태를 바꿨습니다"); } catch (er) { e.target.value = f.status; toast(er.message, true); } } },
        ...["접수", "조치 중", "완료"].map(x => el("option", { value: x, selected: x === f.status }, x))),
      el("button", { class: "small", onclick: () => { INC = null; host.replaceChildren(); } }, "닫기")),
    el("p", { class: "small" }, el("b", {}, i.date + " "), i.text, i.result ? ` (결과: ${i.result})` : ""),
    el("div", { class: "row", style: { gap: "6px", flexWrap: "wrap" } }, el("span", { class: "small muted" }, "분류한 위험요인"),
      ...(hazards.length ? hazards.map(h => el("span", { class: "tag info" }, `${h.name}(${h.type})`)) : [el("span", { class: "tag gray" }, "없음")]),
      el("span", { class: "small muted", style: { marginLeft: "10px" } }, "같은 작업 평가"),
      ...(related.length ? related.map(a => el("span", { class: "chip", onclick: () => openA(a.id) }, `${a.fac} · ${a.work}`)) : [el("span", { class: "tag gray" }, "없음")])),
    el("h3", {}, "조치"), rows,
    el("div", { class: "row", style: { gap: "6px" } },
      el("button", { class: "small", onclick: () => { acts.push({ text: "", owner: "", due: "", done: false }); drawActs(); } }, "+ 조치 추가"),
      hazards.length ? el("button", { class: "small", title: "기관 위험요인 목록의 감소대책을 조치 칸에 넣습니다", onclick: () => {
        const have = new Set(acts.map(m => m.text));
        hazards.flatMap(h => h.measures.slice(0, 2)).filter(t => !have.has(t)).forEach(t => acts.push({ text: t, owner: "", due: "", done: false }));
        drawActs(); } }, "위험요인 목록 대책으로 채우기") : null),
    el("h3", {}, "원인"), cause,
    el("h3", {}, `조치 전·후 사진 ${f.photos.length}장`),
    el("div", { class: "row inc-photos", style: { gap: "10px", flexWrap: "wrap" } }, ...f.photos.map(p => el("figure", { class: "inc-ph" },
      el("img", { src: "/api/photo/" + p.name, alt: "" }), el("figcaption", { class: "small" }, el("span", { class: "tag " + (p.stage === "before" ? "gray" : "ok") }, p.stage === "before" ? "조치 전" : "조치 후"), " " + (p.caption || ""),
        el("button", { class: "icon-btn", title: "빼기", onclick: () => saveInc({ ...body(), photos: f.photos.filter(x => x.name !== p.name) }, "사진을 뺐습니다") }, "×"))))),
    el("div", { class: "row", style: { gap: "6px", marginTop: "6px" } }, photoBtn("before"), photoBtn("after")),
    el("div", { class: "row", style: { marginTop: "14px", gap: "8px" } },
      el("button", { onclick: () => saveInc(body(), "저장했습니다") }, "저장"),
      el("button", { class: "primary", id: "inc-rep-btn", onclick: async () => { await saveInc(body()); await openIncReport(true); } }, "결과보고서 미리보기·고쳐서 내려받기")),
    el("p", { class: "small muted" }, "조치를 모두 끝내고 상태를 '완료'로 바꾸면, 완료한 조치가 같은 작업 위험성평가의 감소대책에 '완료'로 들어갑니다. 끝나지 않은 조치는 '오늘 작업 브리핑'에서 시작 전 조치로 표시됩니다.")));
}
function incCtx() {
  const id = INC.incident.id;
  return { sel: "#inc-rep", title: "아차사고 결과보고서 고치기", url: `/api/incidents/${id}/export`, open: openIncReport,
    desc: `등록 내용·조치 기록·사진으로 만든 결과보고서 초안입니다${S.llm ? ". AI가 쓴 원인·재발 방지 문장은 등록 내용·조치·위험요인 목록과 숫자·코드·조문을 대조해, 근거에 없는 것이 있으면 버리고 규칙 문장을 씁니다" : ". 모델을 연결하면 AI가 원인·재발 방지 문장을 씁니다"}. 고치면 오른쪽 미리보기에 바로 반영됩니다.`,
    tools: () => [el("button", { class: "small", onclick: e => incAI("cause", e.currentTarget) }, S.llm ? "AI로 원인 쓰기" : "원인 넣기(규칙)"),
      el("button", { class: "small", onclick: e => incAI("prevent", e.currentTarget) }, S.llm ? "AI로 재발 방지 대책 쓰기" : "재발 방지 대책 넣기(규칙)"),
      el("button", { class: "small", onclick: () => addPhotos(Math.max(0, REP.findIndex(b => b[0] === "h2" && /재발 방지/.test(b[1])))) }, "사진 넣기")] };
}
async function openIncReport(reset) {
  if (!REP || reset || REPX?.sel !== "#inc-rep") REP = (await api("GET", `/api/incidents/${INC.incident.id}/preview`)).blocks;
  REPX = incCtx();
  drawReportEditor();
  $("#inc-rep").scrollIntoView({ behavior: "smooth", block: "start" });
}
async function incAI(part, btn) {
  busy(btn, true, "쓰는 중");
  try {
    const r = await api("POST", `/api/incidents/${INC.incident.id}/ai`, { part });
    const at = REP.findIndex(b => b[0] === "h2" && (part === "cause" ? /원인/ : /재발 방지/).test(b[1]));
    if (at < 0) { toast("보고서에서 넣을 자리를 찾지 못했습니다", true); return; }
    let e = at + 1;
    while (e < REP.length && (part === "cause" ? REP[e][0] === "p" : REP[e][0] === "bullet")) e++;
    REP.splice(at + 1, e - at - 1, ...(part === "cause" ? [["p", r.text]] : r.lines.map(x => ["bullet", x])));
    toast(`${part === "cause" ? "원인" : "재발 방지 대책"}을 넣었습니다(${r.mode})` + (r.dropped ? " · " + r.dropped : ""));
    drawReportEditor();
  } finally { busy(btn, false); }
}

// ------------------------------------------------------------ 기준·자료
function renderLib() {
  const box = $("#tab-lib");
  box.innerHTML = "";
  const cols = ["#ff3b30", "#ff9f0a", "#30d158"];
  const hi = S.kb.rules[0].value, mid = S.kb.rules[1].value;
  const color = r => r >= hi ? cols[0] : r >= mid ? cols[1] : cols[2];
  box.append(el("div", { class: "panel" }, el("h2", {}, "판단 기준"),
    el("p", { class: "small muted" }, "기준값은 기관 안전보건관리규정 조문에서 읽습니다. 규정을 고쳐 다시 올리면 기준이 바뀝니다."),
    el("div", { class: "grid2" },
      el("table", { class: "t" }, el("tr", {}, ["기준", "값", "근거"].map(h => el("th", {}, h))),
        S.kb.rules.map(r => el("tr", {}, el("td", {}, r.label), el("td", {}, r.value), el("td", {}, r.basis ? basisChip(r.basis) : el("span", { class: "tag gray" }, "기본값"))))),
      el("div", {}, el("div", { class: "small muted" }, "위험성 = 가능성 × 중대성"),
        el("table", { class: "matrix" }, el("tr", {}, el("td", { style: { color: "var(--muted)" } }, "가능성＼중대성"), [1, 2, 3].map(s => el("td", { style: { color: "var(--ink)" } }, s))),
          [3, 2, 1].map(l => el("tr", {}, el("td", { style: { color: "var(--ink)" } }, l), [1, 2, 3].map(s => el("td", { style: { background: color(l * s) } }, l * s)))))))));
  const drop = el("div", { class: "drop" }, "위험요인 목록·평가 대상 작업·아차사고(엑셀), 안전보건 규정(한글)을 끌어다 놓거나 ",
    el("label", { style: { color: "var(--brand)", cursor: "pointer" } }, "파일 선택", el("input", { type: "file", multiple: true, hidden: true, onchange: async e => { S = await api("POST", "/api/kb/upload", { files: await readFiles([...e.target.files]) }); await load(); toast("반영했습니다"); } })));
  drop.addEventListener("dragover", e => { e.preventDefault(); drop.classList.add("over"); });
  drop.addEventListener("dragleave", () => drop.classList.remove("over"));
  drop.addEventListener("drop", async e => { e.preventDefault(); drop.classList.remove("over"); await api("POST", "/api/kb/upload", { files: await readFiles(await filesFromDrop(e)) }); await load(); toast("반영했습니다"); });
  const pub = S.public;
  box.append(el("div", { class: "panel" }, el("h2", {}, "기관 자료"),
    pub ? el("div", { class: "q" }, "공개 시연판에서는 기관 자료를 바꿀 수 없습니다(방문자 모두가 같은 기준으로 보도록). 내려받아 설치하면 기관의 위험요인 목록·규정으로 바꿔 쓸 수 있습니다.") : drop,
    el("table", { class: "t", style: { marginTop: "12px" } }, el("tr", {}, ["파일", "종류", "건수"].map(h => el("th", {}, h))),
      S.kb.files.map(f => el("tr", {}, el("td", {}, f.file), el("td", {}, f.kind), el("td", {}, f.rows)))),
    S.kb.warnings.map(w => el("div", { class: "small", style: { color: "var(--warn)" } }, "※ " + w)),
    el("button", { style: { marginTop: "10px" }, onclick: async () => { await api("POST", "/api/kb/sample"); await load(); toast("모의자료로 되돌렸습니다"); } }, "모의자료로 되돌리기")));
  box.append(el("div", { class: "panel" }, el("h3", {}, `위험요인 목록 ${S.hazards.length}종`),
    el("table", { class: "t" }, el("tr", {}, ["코드", "위험요인", "찾는 낱말", "가능성", "중대성", "감소대책", "관련 기준"].map(h => el("th", {}, h))),
      S.hazards.map(h => el("tr", {}, el("td", {}, h.code), el("td", {}, h.name),
        el("td", { class: "small" }, h.words.filter(w => !h.learned.includes(w)).join(", "),
          h.learned.map(w => el("span", { class: "chip learned", title: "현장에서 보탠 낱말(누르면 빼기)", onclick: async () => {
            S = await api("POST", "/api/learned/remove", { code: h.code, word: w }); await load(); toast(`'${w}'를 뺐습니다`);
          } }, "+ " + w))), el("td", {}, h.L), el("td", {}, h.S),
        el("td", { class: "small" }, h.measures.join(" / ")), el("td", { class: "small" }, h.law)))),
    el("p", { class: "small muted" }, "관련 기준의 세부 조문은 국가법령정보센터에서 확인하세요. 목록은 엑셀로 고쳐 다시 올리면 됩니다. 파란 칩은 현장에서 평가하며 보탠 낱말입니다."),
    S.learned.length ? el("table", { class: "t" }, el("tr", {}, ["보탠 날", "위험요인", "낱말", "어느 작업에서"].map(h => el("th", {}, h))),
      S.learned.map(x => el("tr", {}, el("td", {}, x.at), el("td", {}, x.code), el("td", {}, x.word), el("td", {}, x.work)))) : null));
}

async function renderLog() {
  const r = await api("GET", "/api/log");
  $("#tab-log").replaceChildren(el("div", { class: "panel" }, el("h2", {}, "작업 기록"),
    r.items.length ? el("table", { class: "t" }, el("tr", {}, ["시각", "작업", "내용"].map(h => el("th", {}, h))),
      r.items.map(i => el("tr", {}, el("td", {}, i.at), el("td", {}, i.action), el("td", {}, i.detail || "")))) : el("div", { class: "empty" }, "기록이 없습니다.")));
}

document.addEventListener("DOMContentLoaded", async () => {
  GO = setupTabs(id => { if (id === "log") renderLog(); if (id === "about") renderAbout(); if (id === "photo") renderPhoto(); if (id === "perf") renderPerf(); });
  api("GET", "/api/reports-sample").then(x => { RP.samples = x.items; if (!$("#tab-photo").hidden) renderPhoto(); }).catch(() => {});
  $("#n-run").addEventListener("click", runNew);
  $("#n-next").addEventListener("click", () => flowGo(2));
  $("#n-match").addEventListener("click", flowMatch);
  $$("#flow-steps button").forEach(b => b.addEventListener("click", () => flowGo(+b.dataset.s)));
  setupMic();
  $("#ask-btn").addEventListener("click", () => ask());
  $("#q").addEventListener("keydown", e => { if (e.key === "Enter") ask(); });
  $("#ask-ex").append(...EX.map(x => el("span", { class: "chip", onclick: () => ask(x) }, x)));
  $("#n-wx").addEventListener("click", loadWx);
  $("#n-example").addEventListener("click", () => {
    $("#n-fac").value = "종합체육센터"; $("#n-dept").value = "체육사업팀"; $("#n-temp").value = "";
    $("#n-work").value = "체육관 천장 조명(등기구) 교체";
    $("#n-text").value = "이동식 일자 사다리로 높이 4m 등기구 안정기 교체. 혼자 작업, 바닥 왁스 청소 직후";
  });
  $("#task-pick").addEventListener("change", e => {
    const t = S.tasks[e.target.value];
    if (t) { $("#n-fac").value = t.fac; $("#n-dept").value = t.dept; $("#n-work").value = t.work; $("#n-text").focus(); }
  });
  $("#n-photo").addEventListener("change", async e => {
    PHOTOS = (await readFiles([...e.target.files].slice(0, 4))).map(f => ({ name: f.path, b64: f.b64 }));
    $("#n-photo-list").textContent = PHOTOS.map(p => p.name).join(", ");
  });
  $("#n-sample-photo").addEventListener("click", async () => {
    const p = await api("GET", "/api/sample-photo");
    PHOTOS = [p]; $("#n-photo-list").textContent = p.name + (S.llm ? "" : " (모델 미연결: 첨부만 됨)");
  });
  await load();
});


// 법제처 Open API 조문 원문(키가 없으면 국가법령정보센터 링크만)
async function toggleLaw(btn, code) {
  const card = btn.closest(".row");
  const old = card.nextElementSibling;
  if (old && old.classList.contains("law-box")) { old.remove(); return; }
  btn.disabled = true;
  try {
    const r = await api("GET", `/api/laws/${code}`);
    const box = el("div", { class: "law-box" },
      el("div", { class: "small muted" }, r.live ? `출처: ${r.source} (실시간)` : "출처: 국가법령정보센터 링크(법제처 인증값 없음)"),
      r.items.map(x => el("div", { class: "law-art" },
        el("div", {}, el("b", {}, `${x.law} ${x.no}`), x.title ? ` (${x.title})` : "", x.date ? el("span", { class: "small muted" }, `  시행 ${x.date}`) : null,
          " ", el("a", { href: x.url, target: "_blank", rel: "noopener", class: "small" }, "원문 보기")),
        el("div", { class: "law-text" }, x.text))),
      !r.items.length ? r.refs.map(f => el("div", {}, el("a", { href: f.url, target: "_blank", rel: "noopener" }, f.law + " 원문 보기(국가법령정보센터)"))) : null,
      r.note ? el("div", { class: "small muted" }, r.note) : null);
    card.after(box);
  } catch (e) { toast(e.message, true); }
  btn.disabled = false;
}

