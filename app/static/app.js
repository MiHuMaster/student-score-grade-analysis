const selectedExamStorageKey = "student-analysis-selected-exam";
const selectedTrackStorageKey = "student-analysis-selected-track";
const selectedTargetStorageKey = "student-analysis-selected-target";
const comparisonExamsStorageKey = "student-analysis-comparison-exams";
const storedTrack = localStorage.getItem(selectedTrackStorageKey);
let storedComparisonExams = [];
try { storedComparisonExams = JSON.parse(localStorage.getItem(comparisonExamsStorageKey) || "[]"); }
catch (_error) { storedComparisonExams = []; }

const state = {
  view: "overview",
  exams: [],
  metadata: null,
  filters: {
    exam_key: localStorage.getItem(selectedExamStorageKey) || "",
    track: ["物理", "历史"].includes(storedTrack) ? storedTrack : "物理",
    target_name: localStorage.getItem(selectedTargetStorageKey) || "",
    organization_id: "", class_id: "", critical_window: "40",
  },
  preview: null,
  importIssuePages: { error: 1, warning: 1 },
  bandStep: 50,
  targetPage: 1,
  targetPageSize: 10,
  groupTransitionTab: "current",
  groupTransitionPages: {current:1, converted:1, new:1},
  groupTransitionPageSize: 20,
  groupPage: 1,
  groupPageSize: 20,
  studentItems: [],
  selectedStudent: "",
  benchmarkExamKeys: [],
  benchmarkGrades: [],
  benchmarkInitialized: false,
  benchmarkSections: {averages:true, lines:true},
  comparisonExamKeys: Array.isArray(storedComparisonExams) ? storedComparisonExams : [],
  exportFilters: {
    classes: {grades:[], examKeys:[], organizationIds:[], classIds:[]},
  },
  exportInitialized: false,
  classTrendMode: "continuous",
};

const viewMeta = {
  overview: ["成绩分析 / 总览", "整体分析"],
  classes: ["成绩分析 / 班级", "班级分析"],
  bands: ["成绩分析 / 分布", "分数段分析"],
  subjects: ["成绩分析 / 学科", "学科分析"],
  groups: ["成绩分析 / 群体", "学生群体"],
  students: ["成绩分析 / 个体", "学生个体"],
  import: ["工作台 / 数据", "数据管理"],
  benchmark: ["工作台 / 年级", "年级数据"],
  export: ["工作台 / 交付", "导出中心"],
  settings: ["工作台 / 规则", "规则设置"],
};

const content = document.querySelector("#content");
const filterStrip = document.querySelector("#filterStrip");
const businessRoot = document.querySelector("#businessRoot");
function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;").replaceAll("'", "&#039;");
}

function fmt(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
  const number = Number(value);
  const rounded = Math.round(number * 100) / 100;
  return rounded.toLocaleString("zh-CN", { minimumFractionDigits: Number.isInteger(rounded) ? 0 : 0, maximumFractionDigits: 2 });
}

function fmtInt(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
  return Math.round(Number(value)).toLocaleString("zh-CN", { maximumFractionDigits: 0 });
}

function pct(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "无法计算";
  return `${(Number(value) * 100).toFixed(2)}%`;
}

const chartPalette = ["#2f75b5", "#2a9d8f", "#e9b949", "#7b61a8", "#e76f51", "#3a86c8", "#5a9f68", "#d26485"];

function jumpNav(items) {
  return `<nav class="jump-nav" aria-label="板块定位">${items.map(([id,label]) => `<button type="button" data-scroll-target="${id}">${escapeHtml(label)}</button>`).join("")}</nav>`;
}

function bindJumpNav() {
  content.querySelectorAll("[data-scroll-target]").forEach(button => button.addEventListener("click", () => {
    content.querySelector(`#${button.dataset.scrollTarget}`)?.scrollIntoView({behavior:"smooth", block:"start"});
  }));
}

function metricTile(label, value, note = "", tone = "") {
  return `<div class="metric-tile ${tone}"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong>${note ? `<small>${escapeHtml(note)}</small>` : ""}</div>`;
}

function dashboardCard(id, title, subtitle, metrics, accent = "#2f75b5", visual = "") {
  return `<article class="card card-pad dashboard-card anchor-section" id="${id}" style="--section-accent:${accent}"><div class="card-title"><div><h3>${escapeHtml(title)}</h3>${subtitle ? `<small>${escapeHtml(subtitle)}</small>` : ""}</div></div><div class="dashboard-card-content ${visual ? "has-visual" : ""}"><div class="metric-tiles">${metrics.join("")}</div>${visual ? `<div class="compact-visual">${visual}</div>` : ""}</div></article>`;
}

function barChartSvg(items, { yTitle = "人数", labelKey = "label", valueKey = "count", colors = chartPalette } = {}) {
  if (!items.length) return '<div class="callout">暂无可绘制数据</div>';
  const width = Math.max(760, items.length * 98), height = 300;
  const pad = {l:58,r:22,t:28,b:72};
  const values = items.map(item => Number(item[valueKey]) || 0);
  const rawMaximum = Math.max(...values, 1);
  const tickStep = Math.max(1, Math.ceil(rawMaximum / 4));
  const maximum = tickStep * 4;
  const plotWidth = width - pad.l - pad.r, plotHeight = height - pad.t - pad.b;
  const slot = plotWidth / items.length, barWidth = Math.min(48, slot * .58);
  const grids = Array.from({length:5}, (_,index) => {
    const value = tickStep * index, y = pad.t + plotHeight - plotHeight * index / 4;
    return `<line class="grid" x1="${pad.l}" y1="${y}" x2="${width-pad.r}" y2="${y}"/><text x="${pad.l-8}" y="${y+4}" text-anchor="end">${fmtInt(value)}</text>`;
  }).join("");
  const bars = items.map((item,index) => {
    const value = values[index], x = pad.l + slot * index + (slot-barWidth)/2;
    const h = plotHeight * value / maximum, y = pad.t + plotHeight - h;
    const label = String(item[labelKey] ?? "");
    return `<rect class="bar" x="${x}" y="${y}" width="${barWidth}" height="${Math.max(h,1)}" rx="6" fill="${colors[index % colors.length]}"/><text x="${x+barWidth/2}" y="${Math.max(18,y-8)}" text-anchor="middle">${fmt(value)}</text><text x="${x+barWidth/2}" y="${height-42}" text-anchor="middle">${escapeHtml(label.length>12?label.slice(0,11)+"…":label)}</text>`;
  }).join("");
  return `<svg class="bar-chart-svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="${escapeHtml(yTitle)}柱状图"><text x="8" y="18">${escapeHtml(yTitle)}</text>${grids}<line class="axis" x1="${pad.l}" y1="${pad.t}" x2="${pad.l}" y2="${pad.t+plotHeight}"/><line class="axis" x1="${pad.l}" y1="${pad.t+plotHeight}" x2="${width-pad.r}" y2="${pad.t+plotHeight}"/>${bars}</svg>`;
}

function compactBarSvg(items, {valueKey="value", labelKey="label", color="#2f75b5", formatter=fmtInt} = {}) {
  const valid = items.map(item => ({...item, numeric:Number(item[valueKey])})).filter(item => Number.isFinite(item.numeric));
  if (!valid.length) return '<span class="empty-cell">暂无可绘制数据</span>';
  const width=250,height=126,pad={l:10,r:8,t:20,b:30},maximum=Math.max(...valid.map(item=>item.numeric),1);
  const slot=(width-pad.l-pad.r)/valid.length,barWidth=Math.min(36,slot*.52),plotHeight=height-pad.t-pad.b;
  const bars=valid.map((item,index)=>{const h=Math.max(2,plotHeight*item.numeric/maximum),x=pad.l+index*slot+(slot-barWidth)/2,y=pad.t+plotHeight-h;return `<g><title>${escapeHtml(item[labelKey])}：${escapeHtml(formatter(item.numeric))}</title><rect x="${x}" y="${y}" width="${barWidth}" height="${h}" rx="5" fill="${Array.isArray(color)?color[index%color.length]:color}"/><text x="${x+barWidth/2}" y="${Math.max(12,y-5)}" text-anchor="middle">${escapeHtml(formatter(item.numeric))}</text><text x="${x+barWidth/2}" y="${height-9}" text-anchor="middle">${escapeHtml(String(item[labelKey]).slice(0,6))}</text></g>`;}).join("");
  return `<svg class="compact-chart" viewBox="0 0 ${width} ${height}" role="img">${bars}</svg>`;
}

function groupedBarChartSvg(items, series) {
  if (!items.length) return '<div class="callout">暂无可绘制数据</div>';
  const width=Math.max(760,items.length*145),height=310,pad={l:58,r:20,t:42,b:70};
  const values=items.flatMap(item=>series.map(entry=>item[entry.key])).filter(value=>value!==null&&value!==undefined&&Number.isFinite(Number(value))).map(Number);
  if (!values.length) return '<div class="callout">所选考试缺少可用划线数据</div>';
  const maximum=Math.max(...values,1),plotWidth=width-pad.l-pad.r,plotHeight=height-pad.t-pad.b,groupWidth=plotWidth/items.length;
  const barWidth=Math.min(22,groupWidth/(series.length+1));
  const grids=Array.from({length:5},(_,index)=>{const value=Math.ceil(maximum*index/4),y=pad.t+plotHeight-plotHeight*index/4;return `<line class="grid" x1="${pad.l}" y1="${y}" x2="${width-pad.r}" y2="${y}"/><text x="${pad.l-8}" y="${y+4}" text-anchor="end">${fmtInt(value)}</text>`;}).join("");
  const bars=items.map((item,itemIndex)=>series.map((entry,seriesIndex)=>{const raw=item[entry.key];if(raw===null||raw===undefined)return "";const value=Number(raw),x=pad.l+itemIndex*groupWidth+(groupWidth-series.length*barWidth)/2+seriesIndex*barWidth,h=plotHeight*value/maximum,y=pad.t+plotHeight-h;return `<rect x="${x}" y="${y}" width="${Math.max(5,barWidth-2)}" height="${Math.max(h,1)}" rx="3" fill="${entry.color}"><title>${escapeHtml(item.exam_name)} · ${entry.label}：${fmtInt(value)}</title></rect>`;}).join("")+`<text x="${pad.l+itemIndex*groupWidth+groupWidth/2}" y="${height-35}" text-anchor="middle">${escapeHtml(String(item.exam_name).slice(-8))}</text>`).join("");
  const legend=series.map((entry,index)=>`<g transform="translate(${pad.l+index*115} 17)"><rect width="10" height="10" rx="2" fill="${entry.color}"/><text x="15" y="9">${entry.label}</text></g>`).join("");
  return `<svg class="bar-chart-svg grouped-bar-chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="上线历次对比柱状图">${legend}${grids}<line class="axis" x1="${pad.l}" y1="${pad.t}" x2="${pad.l}" y2="${pad.t+plotHeight}"/><line class="axis" x1="${pad.l}" y1="${pad.t+plotHeight}" x2="${width-pad.r}" y2="${pad.t+plotHeight}"/>${bars}</svg>`;
}

function donutSvg(items) {
  const values=items.map(item=>Math.max(0,Number(item.value)||0)),total=values.reduce((sum,value)=>sum+value,0);
  if (!total) return '<span class="empty-cell">暂无占比数据</span>';
  const radius=42,circumference=2*Math.PI*radius,colors=items.map((_item,index)=>chartPalette[index%chartPalette.length]);
  let offset=0;
  const arcs=items.map((item,index)=>{const length=circumference*values[index]/total,current=offset;offset+=length;return `<circle cx="70" cy="62" r="${radius}" fill="none" stroke="${colors[index]}" stroke-width="15" stroke-dasharray="${length} ${circumference-length}" stroke-dashoffset="-${current}" transform="rotate(-90 70 62)"><title>${escapeHtml(item.label)}：${fmtInt(values[index])}</title></circle>`;}).join("");
  const legend=items.map((item,index)=>`<g transform="translate(130 ${34+index*29})"><rect width="9" height="9" rx="2" fill="${colors[index]}"/><text x="15" y="9">${escapeHtml(item.label)} ${fmtInt(values[index])}</text></g>`).join("");
  return `<svg class="compact-chart donut-chart" viewBox="0 0 250 126" role="img">${arcs}<text x="70" y="59" text-anchor="middle" class="donut-total">${fmtInt(total)}</text><text x="70" y="75" text-anchor="middle">总计</text>${legend}</svg>`;
}

function smoothLineSvg(labels, values, {inverse=false,width=230,height=84,formatter=fmt,breakOnMissing=false,examKeys=[],highlightExamKey=""} = {}) {
  const numeric = values.map(value => value === null || value === undefined ? null : Number(value));
  const present = numeric.filter(value => value !== null && !Number.isNaN(value));
  if (!present.length) return '<span class="empty-cell">无趋势</span>';
  const pad={l:12,r:12,t:19,b:15},min=Math.min(...present),max=Math.max(...present),span=Math.max(max-min,1);
  const indexed=numeric.map((value,index)=>value===null||Number.isNaN(value)?null:{x:numeric.length===1?width/2:pad.l+index*(width-pad.l-pad.r)/(numeric.length-1),y:pad.t+(max-value)*(height-pad.t-pad.b)/span,value,index});
  const points=indexed.filter(Boolean);
  const segments=[];
  if (breakOnMissing) {
    let segment=[];
    indexed.forEach(point => { if (point) segment.push(point); else if (segment.length) { segments.push(segment); segment=[]; } });
    if (segment.length) segments.push(segment);
  } else {
    segments.push(points);
  }
  const paths=segments.filter(segment=>segment.length>1).map(segment=>segment.slice(1).reduce((d,point,index)=>{const previous=segment[index],mid=(previous.x+point.x)/2;return `${d} C ${mid} ${previous.y}, ${mid} ${point.y}, ${point.x} ${point.y}`;},`M ${segment[0].x} ${segment[0].y}`));
  const color=inverse?'#7b61a8':'#2f75b5';
  return `<svg class="smooth-line" viewBox="0 0 ${width} ${height}" role="img">${paths.map(path=>`<path d="${path}" fill="none" stroke="${color}" stroke-width="2.5" stroke-linecap="round"/>`).join("")}${points.map(point=>{const highlighted=examKeys[point.index]===highlightExamKey;return `<g><title>${escapeHtml(labels[point.index]||"")}：${escapeHtml(formatter(point.value))}</title><circle class="${highlighted?"current-exam-point":""}" cx="${point.x}" cy="${point.y}" r="${highlighted?6:4}" fill="${highlighted?'#e76f51':'#fff'}" stroke="${highlighted?'#b7432f':color}" stroke-width="${highlighted?3:2}"/><text x="${point.x}" y="${Math.max(10,point.y-9)}" text-anchor="middle">${escapeHtml(formatter(point.value))}</text></g>`;}).join("")}</svg>`;
}

function radarSvg(subjects) {
  if (!subjects.length) return '<div class="callout">暂无学科线差</div>';
  const width=420,height=330,cx=210,cy=165,radius=112,maxAbs=Math.max(...subjects.map(item=>Math.abs(Number(item.line_gap)||0)),1);
  const point=(index,scale)=>{const angle=-Math.PI/2+index*2*Math.PI/subjects.length;return [cx+Math.cos(angle)*radius*scale,cy+Math.sin(angle)*radius*scale]};
  const rings=[.25,.5,.75,1].map(scale=>`<polygon points="${subjects.map((_item,index)=>point(index,scale).join(',')).join(' ')}" fill="none" stroke="${scale===.5?'#9fb3c8':'#dce5ed'}" stroke-width="${scale===.5?1.5:1}"/>`).join("");
  const axes=subjects.map((item,index)=>{const [x,y]=point(index,1),[lx,ly]=point(index,1.18);return `<line x1="${cx}" y1="${cy}" x2="${x}" y2="${y}" stroke="#d4dee8"/><text x="${lx}" y="${ly}" text-anchor="middle">${escapeHtml(item.name)} ${fmt(item.line_gap)}</text>`}).join("");
  const dataPoints=subjects.map((item,index)=>point(index,.5+(Number(item.line_gap)||0)/(2*maxAbs)));
  return `<svg class="radar-chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="学科特控线差雷达图">${rings}${axes}<polygon points="${dataPoints.map(item=>item.join(',')).join(' ')}" fill="rgba(47,117,181,.2)" stroke="#2f75b5" stroke-width="2.5"/>${dataPoints.map(([x,y])=>`<circle cx="${x}" cy="${y}" r="4" fill="#fff" stroke="#2f75b5" stroke-width="2"/>`).join("")}</svg>`;
}

async function triggerDownload(path, button, resetText = "导出") {
  if (button.disabled) return;
  button.disabled = true;
  const original = button.textContent;
  button.textContent = "正在生成…";
  try {
    const response = await fetch(path);
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      const message = payload.error || `下载失败（${response.status}）`;
      throw new Error(message);
    }
    if ((response.headers.get("content-type") || "").includes("application/json")) {
      throw new Error("下载失败：未收到文件，请稍后重试");
    }
    const blob = await response.blob();
    const disposition = response.headers.get("content-disposition") || "";
    const encoded = disposition.match(/filename\*=UTF-8''([^;]+)/i);
    const plain = disposition.match(/filename="([^"]+)"|filename=([^;]+)/i);
    const filename = encoded ? decodeURIComponent(encoded[1]) : (plain?.[1] || plain?.[2] || "下载文件");
    const url = URL.createObjectURL(blob), link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 60000);
  } catch (error) {
    showToast(error instanceof TypeError ? "无法连接本机服务，请确认程序仍在运行" : error.message, "error");
  } finally {
    button.disabled = false;
    button.textContent = original || resetText;
  }
}

document.addEventListener("click", event => {
  const link = event.target.closest('a[href^="/api/import/"]');
  if (!link || !new URL(link.href).pathname.endsWith("/workbook")) return;
  event.preventDefault();
  triggerDownload(link.href, link);
});

function showToast(message, type = "") {
  const toast = document.querySelector("#toast");
  toast.textContent = message;
  toast.className = `toast show ${type}`;
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => { toast.className = "toast"; }, 3000);
}

async function api(path, options = {}) {
  const response = await fetch(path, options);
  const type = response.headers.get("content-type") || "";
  const payload = type.includes("application/json") ? await response.json() : null;
  if (!response.ok) throw new Error(payload?.error || `请求失败（${response.status}）`);
  return payload;
}

function query(extra = {}) {
  const params = new URLSearchParams({
    exam_key: state.filters.exam_key,
    track: state.filters.track,
    critical_window: state.filters.critical_window,
    target_name: state.filters.target_name,
    ...extra,
  });
  if (!Object.prototype.hasOwnProperty.call(extra, "organization_id") && state.filters.organization_id) {
    params.set("organization_id", state.filters.organization_id);
  }
  if (!Object.prototype.hasOwnProperty.call(extra, "class_id") && state.filters.class_id) {
    params.set("class_id", state.filters.class_id);
  }
  state.comparisonExamKeys.forEach(key => params.append("exam_keys", key));
  return params.toString();
}

function loading() {
  content.innerHTML = '<div class="loading-card"><div class="spinner"></div><p>正在统一计算指标…</p></div>';
}

function emptyDatabase() {
  content.innerHTML = `
    <div class="card empty-state">
      <div class="empty-icon">⇧</div>
      <h2>数据库中还没有考试</h2>
      <p>先前往“数据管理”上传标准模板。系统会先生成校验报告，确认后才正式写入 SQLite；也可以在终端运行 <code>flask --app run.py seed-demo</code> 查看匿名演示效果。</p>
      <button class="primary" data-go="import">开始导入数据</button>
    </div>`;
  content.querySelector("[data-go]")?.addEventListener("click", () => switchView("import"));
}

function currentExam() { return state.exams.find(item => item.exam_key === state.filters.exam_key); }
function trackLabel() { return state.filters.track ? `${state.filters.track}方向` : "全部方向"; }

function comparisonCandidates(examKey = state.filters.exam_key) {
  const anchor = state.exams.find(item => item.exam_key === examKey);
  if (!anchor) return [];
  return state.exams.filter(item=>item.grade===anchor.grade).slice().sort((a,b)=>a.exam_date.localeCompare(b.exam_date)||a.exam_key.localeCompare(b.exam_key));
}

function normalizeComparisonSelection(reset = false) {
  const anchorKey = state.filters.exam_key;
  const candidates = comparisonCandidates(anchorKey);
  const valid = new Set(candidates.map(item=>item.exam_key));
  const retained = reset ? [] : state.comparisonExamKeys.filter(key=>valid.has(key)&&key!==anchorKey);
  const selected = new Set([anchorKey,...retained.slice(0,4)].filter(Boolean));
  state.comparisonExamKeys = candidates.filter(item=>selected.has(item.exam_key)).map(item=>item.exam_key);
  localStorage.setItem(comparisonExamsStorageKey, JSON.stringify(state.comparisonExamKeys));
}

function renderGlobalComparisonFilter() {
  const host = document.querySelector("#comparisonExamFilter");
  if (!host) return;
  const options = comparisonCandidates().map(item=>({
    value:item.exam_key, label:item.name, description:`${item.exam_date}${item.exam_key===state.filters.exam_key?" · 单次考试（必选）":""}`,
    locked:item.exam_key===state.filters.exam_key,
  }));
  host.innerHTML = renderMultiSelect("global-comparison-exams","历次考试对比",options,state.comparisonExamKeys,"搜索同年级考试");
  bindMultiSelect(host,"global-comparison-exams",values=>{
    state.comparisonExamKeys=values;
    normalizeComparisonSelection();
    state.groupPage=1; state.targetPage=1;
    state.groupTransitionPages={current:1,converted:1,new:1};
  },{maxSelections:5,lockedValues:[state.filters.exam_key]});
}

function enhanceSearchableSelect(select, placeholder) {
  if (!select || select.dataset.searchEnhanced === "true") return;
  select.dataset.searchEnhanced = "true";
  select.classList.add("searchable-native");
  const wrapper = document.createElement("div");
  wrapper.className = "searchable-select";
  wrapper.innerHTML = `<input type="search" autocomplete="off" placeholder="${escapeHtml(placeholder)}" aria-label="${escapeHtml(placeholder)}"><button type="button" class="searchable-toggle" aria-label="展开选项">⌄</button><div class="searchable-menu" role="listbox"></div>`;
  select.after(wrapper);
  const input = wrapper.querySelector("input");
  const menu = wrapper.querySelector(".searchable-menu");
  const selectedText = () => select.options[select.selectedIndex]?.text || "";
  const sync = () => { input.value = selectedText(); };
  const close = () => { wrapper.classList.remove("open"); };
  const renderOptions = (keyword = "") => {
    const normalized = String(keyword).trim().toLocaleLowerCase("zh-CN");
    const options = [...select.options].filter(option => !normalized || option.text.toLocaleLowerCase("zh-CN").includes(normalized));
    menu.innerHTML = options.map(option => `<button type="button" role="option" data-select-value="${escapeHtml(option.value)}" class="${option.value === select.value ? "selected" : ""}">${escapeHtml(option.text)}</button>`).join("") || '<span class="searchable-empty">没有匹配项</span>';
    menu.querySelectorAll("[data-select-value]").forEach(button => button.addEventListener("mousedown", event => {
      event.preventDefault();
      select.value = button.dataset.selectValue;
      select.dispatchEvent(new Event("change", {bubbles:true}));
      sync();
      close();
    }));
  };
  const open = (useInput = false) => {
    renderOptions(useInput ? input.value : "");
    wrapper.classList.add("open");
  };
  input.addEventListener("focus", () => { input.select(); open(false); });
  input.addEventListener("input", () => open(true));
  input.addEventListener("keydown", event => {
    if (event.key === "Escape") { close(); sync(); input.blur(); }
    if (event.key === "Enter") {
      event.preventDefault();
      menu.querySelector("[data-select-value]")?.dispatchEvent(new MouseEvent("mousedown", {bubbles:true}));
    }
  });
  input.addEventListener("blur", () => setTimeout(() => { if (!wrapper.classList.contains("open")) sync(); }, 0));
  wrapper.querySelector(".searchable-toggle").addEventListener("click", () => {
    if (wrapper.classList.contains("open")) close(); else { input.focus(); open(false); }
  });
  document.addEventListener("mousedown", event => { if (!wrapper.contains(event.target)) { close(); sync(); } });
  select.addEventListener("change", sync);
  select._syncSearchable = sync;
  sync();
}

function syncSearchableSelect(select) {
  select?._syncSearchable?.();
}

function renderMultiSelect(id, label, options, selectedValues, placeholder = "搜索") {
  const selected = new Set(selectedValues.map(String));
  const valid = options.map(item => ({...item, value:String(item.value)}));
  const selectedCount = valid.filter(item => selected.has(item.value)).length;
  return `<div class="multi-select" data-multi-select="${escapeHtml(id)}"><span class="multi-select-label">${escapeHtml(label)}</span><button type="button" class="multi-select-trigger" aria-expanded="false"><span>${selectedCount ? `已选 ${selectedCount} 项` : `请选择${label}`}</span><b>⌄</b></button><div class="multi-select-menu"><input type="search" autocomplete="off" placeholder="${escapeHtml(placeholder)}"><div class="multi-select-actions"><button type="button" data-multi-action="all">全选</button><button type="button" data-multi-action="clear">清空</button></div><div class="multi-select-options">${valid.map(item => `<label data-multi-option data-search-text="${escapeHtml(`${item.label} ${item.description || ""}`.toLocaleLowerCase("zh-CN"))}" class="${item.locked ? "locked" : ""}"><input type="checkbox" value="${escapeHtml(item.value)}" ${selected.has(item.value) ? "checked" : ""} ${item.locked ? "disabled" : ""}><span><strong>${escapeHtml(item.label)}</strong>${item.description ? `<small>${escapeHtml(item.description)}</small>` : ""}</span></label>`).join("") || '<span class="searchable-empty">暂无可选数据</span>'}</div></div></div>`;
}

function bindMultiSelect(root, id, onChange, {maxSelections=Infinity, lockedValues=[]} = {}) {
  const element = root.querySelector(`[data-multi-select="${id}"]`);
  if (!element) return;
  const trigger = element.querySelector(".multi-select-trigger");
  const search = element.querySelector('input[type="search"]');
  const optionInputs = [...element.querySelectorAll('[data-multi-option] input[type="checkbox"]')];
  const selectedValues = () => optionInputs.filter(input => input.checked).map(input => input.value);
  const syncLabel = () => {
    const count = selectedValues().length;
    trigger.querySelector("span").textContent = count ? `已选 ${count} 项` : `请选择${element.querySelector(".multi-select-label").textContent}`;
  };
  trigger.addEventListener("click", event => {
    event.stopPropagation();
    const open = element.classList.toggle("open");
    trigger.setAttribute("aria-expanded", String(open));
    if (open) search?.focus();
  });
  search?.addEventListener("input", () => {
    const keyword = search.value.trim().toLocaleLowerCase("zh-CN");
    element.querySelectorAll("[data-multi-option]").forEach(option => { option.hidden = Boolean(keyword) && !option.dataset.searchText.includes(keyword); });
  });
  const locked = new Set(lockedValues.map(String));
  optionInputs.forEach(input => input.addEventListener("change", () => {
    if (input.checked && selectedValues().length > maxSelections) {
      input.checked = false;
      showToast(`最多选择 ${maxSelections} 场考试。`, "error");
    }
    syncLabel(); onChange(selectedValues());
  }));
  element.querySelector('[data-multi-action="all"]')?.addEventListener("click", () => {
    optionInputs.forEach(input => { input.checked = false; });
    locked.forEach(value => { const input=optionInputs.find(item=>item.value===value); if(input) input.checked=true; });
    optionInputs.filter(input=>!locked.has(input.value)).slice(0,Math.max(0,maxSelections-locked.size)).forEach(input=>{input.checked=true;});
    syncLabel(); onChange(selectedValues());
  });
  element.querySelector('[data-multi-action="clear"]')?.addEventListener("click", () => {
    optionInputs.forEach(input => { input.checked = locked.has(input.value); }); syncLabel(); onChange(selectedValues());
  });
}

document.addEventListener("mousedown", event => {
  document.querySelectorAll(".multi-select.open").forEach(element => {
    if (!element.contains(event.target)) {
      element.classList.remove("open");
      element.querySelector(".multi-select-trigger")?.setAttribute("aria-expanded", "false");
    }
  });
});

async function loadFilters() {
  const data = await api(`/api/filters?exam_key=${encodeURIComponent(state.filters.exam_key)}`);
  const targetSelect = document.querySelector("#targetFilter");
  const targets = data.targets || [];
  if (!targets.includes(state.filters.target_name)) state.filters.target_name = data.default_target_name || "";
  targetSelect.innerHTML = (data.default_target_name ? "" : '<option value="">未设置默认高考目标，请选择</option>') + targets.map(name => `<option value="${escapeHtml(name)}">${escapeHtml(name.endsWith("目标") ? name : name + "目标")}</option>`).join("");
  targetSelect.value = state.filters.target_name;
  targetSelect.disabled = !targets.length;
  syncSearchableSelect(targetSelect);
  persistSelectedScope();
  const school = document.querySelector("#schoolFilter");
  school.innerHTML = '<option value="">全部学校</option>' + data.organizations.map(item => `<option value="${item.id}">${escapeHtml(item.name)}</option>`).join("");
  school.value = state.filters.organization_id;
  syncSearchableSelect(school);
  const classSelect = document.querySelector("#classFilter");
  classSelect.innerHTML = '<option value="">全部班级</option>' + data.classes.filter(item => (!state.filters.track || item.track === state.filters.track) && (!state.filters.organization_id || String(item.organization_name) === school.options[school.selectedIndex]?.text)).map(item => `<option value="${item.id}">${escapeHtml(item.track)} · ${escapeHtml(item.organization_name)} · ${escapeHtml(item.class_name)}班</option>`).join("");
  classSelect.value = state.filters.class_id;
  syncSearchableSelect(classSelect);
}

function syncFiltersFromDom() {
  state.filters = {
    exam_key: document.querySelector("#examFilter").value,
    track: document.querySelector("#trackFilter").value,
    target_name: document.querySelector("#targetFilter").value,
    organization_id: document.querySelector("#schoolFilter").value,
    class_id: document.querySelector("#classFilter").value,
    critical_window: document.querySelector("#windowFilter").value,
  };
  persistSelectedScope();
}

function persistSelectedScope() {
  if (state.filters.exam_key) localStorage.setItem(selectedExamStorageKey, state.filters.exam_key);
  else localStorage.removeItem(selectedExamStorageKey);
  localStorage.setItem(selectedTrackStorageKey, state.filters.track);
  if (state.filters.target_name) localStorage.setItem(selectedTargetStorageKey, state.filters.target_name);
  else localStorage.removeItem(selectedTargetStorageKey);
  localStorage.setItem(comparisonExamsStorageKey, JSON.stringify(state.comparisonExamKeys));
}

async function renderOverview() {
  const data = await api(`/api/analytics/overview?${query()}`);
  const lines = data.lines;
  const control = lines["特控"];
  const targetPages=Math.max(1,Math.ceil(data.targets.details.length/state.targetPageSize));
  state.targetPage=Math.min(Math.max(1,state.targetPage),targetPages);
  const targetRows=()=>{
    const page=data.targets.details.slice((state.targetPage-1)*state.targetPageSize,state.targetPage*state.targetPageSize);
    return page.length?page.map(item=>`<tr><td>${escapeHtml(item.organization_name)}</td><td>${escapeHtml(item.class_name)}班</td><td class="numeric">${item.actual}</td><td class="numeric">${item.target}</td><td><span class="pill ${item.difference>=0?"teal":"red"}">${item.status} ${Math.abs(item.difference)} 人</span></td></tr>`).join(""):'<tr><td colspan="5" class="empty-cell">当前范围没有已设置目标的班级</td></tr>';
  };
  const onlineSeries=[
    {key:"critical_count",label:"临界生",color:"#f6c8ce"},
    {key:"control_count",label:"特控",color:"#c8e5b4"},
    {key:"line_211_count",label:"211",color:"#b6c7ec"},
    {key:"line_985_count",label:"985",color:"#f9e3a1"},
  ];
  const anchors = [["overview-basic","考试基础"],["overview-scores","基础数据"],["overview-lines","上线结构"],["overview-online-history","上线历次"],["overview-targets","目标达标班级"],["overview-critical","临界分析"],["overview-history","历次对比"]];
  content.innerHTML = `
    <div class="section-heading"><div><h2>${escapeHtml(data.exam.name)}</h2><p>${escapeHtml(data.exam.grade)} · ${data.exam.date} · ${trackLabel()}</p></div><span class="meta">数据版本 ${data.exam.data_version} · ${escapeHtml(data.rule_version)}</span></div>
    ${jumpNav(anchors)}
    <div class="grid two-col equal">
      ${dashboardCard("overview-basic", "考试基础信息", `${trackLabel()} · 按已导入有效参考统计`, [metricTile("参考人数", `${fmtInt(data.reference_count)} 人`), metricTile("参考班级数", `${fmtInt(data.class_count)} 个`), ...data.student_types.map(item=>metricTile(item.name, `${fmtInt(item.count)} 人`, pct(item.rate)))], "#2f75b5", donutSvg(data.student_types.map(item=>({label:item.name,value:item.count}))))}
      ${dashboardCard("overview-scores", "成绩分析基础数据", "有效总分口径", [metricTile("最高分", `${fmt(data.highest)} 分`), metricTile("最低分", `${fmt(data.lowest)} 分`), metricTile("平均分", `${fmt(data.average)} 分`), metricTile("总体标准差", `${fmt(data.standard_deviation)} 分`)], "#7b61a8", compactBarSvg([{label:"最高",value:data.highest},{label:"最低",value:data.lowest},{label:"平均",value:data.average},{label:"标准差",value:data.standard_deviation}],{color:["#2f75b5","#e76f51","#2a9d8f","#7b61a8"],formatter:fmt}))}
      ${dashboardCard("overview-lines", "上线结构分析", `分母 ${fmtInt(data.reference_count)} 人`, [
        metricTile("特控线上线", `${fmtInt(control.count)} 人`, pct(control.rate), "teal"),
        metricTile("211上线", `${fmtInt(lines["211"].count)} 人`, pct(lines["211"].rate)),
        metricTile("985上线", `${fmtInt(lines["985"].count)} 人`, pct(lines["985"].rate), "gold"),
      ], "#2a9d8f", compactBarSvg([{label:"特控",value:control.count},{label:"211",value:lines["211"].count},{label:"985",value:lines["985"].count}],{color:["#2a9d8f","#2f75b5","#e9b949"]}))}
      <article class="card card-pad dashboard-card anchor-section full-span" id="overview-online-history" style="--section-accent:#52667a"><div class="card-title"><div><h3>上线历次对比分析</h3><small>临界生为各场考试特控线下40分；缺少对应划线时保留空值</small></div><span class="pill">${data.history.length} 场考试</span></div><div class="chart-panel">${groupedBarChartSvg(data.history,onlineSeries)}</div></article>
      <article class="card card-pad dashboard-card anchor-section" id="overview-targets" style="--section-accent:#3a86c8"><div class="card-title"><div><h3>目标达标班级分析</h3><small>已配置目标 ${fmtInt(data.targets.configured_classes)} 个班级</small></div></div><div class="dashboard-card-content has-visual"><div class="metric-tiles target-pair">${metricTile("目标达标班级比例", pct(data.targets.rate), `${fmtInt(data.targets.met)} / ${fmtInt(data.targets.configured_classes)} 个班级`, "teal")}${metricTile("未达标班级", `${fmtInt(data.targets.missed)} 个`, "", "red")}</div><div class="compact-visual">${donutSvg([{label:"达标",value:data.targets.met},{label:"未达标",value:data.targets.missed}])}</div></div><div class="table-wrap" style="margin-top:14px"><table><thead><tr><th>学校</th><th>班级</th><th>实际上线</th><th>目标</th><th>结果</th></tr></thead><tbody id="targetRows">${targetRows()}</tbody></table></div><div class="pagination"><button id="targetPrev" ${state.targetPage===1?'disabled':''}>上一页</button><span id="targetPageLabel">第 ${state.targetPage} / ${targetPages} 页 · 共 ${fmtInt(data.targets.details.length)} 个班级</span><button id="targetNext" ${state.targetPage===targetPages?'disabled':''}>下一页</button></div></article>
      ${dashboardCard("overview-critical", "临界分析", `临界窗口：特控线下 ${data.critical.window} 分`, [metricTile("临界生转化", `${fmtInt(data.transitions.converted_count)} 人`, pct(data.transitions.conversion_rate), "teal"), metricTile("本次转为临界生", `${fmtInt(data.transitions.newly_critical_count)} 人`), metricTile("共同参考学生", `${fmtInt(data.transitions.common_student_count)} 人`)], "#e76f51", compactBarSvg([{label:"转化",value:data.transitions.converted_count},{label:"转为临界",value:data.transitions.newly_critical_count},{label:"共同参考",value:data.transitions.common_student_count}],{color:["#2a9d8f","#e76f51","#7b61a8"]}))}
      ${dashboardCard("overview-history", "历次对比分析", "平滑曲线：历次特控上线人数", [metricTile("上升班级", `${fmtInt(data.class_line_changes.increased)} 个`, "", "teal"), metricTile("下降班级", `${fmtInt(data.class_line_changes.decreased)} 个`, "", "red"), metricTile("不变班级", `${fmtInt(data.class_line_changes.unchanged)} 个`)], "#52667a", smoothLineSvg(data.history.map(item=>item.exam_name),data.history.map(item=>item.control_count),{width:250,height:126,formatter:fmtInt,examKeys:data.history.map(item=>item.exam_key),highlightExamKey:state.filters.exam_key}))}
    </div>`;
  const repaintTargets=()=>{
    content.querySelector("#targetRows").innerHTML=targetRows();
    content.querySelector("#targetPageLabel").textContent=`第 ${state.targetPage} / ${targetPages} 页 · 共 ${fmtInt(data.targets.details.length)} 个班级`;
    content.querySelector("#targetPrev").disabled=state.targetPage===1;
    content.querySelector("#targetNext").disabled=state.targetPage===targetPages;
  };
  content.querySelector("#targetPrev")?.addEventListener("click",()=>{state.targetPage--;repaintTargets();});
  content.querySelector("#targetNext")?.addEventListener("click",()=>{state.targetPage++;repaintTargets();});
  bindJumpNav();
}

async function renderClasses() {
  if (!state.filters.track) {
    content.innerHTML = '<div class="card empty-state"><div class="empty-icon">▦</div><h2>班级分析需要明确方向</h2><p>班级排名和上线指标分别按物理、历史方向计算。请选择方向；“全部方向”可用于整体、学科、学生和导出范围。</p></div>';
    return;
  }
  if (!state.filters.class_id) {
    content.innerHTML = '<div class="card empty-state"><div class="empty-icon">▦</div><h2>请先选择具体班级</h2><p>班级分析包含多次考试纵向指标和同方向横向对比，选择学校与班级后开始计算。</p></div>';
    return;
  }
  const data = await api(`/api/analytics/classes?${query()}`);
  if (!data.classes.length) {
    content.innerHTML = '<div class="callout warning">当前筛选范围没有班级成绩。</div>';
    return;
  }
  const selected = data.classes[0];
  const rawHistory = data.history || [];
  const categories = [
    ["class-scores", "成绩分析基础数据", [
      ["参考人数", item => item.reference_count, fmtInt],
      ["最高分", item => item.highest, fmt],
      ["最低分", item => item.lowest, fmt],
      ["平均分", item => item.average, fmt], ["与年级平均分差", item => item.benchmark_gap, fmt],
      ["班级均分排名", item => item.cloud_rank, fmtInt], ["班级标准差", item => item.standard_deviation, fmt],
      ["年级标准差", item => item.cloud_standard_deviation, fmt],
    ]],
    ["class-lines", "上线结构", [
      ["特控上线人数", item => item.control_count, fmtInt], ["特控上线率", item => item.control_rate, pct],
      ["211以上人数", item => item.line_211_count, fmtInt], ["985以上人数", item => item.line_985_count, fmtInt],
      ["潜力生人数", item => item.potential_count, fmtInt],
    ]],
    ["class-target", "目标完成分析", [["目标人数", item => item.target, fmtInt], ["目标完成率", item => item.target_completion_rate, pct]]],
    ["class-critical", "临界分析", [
      ["线下40分临界人数", item => item.critical_40, fmtInt], ["线下90分临界人数", item => item.critical_90, fmtInt],
      ["临界生转化人数", item => item.converted_count, fmtInt], ["本次转为临界生人数", item => item.newly_critical_count, fmtInt],
    ]],
    ["class-history", "历次对比分析", [["较上次特控上线变化人数", item => item.control_change, fmtInt]]],
  ];
  const categoryCards = () => {
    let history = rawHistory.map(item => ({...item, value:item.classes.find(row => row.class_id === selected.class_id) || null}));
    const breakOnMissing = state.classTrendMode === "timeline";
    if (!breakOnMissing) history = history.filter(item => item.value);
    const historyLabels = history.map(item => item.exam_name);
    return categories.map(([id,title,metrics],index) => `<article class="card card-pad dashboard-card anchor-section" id="${id}" style="--section-accent:${chartPalette[index % chartPalette.length]}"><div class="card-title"><h3>${title}</h3><span class="pill">${history.length} 场考试 · ${breakOnMissing ? "真实时间轴" : "仅参考考试"}</span></div><div class="class-metric-grid">${metrics.map(([label,getter,formatter])=>{const values=history.map(item=>item.value ? getter(item.value) : null);return `<div class="class-metric-item"><div><span>${escapeHtml(label)}</span><strong>${escapeHtml(formatter(getter(selected)))}</strong></div>${smoothLineSvg(historyLabels,values,{formatter,width:230,height:82,inverse:label.includes('排名'),breakOnMissing,examKeys:history.map(item=>item.exam_key),highlightExamKey:state.filters.exam_key})}</div>`;}).join("")}</div></article>`).join("");
  };
  const comparisonItems = data.comparison_classes || data.classes;
  const comparisonRows = comparisonItems.map(item => `<tr><td>${escapeHtml(item.school)}</td><td>${escapeHtml(item.class_name)}班</td><td class="numeric">${fmtInt(item.reference_count)}</td><td class="numeric">${fmt(item.highest)}</td><td class="numeric">${fmt(item.lowest)}</td><td class="numeric">${fmt(item.average)}</td><td class="numeric">${fmtInt(item.average_rank)}</td><td class="numeric">${fmt(item.benchmark_average)}</td><td class="numeric">${fmt(item.benchmark_ratio)}</td><td class="numeric">${fmtInt(item.control_count)}</td><td class="numeric">${pct(item.control_rate)}</td><td class="numeric">${fmtInt(item.control_rate_rank)}</td><td class="numeric">${fmtInt(item.line_211_count)}</td><td class="numeric">${fmtInt(item.line_985_count)}</td></tr>`).join("");
  const allSubjects = data.subject_comparison_all || data.subject_comparison;
  const order = ["chinese","math","english","physics","history","chemistry","biology","politics","geography"];
  const subjectCodes = [...new Map(allSubjects.map(item => [item.code, item.name])).entries()].sort((a,b)=>order.indexOf(a[0])-order.indexOf(b[0]));
  const subjectOptions = subjectCodes.map(([code,name]) => `<option value="${code}">${escapeHtml(name)}</option>`).join("");
  content.innerHTML = `
    <div class="section-heading"><div><h2>${escapeHtml(selected.school)} · ${escapeHtml(selected.class_name)}班</h2><p>班级多次考试指标按业务主题分组，横向表用于同方向班级比较。</p></div><span class="meta">${data.track}方向 · ${rawHistory.length} 场考试</span></div>
    ${jumpNav([["class-scores","基础数据"],["class-lines","上线结构"],["class-target","目标完成"],["class-critical","临界分析"],["class-history","历次对比"],["class-total-compare","总分对比"],["class-subject-compare","单科对比"]])}
    <article class="card card-pad class-trend-filter"><div class="card-title"><div><h3>历次趋势范围</h3><small>考试范围统一使用顶部“历次考试对比”；此处只控制缺考场次的连线方式。</small><small class="micro-note">该班已参考：${escapeHtml((selected.participated_exams||[]).map(item=>item.name).join("、")||"暂无正常参考考试")}</small></div><label class="inline-select">趋势模式<select id="classTrendMode"><option value="continuous" ${state.classTrendMode === "continuous" ? "selected" : ""}>仅连接实际参考考试</option><option value="timeline" ${state.classTrendMode === "timeline" ? "selected" : ""}>保留真实考试时间轴</option></select></label></div></article>
    <div class="grid two-col equal" id="classTrendCards">${categoryCards()}</div>
    <article class="card card-pad anchor-section" id="class-total-compare" style="margin-top:16px"><div class="card-title"><h3>总分分析对比</h3><span class="pill">同方向全部班级</span></div><div class="table-wrap"><table><thead><tr><th>学校</th><th>班级</th><th>参考人数</th><th>最高分</th><th>最低分</th><th>平均分</th><th>均分排名</th><th>年级均分</th><th>班级/年级</th><th>特控人数</th><th>特控率</th><th>特控率排名</th><th>211人数</th><th>985人数</th></tr></thead><tbody>${comparisonRows}</tbody></table></div></article>
    <article class="card card-pad anchor-section" id="class-subject-compare" style="margin-top:16px"><div class="card-title"><h3>单科分析对比</h3><label class="inline-select">学科<select id="classSubjectSelect">${subjectOptions}</select></label></div><div class="table-wrap"><table><thead><tr><th>学校</th><th>班级</th><th>参考人数</th><th>平均分</th><th>均分排名</th><th>年级均分比</th><th>特控人数（线）</th><th>特控率</th><th>特控率排名</th><th>211人数</th><th>985人数</th></tr></thead><tbody id="classSubjectRows"></tbody></table></div></article>`;
  const renderSubjectRows = code => {
    const rows = allSubjects.filter(item => item.code === code).map(item => `<tr><td>${escapeHtml(item.school)}</td><td>${escapeHtml(item.class_name)}班</td><td class="numeric">${fmtInt(item.reference_count)}</td><td class="numeric">${fmt(item.average)}</td><td class="numeric">${fmtInt(item.average_rank)}</td><td class="numeric">${fmt(item.benchmark_ratio)}</td><td class="numeric">${fmtInt(item.control_count)}（${fmt(item.lines["特控"])}）</td><td class="numeric">${pct(item.control_rate)}</td><td class="numeric">${fmtInt(item.control_rate_rank)}</td><td class="numeric">${fmtInt(item.line_211_count)}</td><td class="numeric">${fmtInt(item.line_985_count)}</td></tr>`).join("");
    content.querySelector("#classSubjectRows").innerHTML = rows || '<tr><td colspan="11" class="empty-cell">该学科暂无班级成绩</td></tr>';
  };
  const selector = content.querySelector("#classSubjectSelect");
  selector?.addEventListener("change", () => renderSubjectRows(selector.value));
  if (selector) renderSubjectRows(selector.value);
  const repaintTrends = () => { content.querySelector("#classTrendCards").innerHTML = categoryCards(); };
  content.querySelector("#classTrendMode")?.addEventListener("change", event => { state.classTrendMode = event.target.value; repaintTrends(); });
  bindJumpNav();
}

const bandColors = ["#3a86c8", "#7b61a8", "#e76f51", "#2a9d8f", "#e9b949", "#d26485"];

async function renderBands() {
  const data = await api(`/api/analytics/score-bands?${query({step:state.bandStep})}`);
  const legend = data.line_bands.map((item,index) => `<span><i style="background:${bandColors[index]}"></i>${escapeHtml(item.label)}</span>`).join("");
  const history = data.history || [];
  const transposedBandTable = (kind, fallbackBands) => {
    const snapshots = history.length ? history : [{exam_key:state.filters.exam_key, exam_name:currentExam()?.name || "本次考试", [kind]:fallbackBands}];
    const width = Math.max(0, ...snapshots.map(item => (item[kind] || []).length));
    const headers = Array.from({length:width}, (_,index) => {
      const band = snapshots.map(item => (item[kind] || [])[index]).find(Boolean);
      return `<th>${kind === "line_bands" ? escapeHtml(band.display_label) : `分数段${index+1}`}</th>`;
    }).join("");
    const rows = snapshots.flatMap(item => {
      const bands = item[kind] || [];
      const cells = getter => Array.from({length:width}, (_,index) => `<td class="numeric">${index < bands.length ? getter(bands[index]) : "—"}</td>`).join("");
      return [
        `<tr><th rowspan="3">${escapeHtml(item.exam_name)}</th><th>分数区间</th>${cells(band=>escapeHtml(band.label))}</tr>`,
        `<tr><th>人数</th>${cells(band=>fmtInt(band.count))}</tr>`,
        `<tr><th>占比</th>${cells(band=>pct(band.rate))}</tr>`,
      ];
    }).join("");
    return `<div class="table-wrap"><table class="matrix-table band-matrix"><thead><tr><th>考试</th><th>维度</th>${headers}</tr></thead><tbody>${rows}</tbody></table></div>`;
  };
  content.innerHTML = `
    <div class="section-heading"><div><h2>学生成绩结构</h2><p>柱状图用于观察各分数段人数差异，表格保留精确值和历次考试结果。</p></div><div class="button-row"><span class="meta">有效参考 ${fmtInt(data.reference_count)} 人</span></div></div>
    ${jumpNav([["line-band-section","分数线分段"],["fixed-band-section","固定值分段"]])}
    <article class="card card-pad anchor-section" id="line-band-section"><div class="card-title"><h3>按分数线分段</h3><span class="pill ${data.reconcile.matches ? "teal" : "amber"}">${data.reconcile.matches ? "人数核对一致" : "等待分数线"}</span></div>${data.line_bands.length ? `<div class="mini-legend">${legend}</div><div class="chart-panel">${barChartSvg(data.line_bands,{colors:bandColors})}</div><div style="margin-top:14px">${transposedBandTable("line_bands",data.line_bands)}</div><p class="micro-note">总分分数段统一采用左闭右开；最高一档不设右界。各区间人数之和必须等于有效参考人数。</p>` : `<div class="callout warning">${escapeHtml(data.missing_reason)}</div>`}</article>
    <article class="card card-pad anchor-section" id="fixed-band-section" style="margin-top:16px"><div class="card-title"><h3>固定值分段分析</h3><div class="segmented"><button data-band-step="30" class="${state.bandStep===30?'active':''}">30分</button><button data-band-step="50" class="${state.bandStep===50?'active':''}">50分</button></div></div><div class="chart-panel">${barChartSvg(data.fixed_bands,{colors:["#2f75b5"],yTitle:"人数"})}</div><div style="margin-top:14px">${transposedBandTable("fixed_bands",data.fixed_bands)}</div></article>`;
  content.querySelectorAll("[data-band-step]").forEach(button => button.addEventListener("click", async () => { state.bandStep = Number(button.dataset.bandStep); await renderBands(); }));
  bindJumpNav();
}

async function renderSubjects() {
  if (!state.filters.class_id && state.filters.track) {
    content.innerHTML = '<div class="card empty-state"><div class="empty-icon">◎</div><h2>请先选择具体班级</h2><p>学科横向诊断和多次考试趋势需要在明确班级范围后展示，请先选择学校与班级。</p></div>';
    return;
  }
  const data = await api(`/api/analytics/subjects?${query()}`);
  const order = ["chinese","math","english","physics","history","chemistry","biology","politics","geography"];
  data.subjects.sort((a,b)=>order.indexOf(a.code)-order.indexOf(b.code));
  const rows = data.subjects.map(item => `<tr><td><strong>${escapeHtml(item.name)}</strong></td><td class="numeric">${fmtInt(item.reference_count)}</td><td class="numeric">${fmt(item.highest)}</td><td class="numeric">${fmt(item.lowest)}</td><td class="numeric">${fmt(item.average)}</td><td class="numeric">${fmt(item.line_gap)}</td><td class="numeric">${fmtInt(item.control_online_count)}</td><td class="numeric">${pct(item.control_online_rate)}</td><td class="numeric">${pct(item.hit_rate)}</td><td class="numeric">${pct(item.contribution_rate)}</td><td class="numeric">${fmtInt(item.critical_10)}</td><td class="numeric">${fmtInt(item.critical_20)}</td><td class="numeric">${fmt(item.benchmark_ratio)}</td><td><span class="pill ${item.diagnosis === "优势" ? "teal" : item.diagnosis === "薄弱" ? "red" : ""}">${item.diagnosis}</span></td></tr>`).join("");
  const subjectOptions = data.subjects.map(item => `<option value="${item.code}">${escapeHtml(item.name)}</option>`).join("");
  content.innerHTML = `
    <div class="section-heading"><div><h2>${state.filters.class_id ? "班级" : "范围"}学科分析</h2><p>学科固定按语文、数学、英语、物理、历史、化学、生物、政治、地理排序；无成绩学科不显示。</p></div><span class="meta">${trackLabel()} · ${fmtInt(data.reference_count)} 名学生</span></div>
    ${jumpNav([["multi-subject-section","多学科横向对比"],["subject-history-section","单科历次对比"]])}
    <article class="card card-pad anchor-section" id="multi-subject-section"><div class="card-title"><h3>多学科横向对比</h3><span class="pill">雷达图：与特控线分差</span></div><div class="radar-wrap"><div>${radarSvg(data.subjects)}</div><div class="table-wrap"><table><thead><tr><th>学科</th><th>参考人数</th><th>最高</th><th>最低</th><th>平均</th><th>特控线差</th><th>上线人数</th><th>上线率</th><th>命中率</th><th>贡献率</th><th>线下10分</th><th>线下20分</th><th>班级/年级</th><th>判断</th></tr></thead><tbody>${rows || '<tr><td colspan="14">当前范围无单科成绩</td></tr>'}</tbody></table></div></div></article>
    <article class="card card-pad anchor-section" id="subject-history-section" style="margin-top:16px"><div class="card-title"><h3>单科考试多次对比</h3><label class="inline-select">学科<select id="subjectHistorySelect">${subjectOptions}</select></label></div><div class="table-wrap"><table class="matrix-table"><thead><tr><th>维度</th>${(data.history || []).map(item => `<th>${escapeHtml(item.exam_name)}</th>`).join("")}<th>趋势图</th></tr></thead><tbody id="subjectHistoryRows"></tbody></table></div></article>`;
  const selector = content.querySelector("#subjectHistorySelect");
  const renderHistory = code => {
    const snapshots = (data.history || []).map(item => item.subjects.find(subject => subject.code === code));
    const definitions = [
      ["最高分", item => item?.highest, fmt], ["最低分", item => item?.lowest, fmt], ["平均分", item => item?.average, fmt],
      ["与特控线分差", item => item?.line_gap, fmt], ["上线人数", item => item?.control_online_count, fmtInt],
      ["上线率", item => item?.control_online_rate, pct], ["命中率", item => item?.hit_rate, pct], ["贡献率", item => item?.contribution_rate, pct],
      ["临界生（至线下10分）", item => item?.critical_10, fmtInt], ["临界生（至线下20分）", item => item?.critical_20, fmtInt],
    ];
    content.querySelector("#subjectHistoryRows").innerHTML = definitions.map(([label,getter,formatter]) => { const values=snapshots.map(getter); return `<tr><th>${escapeHtml(label)}</th>${values.map(value => `<td class="numeric">${escapeHtml(formatter(value))}</td>`).join("")}<td>${smoothLineSvg((data.history||[]).map(item=>item.exam_name),values,{inverse:label.includes("排名"),formatter,width:210,height:76,examKeys:(data.history||[]).map(item=>item.exam_key),highlightExamKey:state.filters.exam_key})}</td></tr>`; }).join("");
  };
  selector?.addEventListener("change", () => renderHistory(selector.value));
  if (selector) renderHistory(selector.value);
  bindJumpNav();
}

async function renderGroups() {
  if (!state.filters.track) {
    content.innerHTML = '<div class="card empty-state"><div class="empty-icon">♙</div><h2>学生群体划线需要明确方向</h2><p>特控、211、985线按方向配置，因此动态临界群体请先选择物理或历史方向。</p></div>';
    return;
  }
  const [data, matrix] = await Promise.all([
    api(`/api/analytics/student-groups?${query()}`),
    api(`/api/analytics/student-matrix?${query({exam_limit: 5})}`),
  ]);
  const summary = [
    ["本次临界生", data.current_critical.length, `特控线下 ${data.critical_window} 分`],
    ["临界生转化", data.converted.length, data.conversion_rate !== undefined ? `转化率 ${pct(data.conversion_rate)}` : "缺少上一场考试"],
    ["本次转为临界", data.newly_critical.length, `共同学生 ${data.common_student_count} 人`],
  ];
  const transitionItems = { current: data.current_critical, converted: data.converted, new: data.newly_critical };
  if (!transitionItems[state.groupTransitionTab]) state.groupTransitionTab = "current";
  const transitionPage = key => {
    const totalPages = Math.max(1, Math.ceil(transitionItems[key].length / state.groupTransitionPageSize));
    const page = Math.min(Math.max(state.groupTransitionPages[key] || 1, 1), totalPages);
    state.groupTransitionPages[key] = page;
    return {page,totalPages};
  };
  const makeRows = (items, page=1) => items.slice((page-1)*state.groupTransitionPageSize,page*state.groupTransitionPageSize).map(item => `<tr><td>${escapeHtml(item.name)}</td><td>${escapeHtml(item.organization)}</td><td>${escapeHtml(item.class_name)}班</td><td>${item.student_type}</td><td class="numeric">${fmt(item.effective_total)}</td><td class="numeric">${fmt(item.line_gap)}</td><td class="numeric">${item.previous_total !== undefined ? fmt(item.previous_total) : "—"}</td></tr>`).join("") || '<tr><td colspan="7" class="empty-cell">当前条件下没有学生</td></tr>';
  const examHeaders = matrix.exams.map(item => `<th>${escapeHtml(item.name)}</th>`).join("");
  const groupHeaders = `<th colspan="${matrix.exams.length}">总分</th>` + matrix.subjects.map(subject => `<th colspan="${matrix.exams.length}">${escapeHtml(subject.name)}${["chemistry","biology","politics","geography"].includes(subject.code) ? "（赋）" : ""}</th>`).join("");
  const repeatedExamHeaders = examHeaders + matrix.subjects.map(() => examHeaders).join("");
  const lineRows = ["特控", "211", "985"].map(lineType => `<tr class="line-row"><th colspan="3">${lineType}线</th>${matrix.exams.map(exam => `<td class="numeric">${fmt(matrix.total_lines[exam.id]?.[lineType])}</td>`).join("")}${matrix.subjects.map(subject => matrix.exams.map(exam => `<td class="numeric">${fmt(matrix.subject_lines[exam.id]?.[subject.code]?.[lineType])}</td>`).join("")).join("")}</tr>`).join("");
  const scoreCell = cell => `<td class="numeric score-level ${escapeHtml(cell.level)}">${cell.score === null || cell.score === undefined ? "—" : fmt(cell.score)}</td>`;
  const totalPages = Math.max(1, Math.ceil(matrix.students.length / state.groupPageSize));
  state.groupPage = Math.min(Math.max(state.groupPage, 1), totalPages);
  const makeMatrixRows = () => matrix.students.slice((state.groupPage-1)*state.groupPageSize,state.groupPage*state.groupPageSize).map(student => `<tr><td>${escapeHtml(student.organization)}</td><td>${escapeHtml(student.class_name)}</td><td>${escapeHtml(student.name)}</td>${student.totals.map(scoreCell).join("")}${matrix.subjects.map(subject => student.subjects[subject.code].map(scoreCell).join("")).join("")}</tr>`).join("");
  content.innerHTML = `
    <div class="section-heading"><div><h2>动态学生群体</h2><p>只在共同参考学生中计算跨考试转化，避免把缺考和新增学生误判为变化。</p></div><span class="meta">共同学生 ${data.common_student_count} 人</span></div>
    ${jumpNav([["group-transitions","动态学生群体"],["group-matrix","成绩矩阵"]])}
    <div class="grid three-col">${summary.map(([label,value,note], index) => `<article class="card kpi"><div class="kpi-label">${label}</div><div class="kpi-value">${value}</div><div class="kpi-note ${index===1 ? "positive" : ""}">${note}</div></article>`).join("")}</div>
    ${data.missing_reason ? `<div class="callout warning" style="margin-top:16px">${escapeHtml(data.missing_reason)}</div>` : ""}
    <article class="card card-pad anchor-section" id="group-transitions" style="margin-top:16px"><div class="group-tabs"><button class="tab ${state.groupTransitionTab==='current'?'active':''}" data-group="current">本次临界</button><button class="tab ${state.groupTransitionTab==='converted'?'active':''}" data-group="converted">成功转化</button><button class="tab ${state.groupTransitionTab==='new'?'active':''}" data-group="new">本次转为临界</button></div><div class="table-wrap"><table><thead><tr><th>姓名</th><th>学校</th><th>班级</th><th>学生类型</th><th class="numeric">本次总分</th><th class="numeric">线差</th><th class="numeric">上次总分</th></tr></thead><tbody id="groupRows"></tbody></table></div><div class="pagination"><button id="groupTransitionPrev">上一页</button><span id="groupTransitionPage"></span><button id="groupTransitionNext">下一页</button></div></article>
    <article class="card card-pad anchor-section" id="group-matrix" style="margin-top:16px"><div class="card-title"><h3>学生多次考试成绩矩阵</h3><div class="score-legend"><span class="line-critical">临界</span><span class="line-control">特控</span><span class="line-211">211</span><span class="line-985">985</span></div></div><div class="table-wrap tall-table"><table class="matrix-table score-matrix"><thead><tr><th rowspan="2">学校</th><th rowspan="2">班级</th><th rowspan="2">姓名</th>${groupHeaders}</tr><tr>${repeatedExamHeaders}</tr></thead><tbody id="matrixRows">${lineRows}${makeMatrixRows()}</tbody></table></div><div class="pagination"><button id="matrixPrev" ${state.groupPage===1?'disabled':''}>上一页</button><span>第 ${state.groupPage} / ${totalPages} 页 · 共 ${fmtInt(matrix.students.length)} 人</span><button id="matrixNext" ${state.groupPage===totalPages?'disabled':''}>下一页</button></div><p class="micro-note">单科达到特控线下10分、总分达到特控线下40分标红；达到特控、211、985线依次标绿、蓝、黄。</p></article>`;
  const repaintTransition = () => {
    const key = state.groupTransitionTab;
    const {page,totalPages} = transitionPage(key);
    content.querySelector("#groupRows").innerHTML = makeRows(transitionItems[key],page);
    content.querySelector("#groupTransitionPage").textContent = `第 ${page} / ${totalPages} 页 · 共 ${transitionItems[key].length} 人`;
    content.querySelector("#groupTransitionPrev").disabled = page === 1;
    content.querySelector("#groupTransitionNext").disabled = page === totalPages;
  };
  content.querySelectorAll("[data-group]").forEach(button => button.addEventListener("click", () => {
    content.querySelectorAll("[data-group]").forEach(item => item.classList.remove("active")); button.classList.add("active");
    state.groupTransitionTab = button.dataset.group;
    state.groupTransitionPages[state.groupTransitionTab] = 1;
    repaintTransition();
  }));
  content.querySelector("#groupTransitionPrev")?.addEventListener("click",()=>{state.groupTransitionPages[state.groupTransitionTab]--;repaintTransition();});
  content.querySelector("#groupTransitionNext")?.addEventListener("click",()=>{state.groupTransitionPages[state.groupTransitionTab]++;repaintTransition();});
  repaintTransition();
  const updatePage = delta => { state.groupPage += delta; renderGroups(); };
  content.querySelector("#matrixPrev")?.addEventListener("click", () => updatePage(-1));
  content.querySelector("#matrixNext")?.addEventListener("click", () => updatePage(1));
  bindJumpNav();
}

function trendSvg(history, highlightExamKey = "") {
  if (!history.length) return '<div class="callout">没有可展示的考试记录</div>';
  const width = 720, height = 210, pad = { l: 42, r: 22, t: 20, b: 38 };
  const values = history.map(item => Number(item.effective_total));
  const min = Math.floor((Math.min(...values) - 20) / 50) * 50;
  const max = Math.ceil((Math.max(...values) + 20) / 50) * 50 || 750;
  const x = index => history.length === 1 ? width / 2 : pad.l + index * (width - pad.l - pad.r) / (history.length - 1);
  const y = value => pad.t + (max - value) * (height - pad.t - pad.b) / Math.max(max - min, 1);
  const points = values.map((value,index) => ({x:x(index),y:y(value)}));
  const path = points.slice(1).reduce((result, point, index) => { const previous=points[index],mid=(previous.x+point.x)/2; return `${result} C ${mid} ${previous.y}, ${mid} ${point.y}, ${point.x} ${point.y}`; }, `M ${points[0].x} ${points[0].y}`);
  const grids = [0,.5,1].map(rate => { const value=max-(max-min)*rate, yy=y(value); return `<line class="grid-line" x1="${pad.l}" y1="${yy}" x2="${width-pad.r}" y2="${yy}"/><text x="5" y="${yy+4}">${Math.round(value)}</text>`; }).join("");
  const dots = history.map((item,index) => {const highlighted=item.exam_key===highlightExamKey;return `<circle class="dot ${highlighted?'current-exam-point':''}" cx="${x(index)}" cy="${y(item.effective_total)}" r="${highlighted?7:5}" ${highlighted?'fill="#e76f51" stroke="#b7432f"':''}/><text x="${x(index)}" y="${height-12}" text-anchor="middle">${escapeHtml(item.exam_name.slice(-6))}</text><text x="${x(index)}" y="${y(item.effective_total)-11}" text-anchor="middle">${fmt(item.effective_total)}</text>`;}).join("");
  return `<svg class="trend-chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="学生总分趋势">${grids}<path class="line" d="${path}"/>${dots}</svg>`;
}

async function showStudent(studentNo, button) {
  content.querySelectorAll(".student-item").forEach(item => item.classList.remove("active")); button?.classList.add("active");
  const pane = content.querySelector("#studentDetail");
  pane.innerHTML = '<div class="loading-card"><div class="spinner"></div></div>';
  const data = await api(`/api/students/${encodeURIComponent(studentNo)}?${query()}`);
  state.selectedStudent = studentNo;
  const latest = data.history.at(-1);
  const subjectNames = [...new Set(data.history.flatMap(item => item.subjects.map(subject => subject.name)))];
  pane.innerHTML = `<div class="card-title"><div><h3>${escapeHtml(data.student.name)} <small>${escapeHtml(data.student.student_no)}</small></h3><small>${latest ? `${escapeHtml(latest.organization_name)} · ${escapeHtml(latest.class_name)}班 · ${latest.track}方向` : "无考试记录"}</small></div><div class="button-row"><label class="inline-select">对比维度<select id="studentLineType"><option value="特控">特控线</option><option value="211">211线</option><option value="985">985线</option></select></label></div></div><div class="chart-panel">${trendSvg(data.history,state.filters.exam_key)}</div><div class="student-detail-grid" id="studentMetricRows" style="margin-top:16px"></div><p class="micro-note">优势和薄弱学科使用位次百分位判断：${escapeHtml(data.diagnosis_formula)}。排名数值越小越好。</p>`;
  const renderRows = lineType => {
    const definitions = [
      ["总分", item => item.effective_total, fmt, false], ["班级排名", item => item.class_rank, fmtInt, true],
      ["年级排名", item => item.grade_rank, fmtInt, true],
      ["年级已导入有效人数", item => item.grade_reference_count, fmtInt, false],
      ...subjectNames.flatMap(name => [
        [name, item => item.subjects.find(subject => subject.name === name)?.effective_score, fmt, false],
        [`${name}线差`, item => item.subjects.find(subject => subject.name === name)?.line_gaps?.[lineType], fmt, false],
      ]),
    ];
    const examLabels = data.history.map(item => item.exam_name);
    pane.querySelector("#studentMetricRows").innerHTML = definitions.map(([label,getter,formatter,inverse]) => { const values=data.history.map(getter); return `<div class="student-metric-row"><strong>${escapeHtml(label)}</strong><div class="student-metric-values">${data.history.map((item,index)=>`<span title="${escapeHtml(item.exam_name)}">${escapeHtml(item.exam_name)}：${escapeHtml(formatter(values[index]))}</span>`).join("")}</div><div>${smoothLineSvg(examLabels,values,{inverse,formatter,width:210,height:76,examKeys:data.history.map(item=>item.exam_key),highlightExamKey:state.filters.exam_key})}</div></div>`; }).join("") + `<div class="student-metric-row"><strong>优势学科</strong><div class="student-metric-values">${data.history.map(item=>`<span>${escapeHtml(item.exam_name)}：${escapeHtml(item.advantages.join('、')||'—')}</span>`).join("")}</div><div></div></div><div class="student-metric-row"><strong>薄弱学科</strong><div class="student-metric-values">${data.history.map(item=>`<span>${escapeHtml(item.exam_name)}：${escapeHtml(item.weaknesses.join('、')||'—')}</span>`).join("")}</div><div></div></div>`;
  };
  const selector = pane.querySelector("#studentLineType");
  selector.addEventListener("change", () => renderRows(selector.value));
  renderRows(selector.value);
}

async function renderStudents() {
  const data = await api(`/api/students?${query({limit:"10"})}`);
  state.studentItems = data.items;
  if (!state.studentItems.some(item => item.identity_key === state.selectedStudent)) state.selectedStudent = "";
  content.innerHTML = `<div class="section-heading"><div><h2>学生个人成绩分析</h2><p>默认展示同方向总分前10名；可按姓名、学号、学校或班级搜索完整数据库。</p></div><span class="meta" id="studentResultMeta">总分前 ${fmtInt(data.items.length)} 人</span></div><div class="student-layout"><article class="card"><div class="card-pad" style="padding-bottom:10px"><div class="card-title"><h3>学生列表</h3><span class="pill" id="studentListBadge">总分前10</span></div></div><div class="student-search"><input type="text" id="studentSearch" placeholder="搜索姓名、学号、学校或班级"></div><div class="student-list" id="studentList"></div></article><article class="card card-pad" id="studentDetail"><div class="empty-state" style="margin:20px auto"><div class="empty-icon">◇</div><h2>选择一名学生</h2><p>查看各维度多次考试数值、柱状图并导出。</p></div></article></div>`;
  const renderList = (items, keyword="") => {
    state.studentItems = items;
    content.querySelector("#studentResultMeta").textContent = keyword ? `匹配 ${fmtInt(items.length)} 人` : `总分前 ${fmtInt(items.length)} 人`;
    content.querySelector("#studentListBadge").textContent = keyword ? "搜索结果" : "总分前10";
    content.querySelector("#studentList").innerHTML = items.map(item => `<button class="student-item" data-student="${escapeHtml(item.identity_key)}"><strong>${escapeHtml(item.name)}</strong><span class="score">${fmt(item.effective_total)}</span><small>${escapeHtml(item.student_no)} · ${escapeHtml(item.organization)} · ${escapeHtml(item.class_name)}班</small></button>`).join("") || '<div class="card-pad empty-cell">未找到匹配学生</div>';
    content.querySelectorAll("[data-student]").forEach(button => button.addEventListener("click", () => showStudent(button.dataset.student, button)));
  };
  renderList(data.items);
  let requestSequence = 0;
  content.querySelector("#studentSearch").addEventListener("input", event => {
    const keyword = event.target.value.trim();
    const sequence = ++requestSequence;
    clearTimeout(renderStudents.searchTimer);
    renderStudents.searchTimer = setTimeout(async () => {
      try {
        const result = await api(`/api/students?${query({q:keyword,limit:keyword?"50":"10"})}`);
        if (sequence === requestSequence) renderList(result.items, keyword);
      } catch (error) { if (sequence === requestSequence) showToast(error.message,"error"); }
    }, 200);
  });
}

function issueHtml(issue) {
  const location = [issue.sheet_name, issue.row_number ? `第 ${issue.row_number} 行` : "", issue.field_name].filter(Boolean).join(" · ");
  return `<article class="issue ${issue.severity}"><span class="issue-marker">${issue.severity === "error" ? "!" : "i"}</span><div class="issue-content"><div class="issue-heading"><strong>${escapeHtml(issue.message)}</strong><span class="issue-code">${escapeHtml(issue.issue_code)}</span></div>${location ? `<small class="issue-location">位置：${escapeHtml(location)}</small>` : '<small class="issue-location">位置：文件级校验</small>'}${issue.raw_value ? `<small class="issue-raw">原始值：${escapeHtml(issue.raw_value)}</small>` : ""}${issue.suggestion ? `<p>处理建议：${escapeHtml(issue.suggestion)}</p>` : ""}</div></article>`;
}

function batchStatusMeta(status, errorCount = 0) {
  if (String(status).startsWith("committed")) return [status === "committed_partial" ? "已部分入库" : "已入库", "teal"];
  if (errorCount) return ["预检有阻止项", "red"];
  return ["等待确认", "amber"];
}

async function loadBatches() {
  const data = await api("/api/import/batches");
  const body = document.querySelector("#batchRows");
  if (!body) return;
  const count = document.querySelector("#batchCount");
  if (count) count.textContent = `已成功上传 ${fmtInt(data.count ?? data.items.length)} 次`;
  body.innerHTML = data.items.map(item => {
    const [label, tone] = batchStatusMeta(item.status, item.error_count);
    const preparation = item.summary?.preparation;
    const exam = preparation ? `${preparation.grade} · ${preparation.exam_name} · ${preparation.exam_month}` : "按文件内考试信息";
    return `<tr><td><strong>${escapeHtml(item.original_filename)}</strong><small class="table-subline">${escapeHtml(exam)}</small></td><td>${escapeHtml(item.committed_at || item.created_at)}</td><td>${fmtInt(item.valid_row_count || item.row_count)}</td><td><span class="pill ${tone}">${label}</span></td><td><div class="batch-actions"><a class="secondary compact button-link" href="/api/import/${encodeURIComponent(item.batch_key)}/workbook">下载输出表</a><button class="danger-button compact" data-delete-batch="${escapeHtml(item.batch_key)}" data-batch-name="${escapeHtml(item.original_filename)}">清除此批次</button></div></td></tr>`;
  }).join("") || '<tr><td colspan="5" class="empty-cell">暂无成功上传的数据</td></tr>';
  body.querySelectorAll("[data-delete-batch]").forEach(button => button.addEventListener("click", async () => {
    const name = button.dataset.batchName;
    if (!window.confirm(`将删除“${name}”当前关联的成绩和上传文件。是否继续？`)) return;
    if (!window.confirm("此操作无法撤销。请再次确认清除此批次。")) return;
    button.disabled = true;
    try {
      const result = await api(`/api/import/${encodeURIComponent(button.dataset.deleteBatch)}`, {method:"DELETE"});
      if (state.preview?.batch_key === button.dataset.deleteBatch) state.preview = null;
      showToast(`已清除该批次及 ${fmtInt(result.deleted_results)} 条当前关联成绩`);
      await loadBatches();
      await refreshExams();
    } catch (error) { showToast(error.message, "error"); }
  }));
}

async function loadImportIssues(preview, severity, requestedPage = 1) {
  const target = content.querySelector(`#${severity}IssueContent`);
  if (!target) return;
  const count = severity === "error" ? preview.error_count : preview.warning_count;
  if (!count) {
    target.innerHTML = `<div class="validation-empty ${severity}">${severity === "error" ? "没有阻止入库的问题" : "没有需要人工确认的提醒"}</div>`;
    return;
  }
  target.innerHTML = '<div class="issue-loading"><div class="spinner"></div><span>正在读取完整问题列表…</span></div>';
  const result = await api(`/api/import/${encodeURIComponent(preview.batch_key)}/issues?severity=${severity}&page=${requestedPage}&page_size=50`);
  state.importIssuePages[severity] = result.page;
  target.innerHTML = `<div class="issue-list">${result.items.map(issueHtml).join("")}</div><div class="issue-pagination"><span>第 ${result.page} / ${result.total_pages} 页 · 共 ${fmtInt(result.total)} 项</span><div class="button-row"><button class="secondary compact" data-issue-page="${result.page - 1}" ${result.page <= 1 ? "disabled" : ""}>上一页</button><button class="secondary compact" data-issue-page="${result.page + 1}" ${result.page >= result.total_pages ? "disabled" : ""}>下一页</button></div></div>`;
  target.querySelectorAll("[data-issue-page]").forEach(button => button.addEventListener("click", () => loadImportIssues(preview, severity, Number(button.dataset.issuePage))));
}

function bindImportLocators() {
  content.querySelectorAll("[data-import-target]").forEach(button => button.addEventListener("click", () => {
    content.querySelector(`#${button.dataset.importTarget}`)?.scrollIntoView({behavior:"smooth", block:"start"});
  }));
}

async function commitImportPreview(preview) {
  const hasErrors = preview.error_count > 0;
  const warningConfirmation = content.querySelector("#confirmWarnings");
  const partialConfirmation = content.querySelector("#confirmPartial");
  if (warningConfirmation && !warningConfirmation.checked) return showToast("请先确认已核对提醒项", "error");
  if (partialConfirmation && !partialConfirmation.checked) return showToast("请先确认仅保存有效数据并跳过阻止行", "error");
  const validRows = preview.valid_row_count ?? preview.summary?.valid_score_rows ?? 0;
  const blockedRows = preview.blocked_row_count ?? preview.summary?.blocked_score_rows ?? 0;
  const prompt = hasErrors
    ? `将保存 ${validRows} 条有效成绩，跳过 ${blockedRows} 条被阻止的成绩行。预检记录和原文件会继续保留，是否继续并进入分析？`
    : `将正式保存 ${validRows} 条成绩。预检记录和原文件会继续保留，是否继续？`;
  if (!window.confirm(prompt)) return;
  const button = content.querySelector("#commitButton");
  button.disabled = true;
  button.textContent = hasErrors ? "正在保存有效数据…" : "正在事务入库…";
  try {
    const result = await api(`/api/import/${preview.batch_key}/commit`, {
      method: "POST",
      headers: {"Content-Type":"application/json"},
      body: JSON.stringify({
        mode: content.querySelector("#commitMode").value,
        allow_partial: hasErrors,
        warnings_confirmed: !warningConfirmation || warningConfirmation.checked,
      }),
    });
    preview.status = result.status;
    preview.commit_result = result;
    state.preview = preview;
    button.textContent = "保存完成";
    showToast(`已入库 ${result.committed_rows} 条，阻止项跳过 ${result.blocked_rows_skipped || 0} 条，重复跳过 ${result.skipped_rows} 条${result.rank_warning_count ? `；${result.rank_warning_count} 行上传排名有差异，已采用系统排名，可在校验记录查看` : ""}`);
    const importedExamKey = result.exam_keys?.[0] || state.filters.exam_key;
    state.filters.exam_key = importedExamKey;
    state.filters.organization_id = "";
    state.filters.class_id = "";
    await refreshExams();
    if (state.exams.some(exam => exam.exam_key === importedExamKey)) {
      state.filters.exam_key = importedExamKey;
      persistSelectedScope();
    }
    state.benchmarkExamKeys = importedExamKey ? [importedExamKey] : [];
    state.benchmarkGrades = state.exams.find(exam => exam.exam_key === importedExamKey)?.grade ? [state.exams.find(exam => exam.exam_key === importedExamKey).grade] : [];
    state.benchmarkInitialized = true;
    await switchView("benchmark");
  } catch (error) {
    showToast(error.message, "error");
    button.disabled = false;
    button.textContent = hasErrors ? "仅保存有效数据并进入分析" : "确认正式入库";
  }
}

async function renderImportPreview(preview) {
  const panel = content.querySelector("#previewResult");
  const status = content.querySelector("#previewStatus");
  if (!panel || !status) return;
  const committed = String(preview.status).startsWith("committed");
  const validRows = preview.valid_row_count ?? preview.summary?.valid_score_rows ?? 0;
  const blockedRows = preview.blocked_row_count ?? preview.summary?.blocked_score_rows ?? Math.max(0, (preview.summary?.score_rows || 0) - validRows);
  const [statusLabel, statusTone] = batchStatusMeta(preview.status, preview.error_count);
  status.className = `pill ${statusTone}`;
  status.textContent = statusLabel;
  const warningCheck = preview.warning_count ? `<label class="confirmation-check"><input type="checkbox" id="confirmWarnings"><span><strong>我已浏览并确认提醒项</strong><small>这些记录允许保存，但需要人工确认识别结果或数据差异。</small></span></label>` : "";
  const partialCheck = preview.error_count ? `<label class="confirmation-check danger"><input type="checkbox" id="confirmPartial"><span><strong>我确认仅保存有效成绩</strong><small>被阻止的成绩行不会写入数据库，问题明细和源文件仍会保留。</small></span></label>` : "";
  const preparation = preview.summary?.preparation;
  let preparationSummary = preparation ? `<div class="match-summary"><div><span>统一考试</span><strong>${escapeHtml(preparation.grade)} · ${escapeHtml(preparation.exam_name)} · ${escapeHtml(preparation.exam_month)}</strong></div><div><span>身份匹配</span><strong>${fmtInt(preparation.matched_rows)} 条成功</strong><small>${fmtInt(preparation.unmatched_rows)} 条未匹配 · ${fmtInt(preparation.ambiguous_rows)} 条有歧义</small></div><a class="secondary compact button-link" href="/api/import/${encodeURIComponent(preview.batch_key)}/workbook">下载已匹配工作簿</a></div>` : "";
  const timings = preview.summary?.timings || {};
  const totalSeconds = Number(timings["导入预检总耗时"] ?? 0);
  const timingItems = Object.entries(timings).filter(([key]) => key !== "导入预检总耗时" && !key.endsWith("合计"));
  const performanceSummary = timingItems.length ? `<section class="callout ${totalSeconds > 60 ? "warning" : ""}"><strong>${totalSeconds > 60 ? "预检超过 60 秒，请查看耗时阶段" : "导入与预检耗时"}</strong><span class="performance-total">${totalSeconds.toFixed(2)} 秒</span><div class="performance-breakdown">${timingItems.map(([key,value]) => `<span>${escapeHtml(key)} ${Number(value).toFixed(2)} 秒</span>`).join("")}</div></section>` : "";
  preparationSummary += performanceSummary;
  let decision;
  if (committed) {
    const result = preview.commit_result;
    decision = `<div class="callout success"><strong>${preview.status === "committed_partial" ? "有效数据已部分保存" : "本批次已完成入库"}</strong>${result ? `：写入 ${fmtInt(result.committed_rows)} 条，阻止项跳过 ${fmtInt(result.blocked_rows_skipped || 0)} 条。` : ""} 可从最近导入批次随时重新查看本次校验记录。</div>`;
  } else if (!validRows) {
    decision = '<div class="callout danger"><strong>当前没有可安全保存的成绩行。</strong><br>请根据阻止项修正源文件后重新上传；本次预检结果和原文件已经保留。</div>';
  } else {
    decision = `<div class="confirmation-list">${warningCheck}${partialCheck}</div><div class="commit-toolbar"><label>重复数据处理<select id="commitMode"><option value="reject">发现重复则取消</option><option value="append">只追加新记录</option><option value="replace">覆盖已有成绩</option></select></label><div class="button-row"><button class="primary" id="commitButton" disabled>${preview.error_count ? "仅保存有效数据并进入分析" : "确认正式入库"}</button><button class="secondary" id="keepPreviewButton">保留结果，稍后处理</button></div></div><p class="micro-note">${preview.error_count ? `本次只会保存 ${fmtInt(validRows)} 条有效成绩；${fmtInt(blockedRows)} 条问题成绩不会入库。` : `本次将保存 ${fmtInt(validRows)} 条有效成绩。`}页面切换不会清除本次预检，源文件和问题记录也会继续留档。</p>`;
  }
  panel.innerHTML = `${preparationSummary}<div class="validation-summary" id="previewOverview"><button class="validation-stat neutral" data-import-target="previewOverview"><span>成绩记录</span><strong>${fmtInt(preview.summary?.score_rows || 0)}</strong><small>本次识别总行数</small></button><button class="validation-stat success" data-import-target="importDecision"><span>可保存有效行</span><strong>${fmtInt(validRows)}</strong><small>通过行级安全检查</small></button><button class="validation-stat danger" data-import-target="errorIssues"><span>阻止入库</span><strong>${fmtInt(preview.error_count)}</strong><small>${fmtInt(blockedRows)} 条成绩行受影响</small></button><button class="validation-stat warning" data-import-target="warningIssues"><span>允许入库但需确认</span><strong>${fmtInt(preview.warning_count)}</strong><small>保存前需人工核对</small></button></div><nav class="validation-locators" aria-label="校验结果定位"><span>一键定位</span><button data-import-target="errorIssues">阻止项及原因</button><button data-import-target="warningIssues">需确认提醒</button><button data-import-target="importDecision">保存与分析</button></nav><div class="validation-groups"><section class="validation-group error anchor-section" id="errorIssues"><div class="validation-group-title"><div><span class="validation-icon">!</span><div><h4>阻止入库及原因</h4><p>逐项显示工作表、行号、字段、原始值和处理建议</p></div></div><span class="pill red">${fmtInt(preview.error_count)} 项</span></div><div id="errorIssueContent"></div></section><section class="validation-group warning anchor-section" id="warningIssues"><div class="validation-group-title"><div><span class="validation-icon">i</span><div><h4>允许入库但需确认</h4><p>核对自动识别、自动修正和成绩差异提醒</p></div></div><span class="pill amber">${fmtInt(preview.warning_count)} 项</span></div><div id="warningIssueContent"></div></section></div><section class="import-decision anchor-section" id="importDecision"><div class="card-title"><div><h3>保存与分析</h3><small>预检结果不会因切换页面而清除</small></div></div>${decision}</section>`;
  bindImportLocators();
  await Promise.all([
    loadImportIssues(preview, "error", state.importIssuePages.error),
    loadImportIssues(preview, "warning", state.importIssuePages.warning),
  ]);
  const requiredChecks = [...content.querySelectorAll("#importDecision .confirmation-check input")];
  const commitButton = content.querySelector("#commitButton");
  const updateCommitState = () => { if (commitButton) commitButton.disabled = requiredChecks.some(input => !input.checked); };
  requiredChecks.forEach(input => input.addEventListener("change", updateCommitState));
  updateCommitState();
  commitButton?.addEventListener("click", () => commitImportPreview(preview));
  content.querySelector("#keepPreviewButton")?.addEventListener("click", () => showToast("本次预检和上传文件已保留，可从最近导入批次继续处理"));
}

async function renderImport() {
  const demo = await api("/api/demo-data");
  content.innerHTML = `
    <div class="section-heading"><div><h2>基础信息与成绩导入</h2><p>基础信息只需上传一次并自动保存；每次只上传本次成绩表。</p></div><span class="meta">支持 .xlsx，单文件 100 MB</span></div>
    <div class="import-stack">
      ${demo.students ? `<article class="card card-pad"><h3>系统演示数据</h3><p>当前含 ${fmtInt(demo.students)} 名化名学生、${fmtInt(demo.exams)} 场演示考试。这些数据由演示功能生成，不属于上传批次。导入本校数据前，请先清除演示数据。</p><button class="danger-button" id="clearDemoData">清除系统演示数据</button><p class="micro-note">仅清除系统标记的演示记录，保留用户上传的数据和文件。</p></article>` : ""}
      <article class="card card-pad"><div class="card-title"><div><h3>学校与学生基础信息</h3><small>模板包含“学校信息、学生信息”两个子表；选科标签和特控目标可留空。</small></div></div><form id="baseUploadForm" class="button-row"><input type="file" id="baseFile" name="file" accept=".xlsx" disabled><button class="secondary" type="button" data-choose-file="baseFile" disabled>上传基础信息表</button><span class="file-chip" id="baseTitle">尚未选择文件</span></form><div id="baseUploadFeedback" role="status" aria-live="polite"></div><details class="base-details"><summary>查看和手动维护已保存的基础信息</summary><form id="baseClassCreate" class="form-grid" style="margin-top:12px"><label>学校<input name="school_name" required></label><label>年级<input name="grade_name" placeholder="高2026届" required></label><label>班级<input name="class_name" required></label><label>省份<input name="province"></label><label>班级人数<input type="number" name="planned_size"></label><label>特控目标<input type="number" name="control_target"></label><button class="secondary compact">新增或更新班级</button></form><div id="baseInformationCards" class="card-grid"></div><form id="baseStudentCreate" class="form-grid" style="margin-top:16px"><label>学校<input name="school_name" required></label><label>年级<input name="grade_name" required></label><label>班级<input name="class_name" required></label><label>姓名<input name="student_name" required></label><label>学号<input name="student_no" required></label><label>选科标签<input name="subject_tag" placeholder="可留空"></label><button class="secondary compact">新增或更新学生</button></form><div id="baseStudentCards" class="card-grid"></div></details></article>
      <article class="card card-pad import-upload-card"><div class="card-title"><div><h3>导入本次学生成绩</h3><small>已保存的基础信息会自动匹配并补齐身份字段；系统随后清洗表头、识别方向和选科。</small></div><span class="pill">本次考试</span></div><form id="uploadForm"><div class="upload-pair-grid"><section class="file-picker-card"><span class="file-step">01</span><div><h4>学生成绩表</h4><p>支持物理、历史方向子表；已选科目必须填写赋分，中文排名可留空。</p></div><input type="file" name="score_file" id="scoreFile" accept=".xlsx"><button class="secondary" type="button" data-choose-file="scoreFile">选择成绩表</button><span class="file-chip" id="scoreTitle">尚未选择文件</span></section></div><div class="exam-context"><div class="exam-context-heading"><span class="file-step">02</span><div><h4>本次考试统一信息</h4><p>系统会写入规范工作簿，不会改动原始上传文件。</p></div></div><div class="form-grid three-fields"><label>年级<input type="text" name="grade" id="importGrade" placeholder="高2026届" pattern="高20[0-9]{2}届" required></label><label>考试名称<input type="text" name="exam_name" id="importExamName" placeholder="如：高三上第二次月考" maxlength="80" required></label><label>考试时间<input type="text" name="exam_month" id="importExamMonth" placeholder="2025年10月" pattern="20[0-9]{2}年(0?[1-9]|1[0-2])月" required></label></div></div><div class="preview-actions"><button class="primary" type="submit" id="previewButton">开始预检</button><p>身份优先按学号匹配，选科标签为空时根据实际有分数的科目自动识别。</p></div></form></article>
      <article class="card card-pad import-preview-card anchor-section" id="previewSection"><div class="card-title"><div><h3>数据检验结果</h3><small>分类浏览全部问题，并在保存前逐项确认</small></div><span class="pill" id="previewStatus">等待文件</span></div><div id="previewResult"><div class="callout">系统会检查必填字段、重复学生、成绩范围、总分合计、分数线顺序、学生匹配以及年级排名差异（分数降序、同分同名次跳号）；排名差异只提示，以系统计算为准。</div></div></article>
      <article class="card card-pad import-history-card"><div class="card-title"><div><h3>最近成功导入</h3><small id="batchCount">已成功上传 0 次</small></div><div class="button-row"><button class="secondary" id="reloadBatches">刷新</button><button class="danger-button" id="clearImportCache">清除全部上传数据</button></div></div><div class="table-wrap batch-table"><table><thead><tr><th>输出文件 / 考试</th><th>成功时间</th><th>入库成绩</th><th>状态</th><th>操作</th></tr></thead><tbody id="batchRows"></tbody></table></div><p class="micro-note">这里只展示已经成功入库的批次。清除单个批次会同步移除该批次当前关联的成绩；清除全部不会删除系统演示数据。</p></article>
    </div>`;
  await loadBatches();
  content.querySelector("#clearDemoData")?.addEventListener("click", async event => {
    if (!window.confirm("只清除系统演示数据？用户上传的数据和文件会保留。此操作无法撤销。")) return;
    const button = event.currentTarget;
    button.disabled = true;
    try {
      const result = await api("/api/demo-data", {method:"DELETE", headers:{"Content-Type":"application/json"}, body:JSON.stringify({confirmed:true})});
      state.preview = null;
      await refreshExams();
      await renderImport();
      showToast(`已清除 ${fmtInt(result.students)} 名演示学生、${fmtInt(result.exams)} 场演示考试`);
    } catch (error) { showToast(error.message, "error"); button.disabled = false; }
  });
  const scoreInput = content.querySelector("#scoreFile");
  const baseInput = content.querySelector("#baseFile");
  content.querySelectorAll("[data-choose-file]").forEach(button => button.addEventListener("click", () => content.querySelector(`#${button.dataset.chooseFile}`).click()));
  baseInput.addEventListener("change", () => { content.querySelector("#baseTitle").textContent = baseInput.files[0]?.name || "尚未选择文件"; });
  scoreInput.addEventListener("change", () => { content.querySelector("#scoreTitle").textContent = scoreInput.files[0]?.name || "尚未选择文件"; });
  content.querySelectorAll("[data-exam-example]").forEach(button => button.addEventListener("click", () => { content.querySelector("#importExamName").value = button.dataset.examExample; }));
  async function loadBaseInformation(page=1) {
    const data = await api(`/api/base-information?page=${page}&page_size=12`);
    const cards = data.items.map(item => `<article class="card card-pad"><strong>${escapeHtml(item.school_name)} · ${escapeHtml(item.class_name)}班</strong><small>${escapeHtml(item.province || "待补充省份")} · ${escapeHtml(item.grade_name)} · ${fmtInt(item.student_count)} 名学生</small><div class="form-grid"><label>班级人数<input data-base="planned_size" type="number" value="${item.planned_size ?? ""}"></label><label>特控目标<input data-base="control_target" type="number" value="${item.control_target ?? ""}"></label></div><div class="button-row"><button class="secondary compact" data-save-base="${item.id}">保存</button><button class="danger-button compact" data-delete-base="${item.id}">删除</button></div></article>`).join("") || '<div class="callout">尚未保存基础信息。</div>';
    content.querySelector("#baseInformationCards").innerHTML = `${cards}<div class="pagination"><button class="secondary compact" data-base-page="${Math.max(1,data.page-1)}" ${data.page===1?"disabled":""}>上一页</button><span>${data.page} / ${Math.max(1,Math.ceil(data.total/data.page_size))}</span><button class="secondary compact" data-base-page="${data.page+1}" ${data.page*data.page_size>=data.total?"disabled":""}>下一页</button></div>`;
    content.querySelectorAll("[data-base-page]").forEach(button => button.addEventListener("click",()=>loadBaseInformation(Number(button.dataset.basePage))));
    content.querySelectorAll("[data-save-base]").forEach(button => button.addEventListener("click", async () => { const card=button.closest("article"); await api(`/api/base-information/classes/${button.dataset.saveBase}`, {method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify({planned_size:card.querySelector('[data-base="planned_size"]').value,control_target:card.querySelector('[data-base="control_target"]').value})}); showToast("基础信息已保存"); }));
    content.querySelectorAll("[data-delete-base]").forEach(button => button.addEventListener("click", async () => { if(!confirm("删除该班级及其基础学生信息？")) return; await api(`/api/base-information/classes/${button.dataset.deleteBase}`,{method:"DELETE"}); await loadBaseInformation(page); }));
  }
  await loadBaseInformation();
  async function loadBaseStudents(page=1) {
    const data=await api(`/api/base-information/students?page=${page}&page_size=12`);
    const cards=data.items.map(item=>`<article class="card card-pad"><strong>${escapeHtml(item.student_name)}</strong><small>${escapeHtml(item.school_name)} · ${escapeHtml(item.grade_name)} · ${escapeHtml(item.class_name)}班 · ${escapeHtml(item.student_no)}</small><div class="button-row"><span class="pill">${escapeHtml(item.subject_tag || "待自动识别")}</span><button class="danger-button compact" data-delete-student="${item.id}">删除</button></div></article>`).join("") || '<div class="callout">尚未保存学生基础信息。</div>';
    content.querySelector("#baseStudentCards").innerHTML=`${cards}<div class="pagination"><button class="secondary compact" data-student-page="${Math.max(1,data.page-1)}" ${data.page===1?"disabled":""}>上一页</button><span>${data.page} / ${Math.max(1,Math.ceil(data.total/data.page_size))}</span><button class="secondary compact" data-student-page="${data.page+1}" ${data.page*data.page_size>=data.total?"disabled":""}>下一页</button></div>`;
    content.querySelectorAll("[data-student-page]").forEach(button=>button.addEventListener("click",()=>loadBaseStudents(Number(button.dataset.studentPage))));
    content.querySelectorAll("[data-delete-student]").forEach(button=>button.addEventListener("click",async()=>{if(!confirm("删除该学生基础信息？"))return;await api(`/api/base-information/students/${button.dataset.deleteStudent}`,{method:"DELETE"});await loadBaseStudents(page);}));
  }
  await loadBaseStudents();
  content.querySelector("#baseClassCreate").addEventListener("submit", async event => { event.preventDefault(); const form=new FormData(event.currentTarget); try { await api("/api/base-information/classes",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(Object.fromEntries(form.entries()))}); event.currentTarget.reset(); showToast("基础班级已保存"); await loadBaseInformation(); } catch(error) { showToast(error.message,"error"); } });
  content.querySelector("#baseStudentCreate").addEventListener("submit", async event => { event.preventDefault(); const form=new FormData(event.currentTarget); try { await api("/api/base-information/students",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(Object.fromEntries(form.entries()))}); event.currentTarget.reset(); showToast("基础学生已保存"); await loadBaseStudents(); } catch(error) { showToast(error.message,"error"); } });
  content.querySelector("#baseUploadForm").addEventListener("submit", event => event.preventDefault());
  content.querySelector("#baseUploadForm [data-choose-file]").addEventListener("click", () => {});
  baseInput.addEventListener("change", async () => {
    if (!baseInput.files.length) return;
    const feedback = content.querySelector("#baseUploadFeedback");
    feedback.textContent = "正在保存基础信息…";
    const form = new FormData(); form.append("file", baseInput.files[0]);
    try {
      const result = await api("/api/base-information/upload", {method:"POST", body:form});
      feedback.textContent = `已保存 ${fmtInt(result.school_classes)} 个班级、${fmtInt(result.students)} 名学生`;
      showToast(feedback.textContent);
      await loadBaseInformation();
      await loadBaseStudents();
    } catch (error) {
      feedback.textContent = error.message;
      showToast(error.message, "error");
    } finally { baseInput.value = ""; }
  });
  baseInput.disabled = false;
  content.querySelector('[data-choose-file="baseFile"]').disabled = false;
  content.querySelector("#reloadBatches").addEventListener("click", loadBatches);
  content.querySelector("#clearImportCache").addEventListener("click", async event => {
    if (!window.confirm("将清除全部上传批次、当前关联成绩和留存文件。是否继续？")) return;
    if (!window.confirm("此操作无法撤销。请再次确认清除全部上传数据。")) return;
    const button = event.currentTarget; button.disabled = true; button.textContent = "正在清除…";
    try {
      const result = await api("/api/import/cache", {method:"DELETE"});
      state.preview = null;
      showToast(`已清除 ${fmtInt(result.deleted_batches)} 个批次和 ${fmtInt(result.deleted_results)} 条当前关联成绩`);
      await refreshExams();
      await renderImport();
    } catch (error) { showToast(error.message, "error"); button.disabled = false; button.textContent = "清除全部上传数据"; }
  });
  if (state.preview) await renderImportPreview(state.preview);
  content.querySelector("#uploadForm").addEventListener("submit", async event => {
    event.preventDefault();
    if (!scoreInput.files.length) return showToast("请选择本次学生成绩表", "error");
    const button = content.querySelector("#previewButton"); button.disabled = true; button.textContent = "正在匹配并预检…";
    try {
      const form = new FormData(event.currentTarget);
      state.preview = await api("/api/import/prepare", { method: "POST", body: form });
      state.importIssuePages = { error: 1, warning: 1 };
      await renderImportPreview(state.preview);
      content.querySelector("#previewSection")?.scrollIntoView({behavior:"smooth", block:"start"});
      await loadBatches();
    } catch (error) { showToast(error.message, "error"); }
    finally { button.disabled = false; button.textContent = "匹配信息并开始预检"; }
  });
}

async function renderExport() {
  const current = currentExam() || state.exams[0];
  if (!state.exportInitialized) {
    Object.entries(state.exportFilters).forEach(([_key,filter]) => {
      filter.grades = current ? [current.grade] : [];
      filter.examKeys = current ? [current.exam_key] : [];
    });
    state.exportInitialized = true;
  }
  const grades = [...new Set(state.exams.map(item => item.grade))].sort((a,b)=>a.localeCompare(b,"zh-CN"));
  const validGradeSet = new Set(grades);
  const examByKey = new Map(state.exams.map(item => [item.exam_key,item]));
  Object.entries(state.exportFilters).forEach(([_key,filter]) => {
    filter.grades = filter.grades.filter(grade => validGradeSet.has(grade));
    filter.examKeys = filter.examKeys.filter(key => examByKey.has(key) && filter.grades.includes(examByKey.get(key).grade));
  });
  const optionsCache = new Map();
  const loadOptions = examKeys => {
    if (!examKeys.length) return Promise.resolve({organizations:[],classes:[]});
    const cacheKey = [...examKeys].sort().join("|");
    if (!optionsCache.has(cacheKey)) {
      const params = new URLSearchParams();
      examKeys.forEach(key => params.append("exam_keys",key));
      optionsCache.set(cacheKey,api(`/api/export/options?${params}`));
    }
    return optionsCache.get(cacheKey);
  };
  const classOptions = await loadOptions(state.exportFilters.classes.examKeys);
  const normalizeScope = (filter, options) => {
    const organizationIds = new Set(options.organizations.map(item=>String(item.id)));
    filter.organizationIds = filter.organizationIds.filter(id=>organizationIds.has(String(id)));
    const selectedOrganizations = new Set(filter.organizationIds.map(String));
    const visibleClasses = options.classes.filter(item=>!selectedOrganizations.size || selectedOrganizations.has(String(item.organization_id)));
    const classIds = new Set(visibleClasses.map(item=>String(item.id)));
    filter.classIds = filter.classIds.filter(id=>classIds.has(String(id)));
    return visibleClasses;
  };
  const visibleClassOptions = normalizeScope(state.exportFilters.classes,classOptions);
  const gradeOptions = grades.map(grade=>({value:grade,label:grade}));
  const examOptions = filter => state.exams.filter(item=>filter.grades.includes(item.grade)).slice().sort((a,b)=>a.grade.localeCompare(b.grade,"zh-CN") || a.exam_date.localeCompare(b.exam_date) || a.name.localeCompare(b.name,"zh-CN")).map(item=>({value:item.exam_key,label:item.name,description:`${item.grade} · ${item.exam_date}`}));
  const organizationOptions = options => options.organizations.map(item=>({value:item.id,label:item.name}));
  const classPickerOptions = classes => classes.map(item=>({value:item.id,label:`${item.organization_name} · ${item.class_name}班`,description:`${item.track}方向`}));
  const card = (key,index,title,description,extra="") => {
    const filter = state.exportFilters[key];
    const options = key === "classes" ? classOptions : {organizations:[],classes:[]};
    return `<article class="card card-pad export-filter-card" data-export-card="${key}"><div class="card-title"><div class="export-title"><span class="export-index">${index}</span><div><h3>${title}</h3><p>${description}</p></div></div><button class="primary" data-export-key="${key}">导出</button></div><div class="export-filter-row">${renderMultiSelect(`${key}-grades`,"年级",gradeOptions,filter.grades,"搜索年级")}${renderMultiSelect(`${key}-exams`,"考试",examOptions(filter),filter.examKeys,"搜索考试")}${key === "classes"?renderMultiSelect(`${key}-organizations`,"学校",organizationOptions(options),filter.organizationIds,"搜索学校"):""}${key==="classes"?renderMultiSelect(`${key}-classes`,"班级",classPickerOptions(visibleClassOptions),filter.classIds,"搜索学校或班级"):""}${extra}</div></article>`;
  };
  content.innerHTML = `<div class="section-heading"><div><h2>标准交付文件</h2><p>选择考试和班级，生成按考试、班级分组的 Excel 文件压缩包。</p></div><span class="meta">模板版本 ${escapeHtml(state.metadata.export_template_version)}</span></div><div class="export-card-stack">
    ${card("classes","1","班级成绩表","仅生成已选考试、学校和班级；同名班级按考试目录隔离。")}
  </div><div class="callout warning" style="margin-top:16px">未选择学校或班级表示当前已选考试范围内全部；文件包含学生及学校信息，请仅在授权范围内保存和传递。</div>`;
  const rerender = () => renderExport();
  const bindFilter = key => {
    const filter = state.exportFilters[key];
    bindMultiSelect(content,`${key}-grades`,values=>{filter.grades=values;filter.examKeys=filter.examKeys.filter(examKey=>values.includes(examByKey.get(examKey)?.grade));filter.organizationIds=[];filter.classIds=[];rerender();});
    bindMultiSelect(content,`${key}-exams`,values=>{filter.examKeys=values;rerender();});
    bindMultiSelect(content,`${key}-organizations`,values=>{filter.organizationIds=values;filter.classIds=[];rerender();});
    bindMultiSelect(content,`${key}-classes`,values=>{filter.classIds=values;});
  };
  Object.keys(state.exportFilters).forEach(bindFilter);
  const endpoints = {classes:"/api/export/classes"};
  content.querySelectorAll("[data-export-key]").forEach(button=>button.addEventListener("click",()=>{
    const key=button.dataset.exportKey,filter=state.exportFilters[key];
    if (!filter.examKeys.length) return showToast("请至少选择一场考试。","error");
    const params=new URLSearchParams({exam_key:filter.examKeys[0]});
    filter.examKeys.forEach(value=>params.append("exam_keys",value));
    if (key === "classes") filter.organizationIds.forEach(value=>params.append("organization_ids",value));
    if (key === "classes") filter.classIds.forEach(value=>params.append("class_ids",value));
    triggerDownload(`${endpoints[key]}?${params}`,button,"导出");
  }));
}

function benchmarkTrackCard(data, track, mode) {
  const trackData = data.tracks[track];
  const subjectOrder = ["chinese", "math", "english", track === "物理" ? "physics" : "history", "chemistry", "biology", "politics", "geography"];
  const displaySubjects = [...trackData.grade_averages.subjects].sort((a,b) => subjectOrder.indexOf(a.code) - subjectOrder.indexOf(b.code));
  const columns = [{code:"__TOTAL__",name:"总分"},...displaySubjects.map(item=>({code:item.code,name:item.name}))];
  if (mode === "averages") {
    const averages = new Map(trackData.grade_averages.subjects.map(item=>[item.code,item.average]));
    return `<div class="benchmark-track"><div class="benchmark-track-title"><strong>${track}方向</strong><small>已导入 ${trackData.reference_count} 人 / ${trackData.class_count} 个班；请核对全年级覆盖</small></div><div class="table-wrap"><table><thead><tr><th>维度</th>${columns.map(item=>`<th>${escapeHtml(item.name)}</th>`).join("")}</tr></thead><tbody><tr><td><strong>年级均分</strong></td>${columns.map(item=>`<td class="numeric">${fmt(item.code === "__TOTAL__" ? trackData.grade_averages.total : averages.get(item.code))}</td>`).join("")}</tr><tr><td>有效人数</td>${columns.map(item=>`<td class="numeric">${item.code === "__TOTAL__" ? trackData.reference_count : (trackData.grade_averages.subjects.find(subject=>subject.code===item.code)?.reference_count ?? 0)}</td>`).join("")}</tr></tbody></table></div></div>`;
  }
  const subjectLines = new Map(trackData.subject_lines.map(item=>[item.code,item.lines||{}]));
  const rows = ["本科","特控","211","985"].map(lineType=>`<tr class="${lineType === "本科" ? "total-line-row" : ""}"><td><strong>${lineType}</strong></td>${columns.map(item=>{
    if (item.code === "__TOTAL__") return `<td><input class="line-cell-input" type="number" min="0" max="750" step="0.5" name="total:${lineType}" value="${trackData.total_lines[lineType] ?? ""}" aria-label="总分${lineType}线"></td>`;
    if (lineType === "本科") return '<td class="numeric">—</td>';
    return `<td><input class="line-cell-input" type="number" min="0" max="150" step="0.5" name="subject:${item.code}:${lineType}" value="${subjectLines.get(item.code)?.[lineType] ?? ""}" aria-label="${escapeHtml(item.name)}${lineType}线"></td>`;
  }).join("")}</tr>`).join("");
  return `<form class="benchmark-line-form benchmark-track" data-exam-key="${escapeHtml(data.exam.exam_key)}" data-track="${track}"><div class="benchmark-track-title"><strong>${track}方向</strong><button class="primary compact" type="submit">保存本方向最终划线</button></div><div class="table-wrap"><table class="line-edit-table"><thead><tr><th>划线</th>${columns.map(item=>`<th>${escapeHtml(item.name)}</th>`).join("")}</tr></thead><tbody>${rows}</tbody></table></div></form>`;
}

async function renderBenchmark() {
  if (!state.benchmarkInitialized) {
    state.benchmarkExamKeys = state.filters.exam_key ? [state.filters.exam_key] : [];
    state.benchmarkGrades = currentExam() ? [currentExam().grade] : [];
    state.benchmarkInitialized = true;
  }
  const grades = [...new Set(state.exams.map(item=>item.grade))].sort((a,b)=>a.localeCompare(b,"zh-CN"));
  state.benchmarkGrades = state.benchmarkGrades.filter(grade=>grades.includes(grade));
  state.benchmarkExamKeys = state.benchmarkExamKeys.filter(key => state.exams.some(exam => exam.exam_key === key && state.benchmarkGrades.includes(exam.grade)));
  const selectedData = await Promise.all(state.benchmarkExamKeys.map(key => api(`/api/analytics/benchmark?exam_key=${encodeURIComponent(key)}`)));
  const gradeOptions = grades.map(grade=>({value:grade,label:grade}));
  const examOptions = state.exams.filter(item=>state.benchmarkGrades.includes(item.grade)).slice().sort((a,b)=>a.grade.localeCompare(b.grade,"zh-CN") || a.exam_date.localeCompare(b.exam_date)).map(item=>({value:item.exam_key,label:item.name,description:`${item.grade} · ${item.exam_date}`}));
  const sectionCards = (mode, emptyText) => selectedData.map(data => `<article class="card card-pad benchmark-exam-card"><div class="card-title"><div><h3>${escapeHtml(data.exam.name)}</h3><small>${escapeHtml(data.exam.grade)} · ${escapeHtml(data.exam.date)}</small></div><span class="pill">物理在上 · 历史在下</span></div><div class="benchmark-track-grid">${benchmarkTrackCard(data,"物理",mode)}${benchmarkTrackCard(data,"历史",mode)}</div>${mode === "lines" ? `<div class="callout" style="margin-top:14px"><strong>系统推导口径：</strong>${escapeHtml(data.line_formula)}，${escapeHtml(data.rounding)}。保存后的手动值优先于推导值，并成为本次考试后续看板与导出的最终划线。</div>` : ""}</article>`).join("") || `<div class="card empty-state"><p>${emptyText}</p></div>`;
  content.innerHTML = `<div class="section-heading"><div><h2>历次年级数据</h2><p>按“年级＋考试”统一多选；选择几场就纵向展示几场，不再限制 3 场。</p></div><span class="meta">已选 ${state.benchmarkExamKeys.length} 场</span></div>
    <article class="card card-pad benchmark-picker"><div class="card-title"><div><h3>选择要查看的考试</h3><small>同一套筛选同时控制年级平均分和考试划线数据</small></div></div><div class="benchmark-filter-row">${renderMultiSelect("benchmark-grades","年级",gradeOptions,state.benchmarkGrades,"搜索年级")}${renderMultiSelect("benchmark-exams","考试",examOptions,state.benchmarkExamKeys,"搜索考试")}</div></article>
    <details class="benchmark-section benchmark-collapsible" data-benchmark-section="averages" ${state.benchmarkSections.averages?'open':''}><summary><span><strong>年级平均分</strong><small>按本校同次考试同方向已导入有效成绩自动计算，班级筛选不改变年级基准。</small></span><span class="collapse-hint">展开 / 折叠</span></summary><div class="benchmark-exam-grid">${sectionCards("averages","请先从上方选择考试")}</div></details>
    <details class="benchmark-section benchmark-collapsible" data-benchmark-section="lines" ${state.benchmarkSections.lines?'open':''}><summary><span><strong>考试划线数据</strong><small>总分线手动输入；单科线初始由系统推导，也可逐项修订并保存为最终值。</small></span><span class="collapse-hint">展开 / 折叠</span></summary><div class="benchmark-exam-grid">${sectionCards("lines","请先从上方选择考试")}</div></details>`;
  bindMultiSelect(content,"benchmark-grades",values=>{state.benchmarkGrades=values;state.benchmarkExamKeys=state.benchmarkExamKeys.filter(key=>values.includes(state.exams.find(item=>item.exam_key===key)?.grade));renderBenchmark();});
  bindMultiSelect(content,"benchmark-exams",values=>{state.benchmarkExamKeys=values;renderBenchmark();});
  content.querySelectorAll("[data-benchmark-section]").forEach(section=>section.addEventListener("toggle",()=>{state.benchmarkSections[section.dataset.benchmarkSection]=section.open;}));
  content.querySelectorAll(".benchmark-line-form").forEach(form => form.addEventListener("submit", async event => {
    event.preventDefault();
    const values = new FormData(form), payload = {exam_key:form.dataset.examKey, track:form.dataset.track, subject_lines:{}};
    for (const [name,value] of values.entries()) {
      if (String(value).trim() === "") continue;
      const parts = name.split(":");
      if (parts[0] === "total") payload[parts[1]] = value;
      if (parts[0] === "subject") (payload.subject_lines[parts[1]] ||= {})[parts[2]] = value;
    }
    const button = form.querySelector("button[type=submit]"); button.disabled = true;
    try { await api("/api/settings/score-lines", {method:"PUT", headers:{"Content-Type":"application/json"}, body:JSON.stringify(payload)}); showToast(`${form.dataset.track}方向划线已保存`); await renderBenchmark(); }
    catch (error) { showToast(error.message,"error"); button.disabled = false; }
  }));
}

async function renderSettings() {
  const definitions = state.metadata.definitions;
  const labels = { contribution_rate: "贡献率", effective_total: "有效总分", hit_rate: "命中率", reference_count: "参考人数", standard_deviation: "标准差", score_band_boundary: "分数段边界", subject_line: "单科划线" };
  const benchmark = await api(`/api/analytics/benchmark?exam_key=${encodeURIComponent(state.filters.exam_key)}`);
  const settingsTrack = state.filters.track || "物理";
  const trackData = benchmark.tracks[settingsTrack];
  const averageRows = trackData.grade_averages.subjects.map(item => `<tr><td>${escapeHtml(item.name)}</td><td class="numeric">${fmt(item.average)}</td><td class="numeric">${fmt(trackData.subject_lines.find(line => line.code === item.code)?.lines?.["特控"])}</td><td class="numeric">${fmt(trackData.subject_lines.find(line => line.code === item.code)?.lines?.["211"])}</td><td class="numeric">${fmt(trackData.subject_lines.find(line => line.code === item.code)?.lines?.["985"])}</td></tr>`).join("");
  content.innerHTML = `<div class="section-heading"><div><h2>年级数据、总分线与单科线</h2><p>对应标准表“年级数据”；修改后考试数据版本自动递增。</p></div><span class="meta">${escapeHtml(state.metadata.rule_version)}</span></div><div class="grid two-col"><article class="card card-pad"><div class="card-title"><h3>总分线配置</h3><span class="pill">${state.filters.track}方向</span></div><form id="lineForm"><div class="form-grid"><label>本科线<input type="number" name="本科" min="0" max="750" step="0.5" value="${trackData.total_lines["本科"] ?? ""}"></label><label>特控线<input type="number" name="特控" min="0" max="750" step="0.5" value="${trackData.total_lines["特控"] ?? ""}"></label><label>211线<input type="number" name="211" min="0" max="750" step="0.5" value="${trackData.total_lines["211"] ?? ""}"></label><label>985线<input type="number" name="985" min="0" max="750" step="0.5" value="${trackData.total_lines["985"] ?? ""}"></label></div><button class="primary" style="margin-top:16px">保存分数线</button></form></article></div><article class="card card-pad" style="margin-top:16px"><div class="card-title"><h3>年级平均分与系统推导单科线</h3><span class="pill">按0.5舍入</span></div><div class="table-wrap"><table><thead><tr><th>学科</th><th>年级平均分</th><th>特控单科线</th><th>211单科线</th><th>985单科线</th></tr></thead><tbody><tr><td><strong>总分</strong></td><td class="numeric">${fmt(trackData.grade_averages.total)}</td><td class="numeric">${fmt(trackData.total_lines["特控"])}</td><td class="numeric">${fmt(trackData.total_lines["211"])}</td><td class="numeric">${fmt(trackData.total_lines["985"])}</td></tr>${averageRows}</tbody></table></div><div class="callout" style="margin-top:14px">${escapeHtml(benchmark.line_formula)}；${escapeHtml(benchmark.rounding)}。总分分数段按左闭右开计算。</div></article><article class="card card-pad" style="margin-top:16px"><div class="card-title"><h3>不可变核心口径</h3></div><div class="definition-grid">${Object.entries(definitions).map(([key,value]) => `<div class="definition"><strong>${escapeHtml(labels[key] || key)}</strong><p>${escapeHtml(value)}</p></div>`).join("")}</div></article>`;
  content.querySelector("#lineForm").closest("article").querySelector(".pill").textContent = `${settingsTrack}方向`;
  content.querySelector("#lineForm").addEventListener("submit", async event => {
    event.preventDefault(); const form = new FormData(event.target);
    try {
      const payload = {exam_key:state.filters.exam_key, track:settingsTrack};
      for (const lineType of ["本科","特控","211","985"]) {
        const value = form.get(lineType);
        if (String(value).trim() !== "") payload[lineType] = value;
      }
      await api("/api/settings/score-lines", { method:"PUT", headers:{"Content-Type":"application/json"}, body: JSON.stringify(payload) });
      showToast("总分线已保存；未手动修订的单科线已重新推导"); await renderSettings();
    } catch (error) { showToast(error.message, "error"); }
  });
}

const renderers = { overview: renderOverview, classes: renderClasses, bands: renderBands, subjects: renderSubjects, groups: renderGroups, students: renderStudents, import: renderImport, benchmark: renderBenchmark, export: renderExport, settings: renderSettings };

async function renderCurrent() {
  const analysisView = ["overview","classes","bands","subjects","groups","students","benchmark","export","settings"].includes(state.view);
  filterStrip.style.display = ["import","benchmark","export"].includes(state.view) ? "none" : "flex";
  if (analysisView && !state.filters.exam_key) return emptyDatabase();
  loading();
  try { await renderers[state.view](); }
  catch (error) { content.innerHTML = `<div class="callout danger"><strong>页面加载失败</strong><br>${escapeHtml(error.message)}</div>`; }
}

async function switchView(view) {
  state.view = view;
  document.querySelectorAll(".nav-item").forEach(item => item.classList.toggle("active", item.dataset.view === view));
  document.querySelector("#pageEyebrow").textContent = viewMeta[view][0];
  document.querySelector("#pageTitle").textContent = viewMeta[view][1];
  window.scrollTo({top:0, behavior:"smooth"});
  await renderCurrent();
}

function setChromeCollapsed(kind, collapsed) {
  const shell = document.querySelector(".app-shell");
  shell.classList.toggle(`${kind}-collapsed`, collapsed);
  localStorage.setItem(`student-analysis-${kind}-collapsed`, collapsed ? "1" : "0");
}

async function refreshExams() {
  const data = await api("/api/exams"); state.exams = data.items;
  const select = document.querySelector("#examFilter");
  select.innerHTML = state.exams.map(item => `<option value="${item.exam_key}">${escapeHtml(item.grade)} · ${escapeHtml(item.name)} · ${item.exam_date}</option>`).join("") || '<option value="">暂无考试</option>';
  if (!state.exams.some(item => item.exam_key === state.filters.exam_key)) state.filters.exam_key = state.exams[0]?.exam_key || "";
  normalizeComparisonSelection();
  persistSelectedScope();
  select.value = state.filters.exam_key;
  syncSearchableSelect(select);
  renderGlobalComparisonFilter();
  if (state.filters.exam_key) await loadFilters();
}

async function initBusiness() {
  try {
    state.metadata = await api("/api/metadata");
    document.querySelector("#ruleBadge").textContent = `口径 ${state.metadata.rule_version}`;
    enhanceSearchableSelect(document.querySelector("#examFilter"), "搜索考试");
    enhanceSearchableSelect(document.querySelector("#targetFilter"), "搜索目标方案");
    enhanceSearchableSelect(document.querySelector("#schoolFilter"), "搜索学校");
    enhanceSearchableSelect(document.querySelector("#classFilter"), "搜索班级");
    await refreshExams();
    document.querySelector("#trackFilter").value = state.filters.track;
    document.querySelector("#windowFilter").value = state.filters.critical_window;
    document.querySelectorAll(".nav-item").forEach(button => button.addEventListener("click", () => switchView(button.dataset.view)));
    document.querySelector("#applyFilters").addEventListener("click", () => { syncFiltersFromDom(); renderCurrent(); });
    document.querySelector("#examFilter").addEventListener("change", async event => { state.filters.exam_key = event.target.value; state.filters.target_name = ""; state.filters.organization_id = ""; state.filters.class_id = ""; normalizeComparisonSelection(true); persistSelectedScope(); renderGlobalComparisonFilter(); await loadFilters(); });
    document.querySelector("#targetFilter").addEventListener("change", event => { state.filters.target_name = event.target.value; state.targetPage=1; persistSelectedScope(); });
    document.querySelector("#trackFilter").addEventListener("change", async event => { state.filters.track = event.target.value; state.filters.class_id = ""; persistSelectedScope(); await loadFilters(); });
    document.querySelector("#schoolFilter").addEventListener("change", async event => { state.filters.organization_id = event.target.value; state.filters.class_id = ""; await loadFilters(); });
    document.querySelector("#refreshButton").addEventListener("click", renderCurrent);
    const sidebarCollapsed = localStorage.getItem("student-analysis-sidebar-collapsed") === "1";
    const topbarCollapsed = localStorage.getItem("student-analysis-topbar-collapsed") === "1";
    setChromeCollapsed("sidebar", sidebarCollapsed);
    setChromeCollapsed("topbar", topbarCollapsed);
    document.querySelector("#sidebarToggle").addEventListener("click", () => setChromeCollapsed("sidebar", true));
    document.querySelector("#sidebarReveal").addEventListener("click", () => setChromeCollapsed("sidebar", false));
    document.querySelector("#topbarToggle").addEventListener("click", () => setChromeCollapsed("topbar", true));
    document.querySelector("#topbarReveal").addEventListener("click", () => setChromeCollapsed("topbar", false));
    await renderCurrent();
  } catch (error) {
    content.innerHTML = `<div class="callout danger"><strong>系统初始化失败</strong><br>${escapeHtml(error.message)}</div>`;
  }
}

async function initLocalApp() {
  const exitDialog = document.querySelector("#desktopExitDialog");
  document.querySelector("#desktopExitButton").onclick = () => exitDialog.showModal();
  document.querySelector("#cancelDesktopExit").onclick = () => exitDialog.close();
  document.querySelector("#confirmDesktopExit").onclick = performDesktopExit;
  businessRoot.hidden = false;
  await initBusiness();
}

document.addEventListener("DOMContentLoaded", initLocalApp);

async function performDesktopExit() {
  document.querySelector("#desktopExitDialog").close();
  const overlay = document.querySelector("#desktopExitState");
  const retry = document.querySelector("#retryDesktopExit");
  overlay.querySelector("h1").textContent = "正在退出student-score-analysis…";
  overlay.querySelector("p").textContent = "正在安全停止本地服务，请稍候。";
  retry.hidden = true;
  overlay.hidden = false;
  document.querySelector("#businessRoot").inert = true;
  retry.onclick = () => { overlay.hidden = true; document.querySelector("#businessRoot").inert = false; };
  // Paint a self-contained state before asking the local service to stop.
  await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  try {
    const tokenResponse = await fetch("/api/desktop/exit-token", {cache:"no-store", credentials:"same-origin"});
    if (!tokenResponse.ok) throw new Error("无法验证退出操作，请返回重试。");
    const {token} = await tokenResponse.json();
    const response = await fetch("/api/desktop/shutdown", {method:"POST", credentials:"same-origin", headers:{"X-GradeAnalysis-Exit-Token":token}});
    if (!response.ok) throw new Error("退出请求未成功，请返回重试。");
    overlay.querySelector("h1").textContent = "student-score-analysis已退出";
    overlay.querySelector("p").textContent = "现在可以安全关闭此页面。";
  } catch (error) {
    overlay.querySelector("h1").textContent = "尚未确认student-score-analysis退出";
    overlay.querySelector("p").textContent = error.message;
    retry.hidden = false;
  }
}
