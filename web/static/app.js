/* ═══════════════════════════════════════════
   收藏夹管理工具 Web 版 — 前端逻辑 (原生 JS + SSE)
   ═══════════════════════════════════════════ */

"use strict";

// ─────────── 全局状态 ───────────
const State = {
  bookmarks: [],
  distribution: {},
  stats: {},
  filter: "all",
  running: false,
  sse: null,
};

// 阶段芯片顺序
const STAGES = ["parse", "probe", "classify", "fetch", "summary", "ai", "done"];
const STAGE_LABELS = {
  parse: "解析", probe: "体检", classify: "分类",
  fetch: "抓取", summary: "摘要", ai: "AI", done: "完成",
};

// ─────────── DOM 快捷 ───────────
const $ = (id) => document.getElementById(id);

// ─────────── 工具 ───────────
async function api(path, options = {}) {
  const resp = await fetch(path, options);
  if (!resp.ok) {
    let msg = `HTTP ${resp.status}`;
    try { msg = (await resp.json()).detail || msg; } catch (_) {}
    throw new Error(msg);
  }
  return resp.json();
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function fmtStatus(bm) {
  const map = { ok: ["正常", "ok"], dead: ["失效", "dead"], local: ["本地", "local"] };
  const [label, cls] = map[bm.status] || ["待定", "pending"];
  return `<span class="tag tag-status-${cls}">${label}</span>`;
}

// ─────────── 顶部导航 ───────────
$("navSettingsBtn").addEventListener("click", () => openSettings());
$("navHelpBtn").addEventListener("click", () => {
  $("helpModal").hidden = false;
});
$("helpClose").addEventListener("click", () => { $("helpModal").hidden = true; });
$("helpModal").addEventListener("click", (e) => {
  if (e.target === $("helpModal")) $("helpModal").hidden = true;
});
$("settingsClose").addEventListener("click", () => { $("settingsModal").hidden = true; });
$("settingsModal").addEventListener("click", (e) => {
  if (e.target === $("settingsModal")) $("settingsModal").hidden = true;
});

// ─────────── ① 上传 ───────────
const dropzone = $("dropzone");
const fileInput = $("fileInput");

dropzone.addEventListener("click", () => fileInput.click());
dropzone.addEventListener("dragover", (e) => {
  e.preventDefault();
  dropzone.classList.add("dragover");
});
dropzone.addEventListener("dragleave", () => dropzone.classList.remove("dragover"));
dropzone.addEventListener("drop", (e) => {
  e.preventDefault();
  dropzone.classList.remove("dragover");
  const file = e.dataTransfer.files[0];
  if (file) uploadFile(file);
});
fileInput.addEventListener("change", () => {
  if (fileInput.files[0]) uploadFile(fileInput.files[0]);
  fileInput.value = "";
});

async function uploadFile(file) {
  if (State.running) {
    alert("流水线正在运行中，请等待完成");
    return;
  }
  const fd = new FormData();
  fd.append("file", file);

  const statusEl = $("uploadStatus");
  statusEl.hidden = false;
  statusEl.textContent = `⏳ 正在解析 ${file.name}...`;
  statusEl.className = "upload-status";

  try {
    const res = await api("/api/upload", { method: "POST", body: fd });
    State.bookmarks = res.bookmarks;
    State.stats = res.stats;
    updateDistribution();
    statusEl.textContent = `✅ 解析完成: ${res.count} 条书签（${res.filename}）`;
    statusEl.className = "upload-status";

    // 显示结果区（未处理，仅预览）
    $("resultCard").hidden = false;
    renderAll();
    $("exportCard").hidden = true;

    // 一键流程：上传后自动开始处理（体检 → 抓取 → AI 分类），进度实时推送
    await startProcess();
  } catch (err) {
    statusEl.textContent = `❌ ${err.message}`;
    statusEl.className = "upload-status";
    statusEl.style.background = "#FEE2E2";
    statusEl.style.borderColor = "#F87171";
    statusEl.style.color = "#B91C1C";
  }
}

// ─────────── ② 处理 (SSE) ───────────
async function startProcess() {
  if (State.running) return;
  if (!State.bookmarks.length) {
    alert("请先上传书签文件");
    return;
  }

  $("progressCard").hidden = false;
  $("logBox").innerHTML = "";
  $("progressBar").style.width = "0%";
  $("progressText").textContent = "0%";
  $("progressDetail").textContent = "正在启动...";
  renderStages("parse", 0);
  State.running = true;
  $("cancelBtn").hidden = false;

  // 连接 SSE
  if (State.sse) State.sse.close();
  State.sse = new EventSource("/api/events");

  State.sse.addEventListener("snapshot", (e) => {
    const snap = JSON.parse(e.data);
    if (snap.bookmarks) {
      State.bookmarks = snap.bookmarks;
      State.distribution = snap.distribution;
      State.stats = snap.stats;
      renderAll();
    }
  });

  State.sse.onmessage = (e) => {
    try {
      handleEvent(JSON.parse(e.data));
    } catch (_) {}
  };
  State.sse.onerror = () => {
    // 心跳丢失/重连——SSE 会自动重连，无需处理
  };

  try {
    await api("/api/process", { method: "POST" });
  } catch (err) {
    addLog("error", `❌ ${err.message}`);
    State.running = false;
    $("cancelBtn").hidden = true;
  }
}

function handleEvent(ev) {
  switch (ev.type) {
    case "stage":
      renderStages(ev.stage, ev.index);
      break;
    case "progress":
      updateProgress(ev.percent, ev.detail || ev.stage_label);
      break;
    case "log":
      addLog(ev.level === "SUCCESS" ? "success" : ev.level === "WARN" ? "warn" : ev.level === "ERROR" ? "error" : "info", ev.message);
      break;
    case "bookmarks_updated":
      refreshResults();
      break;
    case "item":
      updateProgress(ev.stage === "fetch" ? pctFor(ev.stage, ev.current, ev.total) : pctFor(ev.stage, ev.current, ev.total),
        `${STAGE_LABELS[ev.stage] || ev.stage}: ${ev.current}/${ev.total}`);
      break;
    case "ai_estimate":
      addLog("info", `🤖 待 AI 分类 ${ev.count} 条，预估 ¥${ev.estimated_cost_yuan.toFixed(4)} / 上限 ¥${ev.max_cost_yuan.toFixed(2)}`);
      break;
    case "done":
      refreshResults().then(() => {
        updateProgress(100, "全部完成");
        State.running = false;
        $("cancelBtn").hidden = true;
        if (State.sse) State.sse.close();
      });
      break;
    case "cancelled":
      State.running = false;
      $("cancelBtn").hidden = true;
      if (State.sse) State.sse.close();
      break;
    case "error":
      addLog("error", `❌ ${ev.message}`);
      updateProgress(0, "处理失败");
      State.running = false;
      $("cancelBtn").hidden = true;
      if (State.sse) State.sse.close();
      break;
  }
}

// ─────────── 取消处理 ───────────
$("cancelBtn").addEventListener("click", async () => {
  try {
    await api("/api/cancel", { method: "POST" });
    addLog("warn", "⏹ 已请求取消，正在停止...");
  } catch (err) {
    addLog("error", `❌ 取消失败: ${err.message}`);
  }
});

function pctFor(stage, current, total) {
  const ranges = { fetch: [30, 70], ai: [72, 95] };
  const [lo, hi] = ranges[stage] || [0, 100];
  return Math.min(Math.round(lo + (current / total) * (hi - lo)), hi);
}

function updateProgress(pct, detail) {
  $("progressBar").style.width = `${pct}%`;
  $("progressText").textContent = `${pct}%`;
  if (detail) $("progressDetail").textContent = detail;
}

function addLog(level, msg) {
  const box = $("logBox");
  const div = document.createElement("div");
  div.className = `log-line ${level}`;
  div.textContent = msg;
  box.appendChild(div);
  box.scrollTop = box.scrollHeight;
}

function renderStages(activeStage, index) {
  const list = $("stageList");
  list.innerHTML = "";
  STAGES.forEach((s, i) => {
    const chip = document.createElement("span");
    chip.className = "stage-chip";
    if (s === activeStage && s !== "done") chip.classList.add("active");
    else if (s === "done" || i < index) chip.classList.add("done");
    chip.textContent = STAGE_LABELS[s];
    list.appendChild(chip);
  });
}

// ─────────── ③ 结果渲染 ───────────
function updateDistribution() {
  const dist = {};
  State.bookmarks.forEach((b) => {
    if (b.user_deleted) return;
    const l1 = b.category_l1 || "📁 其他";
    const l2 = b.category_l2 || "未分类";
    dist[l1] = dist[l1] || {};
    dist[l1][l2] = (dist[l1][l2] || 0) + 1;
  });
  State.distribution = dist;
}

function renderStats() {
  const s = State.stats || {};
  const row = $("statRow");
  const total = State.bookmarks.length;
  const classified = State.bookmarks.filter((b) => !b.user_deleted && b.category_l1 && !["其他", "📁 其他"].includes(b.category_l1)).length;
  const dead = State.bookmarks.filter((b) => !b.user_deleted && b.status === "dead").length;
  const local = State.bookmarks.filter((b) => !b.user_deleted && b.status === "local").length;
  row.innerHTML = [
    `<span class="stat-item">总数 <b>${total}</b></span>`,
    `<span class="stat-item">已分类 <b>${classified}</b></span>`,
    `<span class="stat-item">待分类 <b>${total - classified - dead - local}</b></span>`,
    `<span class="stat-item">本地 <b>${local}</b></span>`,
    `<span class="stat-item">失效 <b>${dead}</b></span>`,
  ].join("");
}

function renderDist() {
  const tree = $("distTree");
  tree.innerHTML = "";
  const entries = Object.entries(State.distribution).sort((a, b) =>
    sum(b[1]) - sum(a[1]));
  const maxCount = entries.length ? Math.max(...entries.map(([, v]) => sum(v))) : 1;

  entries.forEach(([l1, l2s]) => {
    const l1Total = sum(l2s);
    const l1Div = document.createElement("div");
    l1Div.className = "dist-l1";
    l1Div.innerHTML = `📂 ${esc(l1)} <span class="cnt">(${l1Total})</span>`;
    l1Div.addEventListener("click", () => { State.filter = "all"; $("filterSelect").value = "all"; renderTable(); });
    tree.appendChild(l1Div);

    Object.entries(l2s).sort((a, b) => b[1] - a[1]).forEach(([l2, count]) => {
      const l2Div = document.createElement("div");
      l2Div.className = "dist-l2";
      const pct = Math.round((count / maxCount) * 60);
      l2Div.innerHTML = `${esc(l2)} <span class="cnt">${count}</span><span class="bar" style="width:${pct}px"></span>`;
      l2Div.addEventListener("click", () => filterByCategory(l1, l2));
      tree.appendChild(l2Div);
    });
  });
}

function sum(v) { return Object.values(v).reduce((a, b) => a + b, 0); }

function filterByCategory(l1, l2) {
  // 简易分类过滤：直接筛选表格
  State.filter = "all";
  $("filterSelect").value = "all";
  renderTable(l1, l2);
}

function filteredBookmarks(l1, l2) {
  return State.bookmarks.filter((b) => {
    if (b.user_deleted) return false;
    if (l1 && b.category_l1 !== l1) return false;
    if (l2 && b.category_l2 !== l2) return false;
    switch (State.filter) {
      case "dead": return b.status === "dead";
      case "local": return b.status === "local";
      case "unclassified": return !b.category_l1 || ["其他", "📁 其他"].includes(b.category_l1);
      default: return true;
    }
  });
}

function renderTable(l1, l2) {
  const rows = filteredBookmarks(l1, l2);
  const tbody = $("bookmarkTbody");
  tbody.innerHTML = "";
  $("tableCount").textContent = `共 ${rows.length} 条`;

  if (!rows.length) {
    tbody.innerHTML = `<tr><td colspan="7" style="text-align:center;color:#94A3B8;padding:24px">暂无书签 — 请先上传文件</td></tr>`;
    return;
  }

  const active = State.bookmarks.filter((b) => !b.user_deleted);
  rows.forEach((b, i) => {
    const idx = active.indexOf(b);
    const tr = document.createElement("tr");

    const l1Class = ["其他", "📁 其他"].includes(b.category_l1) ? "tag-l1" : "tag-l1";
    const unclass = !b.category_l1 || ["其他", "📁 其他"].includes(b.category_l1);
    const tagHtml = (b.tags && b.tags.length)
      ? `<div class="cell-tags">${b.tags.map(t => `<span class="tag tag-tag">${esc(t)}</span>`).join("")}</div>`
      : "";

    tr.innerHTML = `
      <td class="muted">${i + 1}</td>
      <td>
        <div class="cell-title" title="${esc(b.url)}">${esc(b.title) || esc(b.url)}</div>
        <div class="cell-url">${esc(b.url)}</div>
        ${tagHtml}
      </td>
      <td class="cell-domain">${esc(b.domain)}</td>
      <td>${unclass
        ? `<span class="tag tag-l1">待分类</span>`
        : `<span class="tag tag-l1">${esc(b.category_l1)}</span>`}</td>
      <td><span class="tag tag-l2">${esc(b.category_l2) || "未分类"}</span></td>
      <td>${fmtStatus(b)}</td>
      <td>
        <button class="btn btn-edit" data-idx="${idx}" title="修改分类">✏️</button>
        <button class="btn btn-del" data-idx="${idx}" title="删除">🗑️</button>
      </td>
    `;
    tbody.appendChild(tr);
  });

  // 操作绑定（事件委托）
  tbody.querySelectorAll(".btn-edit").forEach((btn) => {
    btn.addEventListener("click", () => editClassification(Number(btn.dataset.idx)));
  });
  tbody.querySelectorAll(".btn-del").forEach((btn) => {
    btn.addEventListener("click", () => deleteOne(Number(btn.dataset.idx)));
  });
}

function renderAll() {
  renderStats();
  renderDist();
  renderTable();
}

async function refreshResults() {
  try {
    const res = await api("/api/bookmarks?filter=all");
    State.bookmarks = res.bookmarks;
    updateDistribution();
    renderAll();
  } catch (_) {}
}

// ─────────── 审核操作 ───────────
async function editClassification(idx) {
  const bm = State.bookmarks.filter((b) => !b.user_deleted)[idx];
  if (!bm) return;

  const l1 = prompt(`修改一级分类（当前: ${bm.category_l1 || "待分类"}）:`, bm.category_l1 || "");
  if (l1 === null) return;
  const l2 = prompt(`修改二级分类（当前: ${bm.category_l2 || "未分类"}）:`, bm.category_l2 || "");
  if (l2 === null) return;

  try {
    await api(`/api/bookmarks/${idx}/classify`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ l1: l1.trim(), l2: l2.trim() }),
    });
    await refreshResults();
  } catch (err) {
    alert(`修改失败: ${err.message}`);
  }
}

async function deleteOne(idx) {
  if (!confirm("确定删除这条书签？")) return;
  try {
    await api(`/api/bookmarks/${idx}/delete`, { method: "POST" });
    await refreshResults();
  } catch (err) {
    alert(`删除失败: ${err.message}`);
  }
}

$("deleteDeadBtn").addEventListener("click", async () => {
  const deadCount = State.bookmarks.filter((b) => !b.user_deleted && b.status === "dead").length;
  if (!deadCount) { alert("没有失效链接"); return; }
  if (!confirm(`确定删除全部 ${deadCount} 条失效链接？`)) return;
  const res = await api("/api/bookmarks/delete-dead", { method: "POST" });
  await refreshResults();
  alert(`已删除 ${res.deleted} 条失效链接`);
});

$("remapBtn").addEventListener("click", async () => {
  if (State.running) { alert("处理中，请等待完成"); return; }
  if (!State.bookmarks.length) { alert("请先上传书签文件"); return; }
  if (!confirm("将所有一级分类收敛到固定 8 类（关键词映射，未命中归「其他」），确定？")) return;
  const res = await api("/api/remap", { method: "POST" });
  await refreshResults();
  alert(`已收敛 ${res.old_categories_merged} 个一级分类到固定 8 类`);
});

$("mergeBtn").addEventListener("click", async () => {
  if (State.running) { alert("处理中，请等待完成"); return; }
  if (!State.bookmarks.length) { alert("请先上传书签文件"); return; }
  if (!confirm("将每个大类下书签数 ≤ 2 的小分类合并到「其他」，确定？")) return;
  const res = await api("/api/merge", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ min_count: 2 }),
  });
  await refreshResults();
  alert(`已合并 ${res.merged_l2} 个小分类，移动 ${res.bookmarks_moved} 条书签到「其他」`);
});

$("filterSelect").addEventListener("change", () => {
  State.filter = $("filterSelect").value;
  renderTable();
});

// ─────────── ④ 导出 ───────────
$("exportBtn").addEventListener("click", async () => {
  if (State.running) { alert("处理中，请等待完成"); return; }
  if (!State.bookmarks.length) { alert("请先上传书签文件"); return; }

  $("exportBtn").disabled = true;
  $("exportBtn").textContent = "⏳ 生成中...";
  try {
    const res = await api("/api/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
    const s = res.stats;
    $("exportStats").textContent =
      `生成 ${s.kept} 条书签，${s.folders_created} 个文件夹，` +
      (s.excluded_dead ? `排除 ${s.excluded_dead} 条失效，` : "") +
      (s.excluded_local ? `排除 ${s.excluded_local} 条本地，` : "") +
      `共 ${res.validation.stats.bookmarks} 条有效条目`;
    $("downloadBtn").href = res.path;
    $("exportCard").hidden = false;
    $("exportCard").scrollIntoView({ behavior: "smooth" });
  } catch (err) {
    alert(`导出失败: ${err.message}`);
  } finally {
    $("exportBtn").disabled = false;
    $("exportBtn").textContent = "⬇️ 导出标准 HTML";
  }
});

$("reprocessBtn").addEventListener("click", () => {
  $("exportCard").hidden = true;
  $("resultCard").scrollIntoView({ behavior: "smooth" });
  startProcess();
});

// ─────────── 设置 ───────────
async function openSettings() {
  $("settingsModal").hidden = false;
  $("proxyTestResult").textContent = "";
  try {
    const s = await api("/api/settings");
    $("proxyEnabled").checked = s.proxy.enabled;
    $("proxyHost").value = s.proxy.host;
    $("proxyPort").value = s.proxy.port;
    $("proxyUsername").value = s.proxy.username;
    $("proxyForAi").checked = s.proxy.use_for_ai;
    $("proxyDetail").style.opacity = s.proxy.enabled ? "1" : "0.4";
    $("aiKey").value = "";
    $("aiKeyTail").textContent = s.ai.configured ? `（已配置 ···${s.ai.key_tail}）` : "（未配置）";
    $("aiBaseUrl").value = s.ai.base_url;
    $("aiModel").value = s.ai.model;
    $("aiBudget").value = s.ai.max_cost_yuan;
  } catch (err) {
    alert(`读取设置失败: ${err.message}`);
  }
}

$("proxyEnabled").addEventListener("change", () => {
  $("proxyDetail").style.opacity = $("proxyEnabled").checked ? "1" : "0.4";
});

$("settingsSaveBtn").addEventListener("click", async () => {
  try {
    await api("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        proxy: {
          enabled: $("proxyEnabled").checked,
          custom_enabled: $("proxyEnabled").checked,
          host: $("proxyHost").value.trim(),
          port: Number($("proxyPort").value) || 0,
          username: $("proxyUsername").value.trim(),
          use_for_ai: $("proxyForAi").checked,
        },
        ai: {
          api_key: $("aiKey").value.trim(),
          base_url: $("aiBaseUrl").value.trim(),
          model: $("aiModel").value.trim(),
          max_cost_yuan: Number($("aiBudget").value) || 5.0,
        },
      }),
    });
    $("settingsModal").hidden = true;
    alert("设置已保存 ✅");
  } catch (err) {
    alert(`保存失败: ${err.message}`);
  }
});

$("proxyTestBtn").addEventListener("click", async () => {
  const el = $("proxyTestResult");
  el.textContent = "⏳ 测试中...";
  el.className = "test-result";
  try {
    const r = await api("/api/settings/proxy-test", { method: "POST" });
    if (r.success) {
      el.textContent = `✅ 连接成功 (${r.ip}, ${r.latency_ms}ms)`;
      el.className = "test-result ok";
    } else {
      el.textContent = `❌ ${r.error}`;
      el.className = "test-result err";
    }
  } catch (err) {
    el.textContent = `❌ ${err.message}`;
    el.className = "test-result err";
  }
});

$("aiTestBtn").addEventListener("click", async () => {
  try {
    const r = await api("/api/settings/ai-test", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ api_key: $("aiKey").value.trim() }),
    });
    alert(r.ok ? `✅ AI 连接成功: ${r.message}` : `❌ ${r.message}`);
  } catch (err) {
    alert(`测试失败: ${err.message}`);
  }
});

// ─────────── 初始化 ───────────
(async function init() {
  // 页面加载时连接 SSE 以接收快照（若有未完成任务）
  try {
    const res = await api("/api/bookmarks?filter=all");
    State.bookmarks = res.bookmarks;
    if (State.bookmarks.length) {
      updateDistribution();
      $("resultCard").hidden = false;
      renderAll();
    }
  } catch (_) {}
})();
