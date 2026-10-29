"use strict";
let S = null, GO = null, CUR = null, PHOTOS = [], LASTINC = null;
const LV = { bad: "작업 전 조치 완료", warn: "작업 중 관리", ok: "현재 조치 유지" };

async function load() {
  S = await api("GET", "/api/state");
  renderDash(); renderList(); renderInc(); renderLib(); fillTasks();
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
  if (d.reassess.length) box.append(el("div", { class: "panel" }, el("h3", {}, "수시평가 필요(같은 작업에서 아차사고 발생)"),
    d.reassess.map(r => el("div", { class: "finding" }, el("i", { class: "dot warn" }), el("div", {}, el("div", { class: "ttl" }, `${r.fac} · ${r.work}`),
      el("button", { class: "small", onclick: () => openA(r.id) }, "평가 열기"))))));
  if (d.open_high.length) box.append(el("div", { class: "panel" }, el("h3", {}, "작업 전에 끝내야 할 조치"),
    el("table", { class: "t" }, el("tr", {}, ["작업", "위험요인", "위험성", "조치", "담당", "기한"].map(h => el("th", {}, h))),
      d.open_high.map(x => el("tr", { style: { cursor: "pointer" }, onclick: () => openA(x.aid) }, el("td", {}, `${x.fac} · ${x.work}`), el("td", {}, x.item),
        el("td", {}, el("span", { class: "tag bad" }, x.R)), el("td", {}, x.measure), el("td", {}, x.owner || "-"),
        el("td", { style: { color: x.due && x.due < S.today ? "var(--bad)" : "" } }, x.due || "-"))))));
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
  try {
    const a = await api("POST", "/api/assess", { fac: $("#n-fac").value, dept: $("#n-dept").value, work: $("#n-work").value,
      text: $("#n-text").value, temp: $("#n-temp").value, photos: PHOTOS });
    PHOTOS = []; $("#n-photo-list").textContent = ""; $("#n-photo").value = "";
    await load(); openA(a.id);
  } finally { busy(btn, false); }
}

// ------------------------------------------------------------ 목록·상세
function renderList() {
  const box = $("#list-box");
  box.innerHTML = "";
  if (!S.assessments.length) { box.append(el("div", { class: "panel empty" }, "평가가 없습니다.")); return; }
  box.append(el("div", { class: "panel" }, el("h2", {}, "평가 목록"),
    el("table", { class: "t" }, el("tr", {}, ["평가일", "시설", "작업", "최고 위험성", "미완료 조치", "상태", ""].map(h => el("th", {}, h))),
      S.assessments.map(a => el("tr", {}, el("td", {}, a.created), el("td", {}, a.fac), el("td", {}, a.work),
        el("td", {}, el("span", { class: "tag " + (a.top >= 6 ? "bad" : a.top >= 3 ? "warn" : "ok") }, a.top)),
        el("td", {}, a.stats.open), el("td", {}, a.status, a.reassess ? el("span", { class: "tag warn", style: { marginLeft: "6px" } }, "수시평가 필요") : null),
        el("td", {}, el("button", { class: "small", onclick: () => openA(a.id) }, "열기")))))));
}

async function openA(id) {
  CUR = await api("GET", `/api/assess/${id}`);
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
          : `위험성 ${a.rules.high} 이상인 ${st.blocked.join(", ")}의 감소대책을 마치기 전에는 작업을 시작하지 않습니다(규정 기준).`))),
    a.questions.map(q => el("div", { class: "q" }, "확인 필요: " + q)),
    a.permits.length ? el("div", { class: "q", style: { background: "var(--bad-soft)", color: "var(--bad)" } }, "작업 전 허가: ",
      a.permits.map(p => el("span", {}, p.name, " ", basisChip(p.basis)))) : null,
    a.reassess.length ? el("div", { class: "q" }, el("b", {}, "수시평가 필요: "), a.reassess.map(r => el("div", {}, `${r.date} 아차사고 - ${r.text} `, basisChip(r.basis))),
      el("button", { class: "small", style: { marginTop: "6px" }, onclick: () => save({ clear_reassess: true }) }, "다시 평가했음(표시 지우기)")) : null,
    a.notes.length ? el("div", { class: "small muted", style: { marginTop: "6px" } }, a.notes.map(n => el("div", {}, "※ " + n))) : null,
    a.photos.length ? el("div", { class: "photos", style: { marginTop: "10px" } }, a.photos.map(p => el("img", { src: `/api/photo/${p}`, alt: "현장 사진" }))) : null,
    el("div", { class: "row", style: { marginTop: "14px" } },
      el("span", { class: "small muted" }, "위험성평가표:"), exportButtons(`/api/assess/${a.id}/export`),
      el("button", { onclick: () => download(`/api/assess/${a.id}/xlsx`, {}) }, "엑셀"),
      el("button", { onclick: showTBM }, "작업 전 회의(TBM)"),
      el("button", { class: a.status === "확정" ? "" : "primary", onclick: () => save({ status: a.status === "확정" ? "작성 중" : "확정" }) }, a.status === "확정" ? "확정 풀기" : "평가 확정"),
      el("button", { class: "danger small", onclick: async () => { await api("DELETE", `/api/assess/${a.id}`); CUR = null; box.innerHTML = ""; await load(); } }, "삭제"))));

  for (const it of a.items) {
    const ls = k => el("select", { onchange: e => save({ items: [{ code: it.code, [k]: +e.target.value }] }) }, [1, 2, 3].map(v => el("option", { value: v, selected: it[k] === v }, v)));
    box.append(el("div", { class: `hz ${it.level}${it.confirmed ? "" : " unconf"}` },
      el("div", { class: "row" }, el("span", { class: "risk " + it.level }, it.R),
        el("div", { style: { flex: 1 } }, el("h3", {}, it.name), el("div", { class: "small muted" }, `${it.code} · ${it.type} · ${it.level_label} · 개선 후 ${it.R_after}`)),
        el("span", { class: "ls small" }, "가능성 ", ls("L"), " 중대성 ", ls("S")),
        el("span", { class: "tag " + (it.by === "낱말" ? "info" : it.by === "사진(모델)" ? "warn" : "gray") }, it.by)),
      !it.confirmed ? el("div", { class: "q" }, `사진에서 모델이 본 위험입니다: "${it.photo || it.quote}". 현장에서 확인한 뒤 평가표에 넣으세요. `,
        el("button", { class: "small primary", onclick: () => save({ items: [{ code: it.code, confirmed: true }] }) }, "확인함"),
        " ", el("button", { class: "small", onclick: async () => { CUR = await api("POST", `/api/assess/${a.id}/remove`, { code: it.code }); renderDetail(); } }, "아님(빼기)")) : null,
      it.quote && it.by !== "사진(모델)" ? el("div", { class: "reason" }, `근거 문구: "${it.quote}"`) : null,
      it.photo && it.by !== "사진(모델)" ? el("div", { class: "reason" }, `사진에서도 확인(모델): ${it.photo}`) : null,
      it.reasons.map(r => el("div", { class: "reason" }, "· " + r.text, " ", r.src ? citeChips([r.src]) : null)),
      el("div", { style: { marginTop: "8px" } }, it.measures.map((m, i) => el("div", { class: "meas" + (m.done ? " done" : "") },
        el("input", { type: "checkbox", checked: m.done, onchange: e => save({ items: [{ code: it.code, measures: it.measures.map((_, j) => j === i ? { done: e.target.checked } : {}) }] }) }),
        el("span", {}, m.text),
        el("input", { type: "text", value: m.owner, placeholder: "담당", onchange: e => save({ items: [{ code: it.code, measures: it.measures.map((_, j) => j === i ? { owner: e.target.value } : {}) }] }) }),
        el("input", { type: "date", value: m.due, onchange: e => save({ items: [{ code: it.code, measures: it.measures.map((_, j) => j === i ? { due: e.target.value } : {}) }] }) })))),
      el("div", { class: "row small", style: { marginTop: "8px" } }, el("span", { class: "muted" }, "관련 기준: " + (it.law || "-")), basisChip(it.basis),
        citeChips([it.src]), el("span", { style: { flex: 1 } }),
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
  modal("작업 전 안전점검회의(TBM) 낭독 문안",
    el("ol", { class: "tbm" }, r.lines.map(l => el("li", {}, l))),
    r.basis ? el("p", { class: "small muted" }, "근거: ", basisChip(r.basis)) : null,
    el("div", { class: "row" }, el("span", { class: "small muted" }, "서명 기록지:"), exportButtons(`/api/assess/${CUR.id}/tbm`)));
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
  box.append(el("div", { class: "panel" }, el("h3", {}, `아차사고 기록 ${S.incidents.length}건`),
    el("table", { class: "t" }, el("tr", {}, ["발생일", "시설", "작업", "내용", "분류", "출처"].map(h => el("th", {}, h))),
      S.incidents.map(i => el("tr", {}, el("td", {}, i.date), el("td", {}, i.fac), el("td", {}, i.work), el("td", {}, i.text),
        el("td", {}, (i.codes || []).join(", ")), el("td", {}, i.src ? citeChips([i.src]) : el("span", { class: "tag info" }, "화면 등록")))))));
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
  box.append(el("div", { class: "panel" }, el("h2", {}, "기관 자료"), drop,
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
  GO = setupTabs(id => { if (id === "log") renderLog(); if (id === "about") renderAbout(); });
  $("#n-run").addEventListener("click", runNew);
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
