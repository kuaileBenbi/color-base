const externalData = window.LITERATURE_TRACKER_DATA || {};
const seedPapers = Array.isArray(externalData.papers) ? externalData.papers : [];

const topicDescriptions = {
  "配方推荐": "从目标颜色、光谱、文本描述或历史配方反推色浆/颜料比例。",
  "汽车涂料测色": "多角度分光、WADE、flop、gloss、曲面测量和修补漆数据库。",
  "光谱恢复": "从 RGB/多光源/高光谱数据恢复反射率，降低同色异谱和照明影响。",
  "效果颜料识别": "金属片、珠光片、颗粒尺寸、空间指纹、图像/光谱联合识别。",
  "结构色/涂层反设计": "用物理约束和深度学习从目标光谱反推涂层或结构参数。",
  "生产过程": "喷涂质量、换色成本、缺陷预测、车间排程和过程数据。",
  "白皮书/报告": "仪器厂商、涂料公司、标准组织发布的公开技术资料。"
};

const statusRank = { "精读": 0, "待读": 1, "未读": 2, "已读": 3, "搁置": 4 };
const storageKey = "auto-coating-literature-tracker-v1";
const selectedKey = "auto-coating-literature-selected-v1";

let papers = loadPapers();
let selectedId = localStorage.getItem(selectedKey) || papers[0]?.id;

const els = {
  searchInput: document.querySelector("#searchInput"),
  topicFilter: document.querySelector("#topicFilter"),
  typeFilter: document.querySelector("#typeFilter"),
  statusFilter: document.querySelector("#statusFilter"),
  sortSelect: document.querySelector("#sortSelect"),
  totalCount: document.querySelector("#totalCount"),
  queueCount: document.querySelector("#queueCount"),
  latestYear: document.querySelector("#latestYear"),
  resultCount: document.querySelector("#resultCount"),
  activeSummary: document.querySelector("#activeSummary"),
  topicMap: document.querySelector("#topicMap"),
  searchLinks: document.querySelector("#searchLinks"),
  paperList: document.querySelector("#paperList"),
  detailView: document.querySelector("#detailView"),
  addForm: document.querySelector("#addForm"),
  exportBtn: document.querySelector("#exportBtn"),
  importInput: document.querySelector("#importInput"),
  resetBtn: document.querySelector("#resetBtn"),
  template: document.querySelector("#paperTemplate")
};

function loadPapers() {
  const saved = localStorage.getItem(storageKey);
  if (!saved) return cloneSeed();
  try {
    const parsed = JSON.parse(saved);
    return Array.isArray(parsed) ? mergeLocalWithSeed(parsed) : cloneSeed();
  } catch {
    return cloneSeed();
  }
}

function cloneSeed() {
  return JSON.parse(JSON.stringify(seedPapers));
}

function mergeLocalWithSeed(localPapers) {
  const localById = new Map(localPapers.map((paper) => [paper.id, paper]));
  const remoteIds = new Set(seedPapers.map((paper) => paper.id));
  const merged = seedPapers.map((remotePaper) => {
    const localPaper = localById.get(remotePaper.id);
    if (!localPaper) return { ...remotePaper };
    return {
      ...remotePaper,
      status: localPaper.status || remotePaper.status,
      notes: localPaper.notes || remotePaper.notes,
      relevance: localPaper.relevance || remotePaper.relevance,
      tags: localPaper.tags?.length ? localPaper.tags : remotePaper.tags,
    };
  });

  localPapers
    .filter((paper) => !remoteIds.has(paper.id))
    .forEach((paper) => merged.push(paper));
  return merged;
}

function savePapers() {
  localStorage.setItem(storageKey, JSON.stringify(papers, null, 2));
}

function uniqueValues(key) {
  return [...new Set(papers.map((paper) => paper[key]).filter(Boolean))].sort((a, b) =>
    String(a).localeCompare(String(b), "zh-CN")
  );
}

function renderOptions(select, values, label) {
  select.innerHTML = `<option value="">全部${label}</option>`;
  values.forEach((value) => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = value;
    select.append(option);
  });
}

function hydrateFilters() {
  renderOptions(els.topicFilter, uniqueValues("topic"), "主题");
  renderOptions(els.typeFilter, uniqueValues("type"), "类型");
  renderOptions(els.statusFilter, uniqueValues("status"), "状态");
}

function getFilteredPapers() {
  const term = els.searchInput.value.trim().toLowerCase();
  const topic = els.topicFilter.value;
  const type = els.typeFilter.value;
  const status = els.statusFilter.value;

  let result = papers.filter((paper) => {
    const haystack = [
      paper.title,
      paper.authors,
      paper.venue,
      paper.topic,
      paper.type,
      paper.notes,
      ...(paper.tags || [])
    ].join(" ").toLowerCase();
    return (
      (!term || haystack.includes(term)) &&
      (!topic || paper.topic === topic) &&
      (!type || paper.type === type) &&
      (!status || paper.status === status)
    );
  });

  const sort = els.sortSelect.value;
  result = [...result].sort((a, b) => {
    if (sort === "relevance-desc") return b.relevance - a.relevance || b.year - a.year;
    if (sort === "status") return (statusRank[a.status] ?? 9) - (statusRank[b.status] ?? 9);
    if (sort === "title") return a.title.localeCompare(b.title, "zh-CN");
    return (b.year || 0) - (a.year || 0);
  });

  return result;
}

function renderMetrics(filtered) {
  const years = papers.map((paper) => paper.year).filter(Boolean);
  const generatedAt = externalData.generatedAt ? new Date(externalData.generatedAt) : null;
  els.totalCount.textContent = papers.length;
  els.queueCount.textContent = papers.filter((paper) => ["待读", "精读"].includes(paper.status)).length;
  els.latestYear.textContent = years.length ? Math.max(...years) : "-";
  els.resultCount.textContent = `${filtered.length} 项`;
  els.activeSummary.textContent = els.topicFilter.value || (generatedAt ? `数据更新 ${generatedAt.toLocaleDateString("zh-CN")}` : "全部主题");
}

function renderTopics() {
  els.topicMap.innerHTML = "";
  Object.entries(topicDescriptions).forEach(([topic, desc]) => {
    const count = papers.filter((paper) => paper.topic === topic).length;
    const button = document.createElement("button");
    button.type = "button";
    button.className = `topic-button ${els.topicFilter.value === topic ? "active" : ""}`;
    button.innerHTML = `<strong>${topic} · ${count}</strong><span>${desc}</span>`;
    button.addEventListener("click", () => {
      els.topicFilter.value = els.topicFilter.value === topic ? "" : topic;
      render();
    });
    els.topicMap.append(button);
  });
}

function renderSearchLinks() {
  const queries = [
    ["arXiv", "https://arxiv.org/search/?query=%22color+matching%22+%22automotive+coatings%22+%22deep+learning%22&searchtype=all"],
    ["Google Scholar", "https://scholar.google.com/scholar?q=%22color+matching%22+%22automotive+coatings%22+%22deep+learning%22"],
    ["Semantic Scholar", "https://www.semanticscholar.org/search?q=%22color%20matching%22%20%22automotive%20coatings%22%20%22deep%20learning%22&sort=relevance"],
    ["Crossref", "https://search.crossref.org/?q=%22color+matching%22+%22automotive+coatings%22+%22deep+learning%22"],
    ["Google Web", "https://www.google.com/search?q=%22automotive+coatings%22+%22color+matching%22+%22white+paper%22"]
  ];
  els.searchLinks.innerHTML = "";
  queries.forEach(([name, url]) => {
    const link = document.createElement("a");
    link.className = "search-link";
    link.href = url;
    link.target = "_blank";
    link.rel = "noreferrer";
    link.innerHTML = `<span>${name}</span><span>打开</span>`;
    els.searchLinks.append(link);
  });
}

function renderPapers(filtered) {
  els.paperList.innerHTML = "";
  if (!filtered.length) {
    els.paperList.innerHTML = `<div class="detail-block">没有匹配结果。可以清空筛选，或在右侧新增条目。</div>`;
    return;
  }

  filtered.forEach((paper) => {
    const node = els.template.content.firstElementChild.cloneNode(true);
    node.querySelector(".year").textContent = paper.year || "年份待补";
    node.querySelector(".type").textContent = paper.type;
    node.querySelector(".relevance").textContent = `相关度 ${paper.relevance}/5`;
    node.querySelector("h3").textContent = paper.title;
    node.querySelector(".paper-meta").textContent = `${paper.authors || "作者待补"} · ${paper.venue || "来源待补"}`;
    node.querySelector(".paper-note").textContent = paper.notes;

    const tags = node.querySelector(".tag-row");
    tags.innerHTML = "";
    [paper.topic, ...(paper.tags || [])].forEach((tag) => {
      const item = document.createElement("span");
      item.textContent = tag;
      tags.append(item);
    });

    node.querySelector(".select-paper").addEventListener("click", () => {
      selectedId = paper.id;
      localStorage.setItem(selectedKey, selectedId);
      renderDetail();
    });

    const link = node.querySelector(".open-link");
    link.href = normalizeUrl(paper.url) || "#";
    link.textContent = paper.url ? "来源" : "无链接";
    if (!paper.url) link.removeAttribute("href");

    const statusSelect = node.querySelector(".status-select");
    statusSelect.value = paper.status;
    statusSelect.addEventListener("change", () => {
      paper.status = statusSelect.value;
      savePapers();
      hydrateFilters();
      render();
    });

    els.paperList.append(node);
  });
}

function renderDetail() {
  const paper = papers.find((item) => item.id === selectedId) || papers[0];
  if (!paper) {
    els.detailView.innerHTML = "暂无条目。";
    return;
  }
  selectedId = paper.id;
  localStorage.setItem(selectedKey, selectedId);
  els.detailView.innerHTML = `
    <h3>${escapeHtml(paper.title)}</h3>
    <div class="detail-block"><strong>定位</strong>${escapeHtml(paper.topic)} · ${escapeHtml(paper.type)} · 相关度 ${paper.relevance}/5</div>
    <div class="detail-block"><strong>作者/来源</strong>${escapeHtml(paper.authors || "作者待补")}<br>${escapeHtml(paper.venue || "来源待补")}</div>
    <div class="detail-block"><strong>学习备注</strong>${escapeHtml(paper.notes || "暂无备注")}</div>
    <div class="detail-block"><strong>关键词</strong>${escapeHtml((paper.tags || []).join(" · ") || "暂无关键词")}</div>
    <div class="detail-block"><strong>链接</strong>${paper.url ? `<a href="${normalizeUrl(paper.url)}" target="_blank" rel="noreferrer">${escapeHtml(paper.url)}</a>` : "暂无链接"}</div>
  `;
}

function normalizeUrl(value) {
  if (!value) return "";
  if (/^[a-z]:[\\/]/i.test(value)) return `file:///${value.replaceAll("\\", "/")}`;
  if (/^(https?|file|doi):/i.test(value)) return value;
  return "";
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function slugify(value) {
  return `${Date.now()}-${value.toLowerCase().replace(/[^a-z0-9\u4e00-\u9fa5]+/g, "-").replace(/^-|-$/g, "")}`;
}

function render() {
  const filtered = getFilteredPapers();
  renderMetrics(filtered);
  renderTopics();
  renderPapers(filtered);
  renderDetail();
}

els.searchInput.addEventListener("input", render);
els.topicFilter.addEventListener("change", render);
els.typeFilter.addEventListener("change", render);
els.statusFilter.addEventListener("change", render);
els.sortSelect.addEventListener("change", render);

els.addForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const data = new FormData(els.addForm);
  const title = String(data.get("title") || "").trim();
  if (!title) return;
  const paper = {
    id: slugify(title),
    title,
    authors: "待补",
    year: Number(data.get("year")) || 0,
    type: "待分类",
    topic: String(data.get("topic") || "配方推荐"),
    venue: "手动新增",
    url: String(data.get("url") || "").trim(),
    relevance: 3,
    status: "未读",
    tags: [],
    notes: String(data.get("notes") || "").trim()
  };
  papers.unshift(paper);
  selectedId = paper.id;
  savePapers();
  hydrateFilters();
  els.addForm.reset();
  render();
});

els.exportBtn.addEventListener("click", () => {
  const blob = new Blob([JSON.stringify(papers, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `auto-coating-literature-${new Date().toISOString().slice(0, 10)}.json`;
  link.click();
  URL.revokeObjectURL(url);
});

els.importInput.addEventListener("change", async (event) => {
  const file = event.target.files?.[0];
  if (!file) return;
  const text = await file.text();
  const imported = JSON.parse(text);
  if (!Array.isArray(imported)) throw new Error("JSON 必须是条目数组");
  papers = imported;
  selectedId = papers[0]?.id;
  savePapers();
  hydrateFilters();
  render();
  event.target.value = "";
});

els.resetBtn.addEventListener("click", () => {
  papers = cloneSeed();
  selectedId = papers[0]?.id;
  savePapers();
  hydrateFilters();
  render();
});

hydrateFilters();
renderSearchLinks();
render();
