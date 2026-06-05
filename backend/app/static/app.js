// 资源库后台前端交互（原生 JS，无构建步骤）

// ---- 概览：同步本地 data/ ----
(function () {
  const btn = document.getElementById("btn-sync-local");
  if (!btn) return;
  btn.addEventListener("click", async () => {
    if (!confirm("扫描 data/ 目录并入库？已存在的记录会跳过或补全。")) return;
    btn.disabled = true;
    btn.textContent = "同步中…";
    try {
      const resp = await fetch("/api/sync/local", { method: "POST" });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.detail || "同步失败");
      alert(
        "同步完成\n" +
          `MissAV：新增 ${data.missav?.created ?? 0}\n` +
          `Pornhub：新增 ${data.pornhub?.created ?? 0}`
      );
      location.reload();
    } catch (err) {
      alert("同步失败：" + err.message);
      btn.disabled = false;
      btn.textContent = "同步本地 data/ 到数据库";
    }
  });
})();

// ---- 资源库：点击预览大图/播放 ----
(function () {
  const box = document.getElementById("lightbox");
  const body = box?.querySelector(".lightbox-body");
  const grid = document.getElementById("res-grid") || document.getElementById("browse-grid");
  if (!box || !body || !grid) return;

  function close() {
    box.classList.add("hidden");
    box.setAttribute("aria-hidden", "true");
    body.innerHTML = "";
  }

  box.querySelector(".lightbox-close")?.addEventListener("click", close);
  box.addEventListener("click", (e) => {
    if (e.target === box) close();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") close();
  });

  function openPreview(el) {
      const url = el.dataset.url;
      const cover = el.dataset.cover;
      const isVideo = el.dataset.type === "video";
      if (!url && !cover) return;
      if (isVideo && url && !url.includes("view_video")) {
        body.innerHTML = `<video src="${url}" controls autoplay playsinline${cover ? ` poster="${cover}"` : ""}></video>`;
      } else if (cover || url) {
        body.innerHTML = `<img src="${cover || url}" alt="" referrerpolicy="no-referrer">`;
      } else {
        return;
      }
      box.classList.remove("hidden");
      box.setAttribute("aria-hidden", "false");
  }

  grid.querySelectorAll(".res-preview").forEach((el) => {
    el.addEventListener("click", () => openPreview(el));
    el.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        openPreview(el);
      }
    });
  });
})();

// ---- 下载进度条轮询 ----
(function () {
  const grid = document.getElementById("res-grid");
  if (!grid) return;

  function updateCard(card, item) {
    card.dataset.status = item.download_status;
    card.dataset.progress = String(item.progress);
    card.dataset.indeterminate = item.indeterminate ? "1" : "0";

    const track = card.querySelector(".res-progress-track");
    const fill = card.querySelector(".res-progress-fill");
    let indet = card.querySelector(".res-progress-indeterminate");
    const label = card.querySelector(".res-progress-label");
    const pct = card.querySelector(".res-progress-pct");

    if (track) {
      track.className = "res-progress-track status-dl-" + item.download_status;
    }
    if (label) {
      label.className = "status status-dl-" + item.download_status + " res-progress-label";
    }
    if (fill) fill.style.width = item.progress + "%";
    if (indet) indet.style.display = item.indeterminate ? "block" : "none";
    if (!indet && item.indeterminate && track) {
      const el = document.createElement("div");
      el.className = "res-progress-indeterminate";
      track.appendChild(el);
    }
    if (label) label.textContent = item.status_label;
    if (pct) pct.textContent = item.indeterminate ? "…" : item.progress + "%";
  }

  async function poll() {
    try {
      const resp = await fetch("/api/videos/download-status");
      const list = await resp.json();
      let hasDownloading = false;
      list.forEach((item) => {
        if (item.download_status === "downloading") hasDownloading = true;
        const card = grid.querySelector('[data-id="' + item.id + '"]');
        if (card) updateCard(card, item);
      });
      return hasDownloading;
    } catch (_) {
      return false;
    }
  }

  const shouldPoll = window.__POLL_DOWNLOADS__ || grid.querySelector('[data-status="downloading"]');
  if (!shouldPoll) return;

  const interval = setInterval(async () => {
    const active = await poll();
    if (!active && window.__POLL_DOWNLOADS__) {
      clearInterval(interval);
      setTimeout(() => location.reload(), 800);
    }
  }, 2000);
  poll();
})();

// ---- 资源库：去封面水印（单条 / 批量）----
(function () {
  const isTrash = document.getElementById("page-flags")?.dataset.trash === "1";
  const selectAll = document.getElementById("select-all");
  const rowChecks = () => [...document.querySelectorAll(".row-select")];
  const selectedCount = document.getElementById("selected-count");
  const batchStatus = document.getElementById("batch-status");
  const batchCategory = document.getElementById("batch-category");
  const batchDelete = document.getElementById("btn-batch-delete");
  const batchRestore = document.getElementById("btn-batch-restore");
  const batchExport = document.getElementById("btn-batch-export");

  function selectedIds() {
    return rowChecks().filter((c) => c.checked).map((c) => Number(c.value));
  }

  function updateSelectedLabel() {
    if (selectedCount) selectedCount.textContent = `已选 ${selectedIds().length}`;
  }

  if (selectAll) {
    selectAll.addEventListener("change", () => {
      rowChecks().forEach((c) => (c.checked = selectAll.checked));
      updateSelectedLabel();
    });
  }
  rowChecks().forEach((c) => c.addEventListener("change", updateSelectedLabel));
  updateSelectedLabel();

  if (batchStatus) {
    batchStatus.addEventListener("change", async () => {
      const status = batchStatus.value;
      if (!status) return;
      const ids = selectedIds();
      if (!ids.length) return alert("请先选择资源");
      const resp = await fetch("/api/videos/batch/update-status", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ids, download_status: status }),
      });
      const data = await resp.json();
      if (!resp.ok) return alert(data.detail || "批量更新失败");
      location.reload();
    });
  }

  if (batchCategory) {
    batchCategory.addEventListener("change", async () => {
      const cat = Number(batchCategory.value || 0);
      if (!cat) return;
      const ids = selectedIds();
      if (!ids.length) return alert("请先选择资源");
      const resp = await fetch("/api/videos/batch/update-categories", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ids, category_ids: [cat] }),
      });
      const data = await resp.json();
      if (!resp.ok) return alert(data.detail || "批量分类失败");
      location.reload();
    });
  }

  if (batchDelete) {
    batchDelete.addEventListener("click", async () => {
      const ids = selectedIds();
      if (!ids.length) return alert("请先选择资源");
      const msg = isTrash
        ? `确认彻底删除选中的 ${ids.length} 条资源？此操作不可恢复。`
        : `确认将选中的 ${ids.length} 条资源移到回收站？`;
      if (!confirm(msg)) return;
      const endpoint = isTrash ? "/api/videos/batch/purge" : "/api/videos/batch/delete";
      const resp = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ids }),
      });
      const data = await resp.json();
      if (!resp.ok) return alert(data.detail || "批量删除失败");
      location.reload();
    });
  }

  document.querySelectorAll(".btn-row-delete").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const id = Number(btn.dataset.id);
      if (!id) return;
      if (!confirm("确认删除这条资源到回收站？")) return;
      const resp = await fetch("/api/videos/batch/delete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ids: [id] }),
      });
      const data = await resp.json();
      if (!resp.ok) return alert(data.detail || "删除失败");
      location.reload();
    });
  });

  if (batchRestore) {
    batchRestore.addEventListener("click", async () => {
      const ids = selectedIds();
      if (!ids.length) return alert("请先选择资源");
      const resp = await fetch("/api/videos/batch/restore", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ids }),
      });
      const data = await resp.json();
      if (!resp.ok) return alert(data.detail || "批量恢复失败");
      location.reload();
    });
  }

  if (batchExport) {
    batchExport.addEventListener("click", async () => {
      const ids = selectedIds();
      if (!ids.length) return alert("请先选择资源");
      const resp = await fetch("/api/videos/batch/export", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ids }),
      });
      if (!resp.ok) return alert("导出失败");
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "videos_export.csv";
      a.click();
      URL.revokeObjectURL(url);
    });
  }

  const batchCoverBtn = document.getElementById("btn-batch-cover");
  const batchBtn = document.getElementById("btn-batch-watermark");
  const grid = document.getElementById("res-grid");
  const box = document.getElementById("lightbox");
  const body = box?.querySelector(".lightbox-body");

  if (batchCoverBtn) {
    batchCoverBtn.addEventListener("click", async () => {
      if (!confirm("为缺失封面的资源批量生成封面？")) return;
      batchCoverBtn.disabled = true;
      batchCoverBtn.textContent = "启动中…";
      try {
        const resp = await fetch("/api/videos/batch-generate-cover", { method: "POST" });
        const data = await resp.json();
        if (!resp.ok || data.ok === false) throw new Error(data.detail || "处理失败");

        const poll = async () => {
          const sResp = await fetch("/api/videos/batch-generate-cover/status");
          const sData = await sResp.json();
          const done = Number(sData.processed || 0);
          const failed = Number(sData.failed || 0);
          const total = Number(sData.total || 0);
          batchCoverBtn.textContent = `补封面 ${done + failed}/${total || "?"}...`;
          if (!sData.running) {
            alert(`补封面完成：成功 ${done}，失败 ${failed}`);
            location.reload();
          } else {
            setTimeout(poll, 1200);
          }
        };
        poll();
      } catch (err) {
        alert("批量补封面失败：" + err.message);
        batchCoverBtn.disabled = false;
        batchCoverBtn.textContent = "批量补封面图";
      }
    });
  }

  document.querySelectorAll(".btn-row-cover").forEach((btn) => {
    btn.addEventListener("click", async () => {
      btn.disabled = true;
      btn.textContent = "处理中…";
      try {
        const resp = await fetch(`/api/videos/${btn.dataset.id}/generate-cover`, { method: "POST" });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.detail || "处理失败");
        btn.textContent = "已完成";
        setTimeout(() => location.reload(), 300);
      } catch (err) {
        alert("补封面失败：" + err.message);
        btn.disabled = false;
        btn.textContent = "补封面";
      }
    });
  });

  async function runOne(id, btn) {
    if (btn) {
      btn.disabled = true;
      btn.textContent = "处理中…";
    }
    try {
      const resp = await fetch(`/api/videos/${id}/remove-watermark`, { method: "POST" });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.detail || "处理失败");
      if (btn) btn.textContent = "已完成";
      setTimeout(() => location.reload(), 300);
    } catch (err) {
      alert("去水印失败：" + err.message);
      if (btn) btn.textContent = "去水印";
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  if (batchBtn) {
    batchBtn.addEventListener("click", async () => {
      if (!confirm("批量处理所有未去水印封面？")) return;
      batchBtn.disabled = true;
      batchBtn.textContent = "启动中…";
      try {
        const resp = await fetch("/api/videos/batch-remove-watermark", { method: "POST" });
        const data = await resp.json();
        if (!resp.ok || data.ok === false) throw new Error(data.detail || "处理失败");

        const poll = async () => {
          const sResp = await fetch("/api/videos/batch-remove-watermark/status");
          const sData = await sResp.json();
          const done = Number(sData.processed || 0);
          const failed = Number(sData.failed || 0);
          const total = Number(sData.total || 0);
          batchBtn.textContent = `处理中 ${done + failed}/${total || "?"}...`;
          if (!sData.running) {
            alert(`批量完成：成功 ${done}，失败 ${failed}`);
            location.reload();
          } else {
            setTimeout(poll, 1200);
          }
        };
        poll();
      } catch (err) {
        alert("批量去水印失败：" + err.message);
        batchBtn.disabled = false;
        batchBtn.textContent = "批量去封面水印";
      }
    });
  }

  document.querySelectorAll(".btn-row-watermark").forEach((btn) => {
    btn.addEventListener("click", () => runOne(btn.dataset.id, btn));
  });

  document.querySelectorAll(".btn-view-clean").forEach((btn) => {
    btn.addEventListener("click", () => {
      if (!box || !body) return;
      const url = btn.dataset.url;
      if (!url) return;
      body.innerHTML = `<img src="${url}" alt="" referrerpolicy="no-referrer">`;
      box.classList.remove("hidden");
      box.setAttribute("aria-hidden", "false");
    });
  });
})();

// ---- 资源库：单条编辑 ----
(function () {
  const modal = document.getElementById("edit-modal");
  if (!modal) return;
  const idEl = document.getElementById("edit-id");
  const titleEl = document.getElementById("edit-title");
  const codeEl = document.getElementById("edit-code");
  const sourceEl = document.getElementById("edit-source");
  const durationEl = document.getElementById("edit-duration");
  const sourceUrlEl = document.getElementById("edit-source-url");
  const coverUrlEl = document.getElementById("edit-cover-url");
  const noteEl = document.getElementById("edit-note");
  const tagsEl = document.getElementById("edit-tags");
  const categoryEl = document.getElementById("edit-category");
  const saveBtn = document.getElementById("btn-edit-save");
  const cancelBtn = document.getElementById("btn-edit-cancel");

  const close = () => {
    modal.classList.add("hidden");
    modal.setAttribute("aria-hidden", "true");
  };
  cancelBtn?.addEventListener("click", close);
  modal.addEventListener("click", (e) => {
    if (e.target === modal) close();
  });

  document.querySelectorAll(".btn-edit").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const id = Number(btn.dataset.id);
      const resp = await fetch(`/api/videos/${id}`);
      const v = await resp.json();
      if (!resp.ok) return alert(v.detail || "加载失败");
      idEl.value = String(v.id);
      titleEl.value = v.title || "";
      codeEl.value = v.code || "";
      sourceEl.value = v.source || "missav";
      durationEl.value = v.duration || "";
      sourceUrlEl.value = v.source_url || "";
      coverUrlEl.value = v.cover_url || "";
      noteEl.value = (v.extra && v.extra.note) || "";
      tagsEl.value = (v.extra && Array.isArray(v.extra.tags)) ? v.extra.tags.join(", ") : "";
      categoryEl.value = "";
      modal.classList.remove("hidden");
      modal.setAttribute("aria-hidden", "false");
    });
  });

  saveBtn?.addEventListener("click", async () => {
    const id = Number(idEl.value || 0);
    if (!id) return;
    const payload = {
      title: titleEl.value,
      code: codeEl.value || null,
      source: sourceEl.value || null,
      duration: durationEl.value || null,
      source_url: sourceUrlEl.value || null,
      cover_url: coverUrlEl.value || null,
      note: noteEl.value || "",
      tags: tagsEl.value ? tagsEl.value.split(",").map((s) => s.trim()).filter(Boolean) : [],
      category_ids: categoryEl.value ? [Number(categoryEl.value)] : undefined,
    };
    const resp = await fetch(`/api/videos/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await resp.json();
    if (!resp.ok) return alert(data.detail || "保存失败");
    location.reload();
  });
})();

// ---- 资源库：新增资源 ----
(function () {
  const modal = document.getElementById("add-modal");
  const openBtn = document.getElementById("btn-open-add");
  const saveBtn = document.getElementById("btn-add-save");
  const cancelBtn = document.getElementById("btn-add-cancel");
  if (!modal || !openBtn || !saveBtn || !cancelBtn) return;

  const titleEl = document.getElementById("add-title");
  const codeEl = document.getElementById("add-code");
  const sourceEl = document.getElementById("add-source");
  const durationEl = document.getElementById("add-duration");
  const sourceUrlEl = document.getElementById("add-source-url");
  const coverUrlEl = document.getElementById("add-cover-url");
  const filePathEl = document.getElementById("add-file-path");

  const close = () => {
    modal.classList.add("hidden");
    modal.setAttribute("aria-hidden", "true");
  };
  const open = () => {
    modal.classList.remove("hidden");
    modal.setAttribute("aria-hidden", "false");
  };

  openBtn.addEventListener("click", open);
  cancelBtn.addEventListener("click", close);
  modal.addEventListener("click", (e) => { if (e.target === modal) close(); });

  saveBtn.addEventListener("click", async () => {
    const title = titleEl.value.trim();
    const source_url = sourceUrlEl.value.trim();
    if (!title || !source_url) return alert("标题和详情页链接为必填");

    const payload = {
      title,
      code: codeEl.value.trim() || null,
      source: sourceEl.value || "missav",
      source_url,
      duration: durationEl.value.trim() || null,
      cover_url: coverUrlEl.value.trim() || null,
      file_path: filePathEl.value.trim() || null,
    };

    saveBtn.disabled = true;
    saveBtn.textContent = "新增中…";
    try {
      const resp = await fetch("/api/videos", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.detail || "新增失败");
      location.reload();
    } catch (err) {
      alert("新增失败：" + err.message);
      saveBtn.disabled = false;
      saveBtn.textContent = "新增";
    }
  });
})();

// ---- 资源库：筛选方案（localStorage）----
(function () {
  const nameInput = document.getElementById("preset-name");
  const saveBtn = document.getElementById("btn-save-preset");
  const select = document.getElementById("preset-select");
  const applyBtn = document.getElementById("btn-apply-preset");
  const delBtn = document.getElementById("btn-del-preset");
  if (!nameInput || !saveBtn || !select || !applyBtn || !delBtn) return;

  const KEY = "ziyuanku_resource_presets_v1";
  const read = () => {
    try { return JSON.parse(localStorage.getItem(KEY) || "[]"); } catch (_) { return []; }
  };
  const write = (arr) => localStorage.setItem(KEY, JSON.stringify(arr));

  function currentQuery() {
    const u = new URL(location.href);
    return {
      source: u.searchParams.get("source") || "",
      download_status: u.searchParams.get("download_status") || "",
      keyword: u.searchParams.get("keyword") || "",
      trash: u.searchParams.get("trash") || "",
    };
  }

  function render() {
    const items = read();
    select.innerHTML = '<option value="">选择方案</option>' +
      items.map((p, i) => `<option value="${i}">${p.name}</option>`).join("");
  }

  saveBtn.addEventListener("click", () => {
    const name = nameInput.value.trim();
    if (!name) return alert("请输入方案名");
    const items = read().filter((x) => x.name !== name);
    items.unshift({ name, query: currentQuery() });
    write(items.slice(0, 20));
    render();
    alert("已保存筛选方案");
  });

  applyBtn.addEventListener("click", () => {
    const idx = Number(select.value || -1);
    const items = read();
    if (idx < 0 || !items[idx]) return;
    const q = items[idx].query || {};
    const u = new URL(location.origin + "/resources");
    Object.entries(q).forEach(([k, v]) => { if (v) u.searchParams.set(k, String(v)); });
    location.href = u.toString();
  });

  delBtn.addEventListener("click", () => {
    const idx = Number(select.value || -1);
    const items = read();
    if (idx < 0 || !items[idx]) return;
    items.splice(idx, 1);
    write(items);
    render();
  });

  render();
})();

// ---- 分类编辑页：分类增删改 ----
(function () {
  async function parseJson(resp) {
    return resp.json().catch(() => ({}));
  }

  const syncBtn = document.getElementById("btn-sync-categories");
  if (syncBtn) {
    syncBtn.addEventListener("click", async () => {
      syncBtn.disabled = true;
      syncBtn.textContent = "同步中…";
      try {
        const resp = await fetch("/api/video-categories/sync", { method: "POST" });
        const data = await parseJson(resp);
        if (!resp.ok) throw new Error(data.detail || "同步失败");
        alert(`分类已同步，共 ${data.total ?? 0} 个`);
        location.reload();
      } catch (err) {
        alert("同步失败：" + err.message);
        syncBtn.disabled = false;
        syncBtn.textContent = "同步预设分类";
      }
    });
  }

  const addRootForm = document.getElementById("add-root-form");
  if (addRootForm) {
    addRootForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const fd = new FormData(addRootForm);
      const name = String(fd.get("name") || "").trim();
      if (!name) return;
      const resp = await fetch("/api/video-categories", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name }),
      });
      const data = await parseJson(resp);
      if (resp.ok) location.reload();
      else alert("新增一级分类失败：" + (data.detail || ""));
    });
  }

  const addSubForm = document.getElementById("add-sub-form");
  if (addSubForm) {
    addSubForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const fd = new FormData(addSubForm);
      const parentId = Number(fd.get("parent_id"));
      const name = String(fd.get("name") || "").trim();
      if (!parentId || !name) return;
      const resp = await fetch("/api/video-categories", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, parent_id: parentId }),
      });
      const data = await parseJson(resp);
      if (resp.ok) location.reload();
      else alert("新增子分类失败：" + (data.detail || ""));
    });
  }

  document.querySelectorAll(".cat-edit-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const oldName = btn.dataset.name || "";
      const nextName = (prompt("请输入新分类名称：", oldName) || "").trim();
      if (!nextName || nextName === oldName) return;
      const resp = await fetch(`/api/video-categories/${btn.dataset.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: nextName }),
      });
      const data = await parseJson(resp);
      if (resp.ok) location.reload();
      else alert("改名失败：" + (data.detail || ""));
    });
  });

  document.querySelectorAll(".cat-delete-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const name = btn.dataset.name || "";
      if (!confirm(`确认删除分类「${name}」？`)) return;
      const resp = await fetch(`/api/video-categories/${btn.dataset.id}`, { method: "DELETE" });
      const data = await parseJson(resp);
      if (resp.ok) location.reload();
      else alert("删除失败：" + (data.detail || ""));
    });
  });
})();

// ---- 分类浏览：视频绑定 / 移出 ----
(function () {
  async function parseJson(resp) {
    return resp.json().catch(() => ({}));
  }

  document.querySelectorAll(".unbind-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      if (!confirm("从当前分类移出该视频？")) return;
      const resp = await fetch(`/api/video-categories/videos/${btn.dataset.id}/unbind`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ category_id: Number(btn.dataset.cat) }),
      });
      if (resp.ok) location.reload();
      else {
        const data = await parseJson(resp);
        alert("移出失败：" + (data.detail || ""));
      }
    });
  });

  document.querySelectorAll(".bind-select").forEach((sel) => {
    sel.addEventListener("change", async () => {
      const catId = Number(sel.value);
      if (!catId) return;
      const resp = await fetch(`/api/video-categories/videos/${sel.dataset.id}/bind`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ category_id: catId }),
      });
      if (resp.ok) location.reload();
      else {
        const data = await parseJson(resp);
        alert("绑定失败：" + (data.detail || ""));
        sel.value = "";
      }
    });
  });

  const bindCatId = Number(window.__BIND_CATEGORY_ID__ || 0);
  const pickList = document.getElementById("uncat-pick-list");
  const bindSelectedBtn = document.getElementById("btn-bind-selected");
  if (!bindCatId || !pickList) return;

  async function loadUncategorized() {
    try {
      const resp = await fetch("/api/videos?uncategorized=true&limit=200");
      const videos = await resp.json();
      if (!videos.length) {
        pickList.textContent = "暂无未分类视频";
        return;
      }
      pickList.innerHTML = videos
        .map(
          (v) =>
            `<label><input type="checkbox" value="${v.id}"> #${v.id} ${escapeHtml(v.title || "")}</label>`
        )
        .join("");
      pickList.querySelectorAll("input").forEach((cb) => {
        cb.addEventListener("change", () => {
          const any = pickList.querySelector("input:checked");
          if (bindSelectedBtn) bindSelectedBtn.disabled = !any;
        });
      });
    } catch (_) {
      pickList.textContent = "加载失败";
    }
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  if (bindSelectedBtn) {
    bindSelectedBtn.addEventListener("click", async () => {
      const ids = [...pickList.querySelectorAll("input:checked")].map((cb) => Number(cb.value));
      if (!ids.length) return;
      bindSelectedBtn.disabled = true;
      bindSelectedBtn.textContent = "绑定中…";
      let ok = 0;
      for (const id of ids) {
        const resp = await fetch(`/api/video-categories/videos/${id}/bind`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ category_id: bindCatId }),
        });
        if (resp.ok) ok += 1;
      }
      alert(`已绑定 ${ok} 条`);
      location.reload();
    });
  }

  loadUncategorized();
})();
