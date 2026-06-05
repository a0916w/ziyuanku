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
          `Pornhub：新增 ${data.pornhub?.created ?? 0}\n` +
          `脚本：登记 ${(data.scripts?.created ?? 0) + (data.scripts?.updated ?? 0)} 个`
      );
      location.reload();
    } catch (err) {
      alert("同步失败：" + err.message);
      btn.disabled = false;
      btn.textContent = "同步本地 data/ 到数据库";
    }
  });
})();


// ---- 脚本页：同步 / 登记 / 编辑 / 运行 ----
(function () {
  const syncBtn = document.getElementById("btn-sync-scripts");
  if (syncBtn) {
    syncBtn.addEventListener("click", async () => {
      syncBtn.disabled = true;
      syncBtn.textContent = "同步中…";
      try {
        const resp = await fetch("/api/scripts/sync", { method: "POST" });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.detail || "同步失败");
        alert(`已同步内置脚本\n新增 ${data.created}，更新 ${data.updated}，共 ${data.total} 个`);
        location.reload();
      } catch (err) {
        alert("同步失败：" + err.message);
        syncBtn.disabled = false;
        syncBtn.textContent = "同步内置脚本";
      }
    });
  }

  const form = document.getElementById("script-form");
  const formBox = document.getElementById("script-form-box");
  const formSummary = document.getElementById("form-summary");
  const formSubmit = document.getElementById("form-submit");
  const formCancel = document.getElementById("form-cancel");

  function resetForm() {
    if (!form) return;
    form.reset();
    form.id.value = "";
    form.enabled.checked = true;
    formSummary.textContent = "+ 登记新脚本";
    formSubmit.textContent = "保存";
    formCancel.classList.add("hidden");
  }

  if (formCancel) formCancel.addEventListener("click", resetForm);

  document.querySelectorAll(".edit-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      if (!form) return;
      try {
        const resp = await fetch(`/api/scripts/${btn.dataset.id}`);
        const sc = await resp.json();
        if (!resp.ok) throw new Error(sc.detail || "加载失败");
        formBox.open = true;
        form.id.value = sc.id;
        form.name.value = sc.name || "";
        form.command.value = sc.command || "";
        form.description.value = sc.description || "";
        form.enabled.checked = !!sc.enabled;
        formSummary.textContent = "编辑脚本";
        formSubmit.textContent = "更新";
        formCancel.classList.remove("hidden");
        form.name.focus();
      } catch (err) {
        alert("无法加载脚本：" + err.message);
      }
    });
  });

  if (form) {
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const fd = new FormData(form);
      const body = {
        name: fd.get("name"),
        command: fd.get("command"),
        description: fd.get("description") || null,
        enabled: fd.get("enabled") === "on",
      };
      const editId = fd.get("id");
      const url = editId ? `/api/scripts/${editId}` : "/api/scripts";
      const method = editId ? "PATCH" : "POST";
      const resp = await fetch(url, {
        method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await resp.json().catch(() => ({}));
      if (resp.ok) location.reload();
      else alert("保存失败：" + (data.detail || resp.status));
    });
  }

  document.querySelectorAll(".toggle-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const enabled = btn.dataset.enabled !== "1";
      const resp = await fetch(`/api/scripts/${btn.dataset.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled }),
      });
      if (resp.ok) location.reload();
      else {
        const data = await resp.json().catch(() => ({}));
        alert("操作失败：" + (data.detail || ""));
      }
    });
  });

  document.querySelectorAll(".delete-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      if (!confirm("确定删除该脚本？运行记录也会一并删除。")) return;
      const resp = await fetch(`/api/scripts/${btn.dataset.id}`, { method: "DELETE" });
      if (resp.ok) location.reload();
      else {
        const data = await resp.json().catch(() => ({}));
        alert("删除失败：" + (data.detail || ""));
      }
    });
  });

  document.querySelectorAll(".run-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      if (!confirm("在后台启动该脚本？下载任务可能耗时很长。")) return;
      btn.disabled = true;
      btn.textContent = "启动中…";
      const resp = await fetch(`/api/scripts/${btn.dataset.id}/run`, { method: "POST" });
      const data = await resp.json().catch(() => ({}));
      if (resp.ok) {
        window.__POLL_RUNS__ = true;
        location.reload();
      } else {
        alert("启动失败：" + (data.detail || ""));
        btn.disabled = false;
        btn.textContent = "运行";
      }
    });
  });
})();

// ---- 运行日志展开 ----
(function () {
  document.querySelectorAll(".log-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const row = document.getElementById("log-" + btn.dataset.log);
      if (!row) return;
      row.classList.toggle("hidden");
      btn.textContent = row.classList.contains("hidden") ? "查看" : "收起";
    });
  });
})();

// ---- 有脚本运行中时自动刷新页面 ----
(function () {
  if (!window.__POLL_RUNS__) return;
  const interval = setInterval(async () => {
    try {
      const resp = await fetch("/api/runs/recent?limit=1");
      const data = await resp.json();
      if (!data.has_running) {
        clearInterval(interval);
        location.reload();
      }
    } catch (_) { /* ignore */ }
  }, 3000);
})();

// ---- 资源库：点击预览大图/播放 ----
(function () {
  const box = document.getElementById("lightbox");
  const body = box?.querySelector(".lightbox-body");
  const grid = document.getElementById("res-grid");
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
    const indet = card.querySelector(".res-progress-indeterminate");
    const label = card.querySelector(".res-progress-label");
    const pct = card.querySelector(".res-progress-pct");

    if (track) {
      track.className = "res-progress-track status-dl-" + item.download_status;
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
