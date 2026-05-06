const entityForm = document.querySelector("#entityForm");
const entityList = document.querySelector("#entityList");
const unmatchedList = document.querySelector("#unmatchedList");
const chatLogList = document.querySelector("#chatLogList");
const refreshButton = document.querySelector("#refreshButton");
const chatButton = document.querySelector("#chatButton");
const chatQuestion = document.querySelector("#chatQuestion");
const chatResult = document.querySelector("#chatResult");
const dynamicFields = document.querySelector("#dynamicFields");
const cancelEditButton = document.querySelector("#cancelEditButton");
const formTitle = document.querySelector("#formTitle");
const formHint = document.querySelector("#formHint");
const submitButton = document.querySelector("#submitButton");

const FIELD_SCHEMAS = {
  event: [
    { name: "event_name", label: "活动名称", type: "text", required: true },
    { name: "time", label: "活动时间", type: "text", placeholder: "例如 2026-04-20 19:00", required: true },
    { name: "location", label: "活动地点", type: "text", required: true },
    { name: "signup_method", label: "报名方式", type: "textarea", required: true },
    { name: "audience", label: "面向对象", type: "text" },
    { name: "fee", label: "费用", type: "text" },
    { name: "owner", label: "负责人", type: "text" },
    { name: "status_label", label: "活动状态", type: "text", placeholder: "例如 报名中" },
    { name: "intro_text", label: "活动介绍", type: "textarea" }
  ],
  signup_rule: [
    { name: "target_event_slug", label: "关联活动 slug", type: "text", required: true },
    { name: "eligibility", label: "报名条件", type: "textarea" },
    { name: "deadline", label: "报名截止时间", type: "text", required: true },
    { name: "process", label: "报名流程", type: "textarea" },
    { name: "reminder", label: "补充提醒", type: "textarea" }
  ],
  department: [
    { name: "department_name", label: "部门名称", type: "text", required: true },
    { name: "manager", label: "负责人", type: "text" },
    { name: "responsibilities", label: "部门职责", type: "textarea", placeholder: "每行一条职责" },
    { name: "intro", label: "部门介绍", type: "textarea" }
  ],
  contact: [
    { name: "contact_name", label: "联系人姓名", type: "text", required: true },
    { name: "role", label: "身份/角色", type: "text" },
    { name: "channel", label: "联系渠道", type: "text", placeholder: "例如 微信" },
    { name: "contact_value", label: "联系方式", type: "text", required: true },
    { name: "available_time", label: "可联系时间", type: "text" }
  ],
  faq_entry: [
    { name: "question", label: "标准问题", type: "text", required: true },
    { name: "aliases", label: "问题别名", type: "textarea", placeholder: "每行一个别名" },
    { name: "answer", label: "标准答案", type: "textarea", required: true },
    { name: "related_entity_type", label: "关联记录类型", type: "text" },
    { name: "related_entity_slug", label: "关联记录 slug", type: "text" }
  ],
  policy_article: [
    { name: "summary", label: "制度摘要", type: "textarea", required: true },
    { name: "details", label: "详细说明", type: "textarea" }
  ],
  club_profile: [
    { name: "club_name", label: "社团名称", type: "text", required: true },
    { name: "mission", label: "社团使命", type: "textarea" },
    { name: "intro", label: "社团介绍", type: "textarea" },
    { name: "base_location", label: "常驻地点", type: "text" },
    { name: "contact_hint", label: "联系提示", type: "textarea" }
  ]
};

let editingEntityId = null;

function toDatetimeLocalValue(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";

  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  const hours = String(date.getHours()).padStart(2, "0");
  const minutes = String(date.getMinutes()).padStart(2, "0");
  return `${year}-${month}-${day}T${hours}:${minutes}`;
}

function fromDatetimeLocalValue(value) {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return date.toISOString();
}

async function request(url, options = {}) {
  const response = await fetch(url, {
    headers: {
      "Content-Type": "application/json"
    },
    ...options
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ error: "Request failed" }));
    throw new Error(error.error || "Request failed");
  }
  return response.json();
}

function renderRows(container, rows, emptyText) {
  container.innerHTML = "";
  if (!rows.length) {
    container.innerHTML = `<p class="empty">${emptyText}</p>`;
    return;
  }

  for (const row of rows) {
    const block = document.createElement("article");
    block.className = "table-row";
    block.innerHTML = `
      <div class="table-main">
        <strong>${row.title || row.question || row.answer_text || "未命名记录"}</strong>
        <p>${row.entity_type || row.reason || row.confidence_level || ""}</p>
      </div>
      <pre>${JSON.stringify(row, null, 2)}</pre>
    `;
    container.appendChild(block);
  }
}

function summarizeDebugTrace(trace = {}) {
  const parts = [];
  if (trace.selected_path) parts.push(`路径：${trace.selected_path}`);
  if (trace.final_answer?.matched_entity_type) {
    parts.push(`命中：${trace.final_answer.matched_entity_type}#${trace.final_answer.matched_entity_id ?? "?"}`);
  }
  if (trace.turn_analysis?.answer_strategy) parts.push(`策略：${trace.turn_analysis.answer_strategy}`);
  return parts.join(" · ");
}

function renderChatLogRows(rows) {
  chatLogList.innerHTML = "";
  if (!rows.length) {
    chatLogList.innerHTML = `<p class="empty">暂无问答日志</p>`;
    return;
  }

  for (const row of rows) {
    const article = document.createElement("article");
    article.className = "table-row debug-row";
    const debugSummary = summarizeDebugTrace(row.debug_trace || {});
    article.innerHTML = `
      <div class="table-main">
        <strong>${escapeHtml(row.question || "未记录问题")}</strong>
        <p>${escapeHtml(`${row.answer_mode} · ${row.confidence_level}${debugSummary ? ` · ${debugSummary}` : ""}`)}</p>
      </div>
      <div class="debug-answer">${escapeHtml(row.answer_text || "")}</div>
      <details class="debug-details">
        <summary>查看调试轨迹</summary>
        <pre>${escapeHtml(JSON.stringify(row.debug_trace || {}, null, 2))}</pre>
      </details>
    `;
    chatLogList.appendChild(article);
  }
}

function escapeHtml(text) {
  return String(text)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function getSchema(type) {
  return FIELD_SCHEMAS[type] || [];
}

function renderDynamicFields(type, values = {}) {
  const schema = getSchema(type);
  dynamicFields.innerHTML = "";

  for (const field of schema) {
    const wrapper = document.createElement("label");
    const value = values[field.name] ?? "";
    const placeholder = field.placeholder ? ` placeholder="${escapeHtml(field.placeholder)}"` : "";
    const required = field.required ? "required" : "";

    wrapper.innerHTML =
      field.type === "textarea"
        ? `
          ${field.label}
          <textarea name="field_${field.name}" rows="4" ${required}${placeholder}>${escapeHtml(
            Array.isArray(value) ? value.join("\n") : value
          )}</textarea>
        `
        : `
          ${field.label}
          <input name="field_${field.name}" value="${escapeHtml(value)}" ${required}${placeholder} />
        `;

    dynamicFields.appendChild(wrapper);
  }
}

function normalizeFieldValue(field, rawValue) {
  if (field.name === "responsibilities" || field.name === "aliases") {
    return rawValue
      .split("\n")
      .map((item) => item.trim())
      .filter(Boolean);
  }
  return rawValue.trim();
}

function collectDynamicData(entityType, formData) {
  const data = {};
  for (const field of getSchema(entityType)) {
    const rawValue = String(formData.get(`field_${field.name}`) || "");
    if (!rawValue.trim()) continue;
    data[field.name] = normalizeFieldValue(field, rawValue);
  }
  return data;
}

function resetForm() {
  editingEntityId = null;
  entityForm.reset();
  entityForm.querySelector('[name="status"]').value = "draft";
  entityForm.querySelector('[name="updated_by"]').value = "admin";
  entityForm.querySelector('[name="entity_id"]').value = "";
  entityForm.querySelector('[name="effective_at"]').value = "";
  formTitle.textContent = "录入结构化知识";
  formHint.textContent = "按类型填写字段，不需要手写 JSON。";
  submitButton.textContent = "保存记录";
  cancelEditButton.classList.add("hidden");
  renderDynamicFields(entityForm.querySelector('[name="entity_type"]').value);
}

function startEdit(entity) {
  editingEntityId = entity.id;
  entityForm.querySelector('[name="entity_id"]').value = String(entity.id);
  entityForm.querySelector('[name="entity_type"]').value = entity.entity_type;
  entityForm.querySelector('[name="slug"]').value = entity.slug;
  entityForm.querySelector('[name="title"]').value = entity.title;
  entityForm.querySelector('[name="status"]').value = entity.status;
  entityForm.querySelector('[name="effective_at"]').value = toDatetimeLocalValue(entity.effective_at);
  entityForm.querySelector('[name="updated_by"]').value = entity.updated_by || "admin";
  renderDynamicFields(entity.entity_type, entity.data || {});
  formTitle.textContent = `编辑记录 #${entity.id}`;
  formHint.textContent = "编辑后会生成一个新版本，原记录仍然保留在历史里。";
  submitButton.textContent = "保存为新版本";
  cancelEditButton.classList.remove("hidden");
  entityForm.scrollIntoView({ behavior: "smooth", block: "start" });
}

function buildEntityActions(row) {
  if (!row.id) return "";
  const publishButton =
    row.status !== "published"
      ? `<button type="button" class="small-button" data-action="publish" data-id="${row.id}">发布</button>`
      : "";
  return `
    <div class="row-actions">
      <button type="button" class="small-button" data-action="edit" data-id="${row.id}">编辑</button>
      ${publishButton}
      <button type="button" class="small-button danger" data-action="delete" data-id="${row.id}">删除</button>
    </div>
  `;
}

function renderEntityRows(rows) {
  entityList.innerHTML = "";
  if (!rows.length) {
    entityList.innerHTML = `<p class="empty">暂无知识记录</p>`;
    return;
  }

  for (const row of rows) {
    const block = document.createElement("article");
    block.className = "table-row";
    block.innerHTML = `
      <div class="table-main">
        <strong>${escapeHtml(row.title || "未命名记录")}</strong>
        <p>${escapeHtml(`${row.entity_type} · ${row.status} · v${row.version}`)}</p>
      </div>
      ${buildEntityActions(row)}
      <pre>${escapeHtml(JSON.stringify(row, null, 2))}</pre>
    `;
    entityList.appendChild(block);
  }
}

async function refresh() {
  const [entities, unmatched, chatLogs] = await Promise.all([
    request("/admin/entities"),
    request("/admin/unmatched-questions"),
    request("/admin/chat-logs")
  ]);

  renderEntityRows(entities.items);
  renderRows(unmatchedList, unmatched.items, "暂无未命中问题");
  renderChatLogRows(chatLogs.items);
}

entityForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const formData = new FormData(entityForm);
  const entityType = String(formData.get("entity_type"));
  const payload = {
    entity_type: entityType,
    slug: String(formData.get("slug") || "").trim(),
    title: String(formData.get("title") || "").trim(),
    status: String(formData.get("status") || "draft"),
    effective_at: fromDatetimeLocalValue(String(formData.get("effective_at") || "").trim()),
    updated_by: String(formData.get("updated_by") || "admin").trim(),
    data: collectDynamicData(entityType, formData)
  };

  if (editingEntityId) {
    await request(`/admin/entities/${editingEntityId}`, {
      method: "PUT",
      body: JSON.stringify(payload)
    });
  } else {
    await request("/admin/entities", {
      method: "POST",
      body: JSON.stringify(payload)
    });
  }

  resetForm();
  await refresh();
});

refreshButton.addEventListener("click", refresh);
cancelEditButton.addEventListener("click", resetForm);

entityForm.querySelector('[name="entity_type"]').addEventListener("change", (event) => {
  renderDynamicFields(event.target.value);
});

chatButton.addEventListener("click", async () => {
  const question = chatQuestion.value.trim();
  if (!question) return;

  const result = await request("/chat", {
    method: "POST",
    body: JSON.stringify({
      session_id: "admin-preview",
      question
    })
  });

  chatResult.textContent = JSON.stringify(result, null, 2);
  await refresh();
});

entityList.addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-action]");
  if (!button) return;

  const action = button.dataset.action;
  const id = button.dataset.id;
  if (!id) return;

  if (action === "edit") {
    const entity = await request(`/admin/entities/${id}`);
    startEdit(entity);
    return;
  }

  if (action === "publish") {
    await request(`/admin/entities/${id}/publish`, {
      method: "POST",
      body: JSON.stringify({
        updated_by: entityForm.querySelector('[name="updated_by"]').value || "admin"
      })
    });
    await refresh();
    return;
  }

  if (action === "delete") {
    const confirmed = window.confirm("删除后这条记录会直接从数据库中移除。确认删除吗？");
    if (!confirmed) return;
    await request(`/admin/entities/${id}`, { method: "DELETE" });
    if (editingEntityId === Number(id)) {
      resetForm();
    }
    await refresh();
  }
});

resetForm();
refresh();
