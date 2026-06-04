// 资源库后台前端交互（原生 JS，无构建步骤）

// ---- 资源页：多选 + 批量发送 ----
(function () {
  const selectAll = document.getElementById("select-all");
  const sendBtn = document.getElementById("btn-send");
  const counter = document.getElementById("sel-count");
  if (!sendBtn) return;

  const checks = () => Array.from(document.querySelectorAll(".row-check"));
  const selected = () => checks().filter((c) => c.checked).map((c) => parseInt(c.value));

  function refresh() {
    const n = selected().length;
    counter.textContent = `已选 ${n} 条`;
    sendBtn.disabled = n === 0;
  }

  if (selectAll) {
    selectAll.addEventListener("change", () => {
      checks().forEach((c) => (c.checked = selectAll.checked));
      refresh();
    });
  }
  document.addEventListener("change", (e) => {
    if (e.target.classList.contains("row-check")) refresh();
  });

  sendBtn.addEventListener("click", async () => {
    const ids = selected();
    if (!ids.length) return;
    if (!confirm(`确认把 ${ids.length} 条资源发送去剪片？`)) return;
    sendBtn.disabled = true;
    try {
      const resp = await fetch("/api/resources/batch-send", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ resource_ids: ids }),
      });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.detail || "发送失败");
      const note = data.mode === "stub" ? "（接口未配置，已本地标记为已发送切片）" : "";
      alert(`已发送 ${data.sent} 条，失败 ${data.failed} 条 ${note}`);
      location.reload();
    } catch (err) {
      alert("发送失败：" + err.message);
      sendBtn.disabled = false;
    }
  });
})();

// ---- 脚本页：登记 + 运行 ----
(function () {
  const form = document.getElementById("add-script");
  if (form) {
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const fd = new FormData(form);
      const resp = await fetch("/api/scripts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: fd.get("name"),
          command: fd.get("command"),
          description: fd.get("description"),
        }),
      });
      if (resp.ok) location.reload();
      else alert("保存失败");
    });
  }

  document.querySelectorAll(".run-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      btn.disabled = true;
      btn.textContent = "运行中…";
      const resp = await fetch(`/api/scripts/${btn.dataset.id}/run`, { method: "POST" });
      const data = await resp.json();
      if (resp.ok) alert(`已启动运行，run #${data.run_id}`);
      else alert("启动失败：" + (data.detail || ""));
      btn.disabled = false;
      btn.textContent = "运行";
    });
  });
})();
