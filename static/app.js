"use strict";
let S = null, GO = null, CUR = null, PHOTOS = [], LASTINC = null, USEWX = false, MSGS = null;
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
  try {
    const a = await api("POST", "/api/assess", { fac: $("#n-fac").value, dept: $("#n-dept").value, work: $("#n-work").value,
      text: $("#n-text").value, temp: $("#n-temp").value, photos: PHOTOS, use_weather: USEWX });
    PHOTOS = []; $("#n-photo-list").textContent = ""; $("#n-photo").value = ""; USEWX = false; $("#n-wx-box").innerHTML = "";
    await load(); openA(a.id);
  } finally { busy(btn, false); }
}

// ------------------------------------------------------------ 목록·상세
function renderList() {
  const box = $("#list-box");
  box.innerHTML = "";
  if (!S.assessments.length) { box.append(el("div", { class: "panel empty" }, "평가가 없습니다.")); return; }
  box.append(el("div", { class: "panel" }, el("h2", {}, "평가 목록"),
    el("div", { class: "tbl-scroll" }, el("table", { class: "t list-t" }, el("tr", {}, ["", "평가일", "시설", "작업", "최고 위험성", "미완료 조치", "상태"].map(h => el("th", {}, h))),
      S.assessments.map(a => el("tr", {}, el("td", {}, el("button", { class: "small", "aria-label": `${a.fac} ${a.work} 평가 열기`, onclick: () => openA(a.id) }, "열기")),
        el("td", {}, a.created), el("td", {}, a.fac), el("td", {}, a.work),
        el("td", {}, el("span", { class: "tag " + (a.top >= 6 ? "bad" : a.top >= 3 ? "warn" : "ok") }, a.top)),
        el("td", {}, a.stats.open), el("td", {}, a.status, a.reassess ? el("span", { class: "tag warn", style: { marginLeft: "6px" } }, "수시평가 필요") : null)))))));
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
      el("button", { class: a.status === "확정" ? "" : "primary", onclick: () => save({ status: a.status === "확정" ? "작성 중" : "확정" }) }, a.status === "확정" ? "확정 풀기" : "평가 확정"),
      el("span", { style: { flex: 1 } }),
      el("button", { class: "danger small", title: "이 평가를 지웁니다(되돌릴 수 없음)", onclick: async () => {
        if (!confirm(`'${a.fac} · ${a.work}' 평가를 지울까요? 지우면 되돌릴 수 없습니다.`)) return;
        await api("DELETE", `/api/assess/${a.id}`); CUR = null; box.innerHTML = ""; await load(); toast("평가를 지웠습니다");
      } }, "평가 삭제"))),
    el("div", { id: "rep-edit" }));

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
  GO = setupTabs(id => { if (id === "log") renderLog(); if (id === "about") renderAbout(); });
  $("#n-run").addEventListener("click", runNew);
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

