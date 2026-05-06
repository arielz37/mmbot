const chatFeed = document.querySelector("#chatFeed");
const chatForm = document.querySelector("#chatForm");
const questionInput = document.querySelector("#questionInput");
const chatStatus = document.querySelector("#chatStatus");
const chatStatusInline = document.querySelector("#chatStatusInline");
const faqList = document.querySelector("#faqList");
const clearChatButton = document.querySelector("#clearChatButton");

let sessionId = `web-${crypto.randomUUID()}`;
let isSending = false;

function setStatus(text, state = "normal") {
  chatStatus.textContent = text;
  chatStatus.dataset.state = state;
  chatStatusInline.textContent = text;
  chatStatusInline.parentElement.dataset.state = state;
}

function scrollToBottom() {
  chatFeed.scrollTop = chatFeed.scrollHeight;
}

function escapeHtml(text) {
  return String(text)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function formatMessageText(text) {
  return escapeHtml(text)
    .split(/\n{2,}/)
    .map((paragraph) => `<p class="message-text">${paragraph.replaceAll("\n", "<br />")}</p>`)
    .join("");
}

function sourceRecordLabel(record) {
  return `${record.title} · ${record.entity_type}`;
}

function formatFieldList(fields = []) {
  if (!fields.length) return "未标注字段";
  return fields.join(" / ");
}

function buildSourceMarkup(sources = []) {
  if (!sources.length) return "";
  const summary = `引用来源 ${sources.length} 条`;
  return `
    <details class="source-panel">
      <summary>${escapeHtml(summary)}</summary>
      <div class="source-list">
        ${sources
          .map(
            (record) => `
              <div class="source-chip">
                <strong>${escapeHtml(sourceRecordLabel(record))}</strong>
                <span>${escapeHtml(formatFieldList(record.fields || []))}</span>
              </div>
            `
          )
          .join("")}
      </div>
    </details>
  `;
}

function buildMetaMarkup(meta = []) {
  if (!meta.length) return "";
  return `
    <div class="message-meta-row">
      ${meta.map((item) => `<span class="meta-badge">${escapeHtml(item)}</span>`).join("")}
    </div>
  `;
}

function appendMessage({ role, text, meta = [], sources = [], pending = false, loadingText = "" }) {
  const article = document.createElement("article");
  article.className = `message ${role}${pending ? " pending" : ""}`;

  const contentMarkup = pending
    ? `
      <div class="loading-block">
        <div class="typing-dots" aria-hidden="true">
          <span></span>
          <span></span>
          <span></span>
        </div>
        <p class="loading-text">${escapeHtml(loadingText || "正在思考...")}</p>
      </div>
    `
    : formatMessageText(text);

  article.innerHTML = `
    <div class="avatar">${role === "user" ? "我" : "AI"}</div>
    <div class="bubble">
      ${contentMarkup}
      ${buildMetaMarkup(meta)}
      ${buildSourceMarkup(sources)}
    </div>
  `;

  chatFeed.appendChild(article);
  scrollToBottom();
  return article;
}

async function requestJson(url, options = {}) {
  const response = await fetch(url, {
    headers: {
      "Content-Type": "application/json"
    },
    ...options
  });

  if (!response.ok) {
    const data = await response.json().catch(() => ({ error: "请求失败" }));
    throw new Error(data.error || "请求失败");
  }

  return response.json();
}

function answerModeLabel(mode) {
  if (mode === "template") return "数据库模板回答";
  if (mode === "general") return "日常聊天回答";
  if (mode === "grounded") return "基于证据生成";
  return "混合回答";
}

async function loadFaqs() {
  try {
    const data = await requestJson("/faq");
    faqList.innerHTML = "";

    if (!data.items.length) {
      faqList.innerHTML = `<p class="empty">当前还没有已发布 FAQ。</p>`;
      return;
    }

    for (const item of data.items) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "faq-chip";
      button.textContent = item.question;
      button.addEventListener("click", () => {
        questionInput.value = item.question;
        questionInput.focus();
      });
      faqList.appendChild(button);
    }
  } catch (error) {
    faqList.innerHTML = `<p class="empty">FAQ 加载失败：${escapeHtml(error.message)}</p>`;
  }
}

function setComposerDisabled(disabled) {
  isSending = disabled;
  questionInput.disabled = disabled;
  chatForm.querySelector('button[type="submit"]').disabled = disabled;
}

async function sendQuestion(question) {
  appendMessage({ role: "user", text: question });
  const pendingMessage = appendMessage({
    role: "assistant",
    pending: true,
    loadingText: "正在分析你的问题，并查询相关社团资料..."
  });

  setComposerDisabled(true);
  setStatus("正在思考", "loading");

  try {
    const result = await requestJson("/chat", {
      method: "POST",
      body: JSON.stringify({
        session_id: sessionId,
        question
      })
    });

    pendingMessage.remove();

    const metaParts = [answerModeLabel(result.answer_mode), `置信度：${result.confidence_level}`];
    if (result.needs_verification) {
      metaParts.push("建议进一步核实");
    }
    if (result.source_records?.length) {
      metaParts.push(`来源 ${result.source_records.length} 条`);
    }

    appendMessage({
      role: "assistant",
      text: result.answer_text,
      meta: metaParts,
      sources: result.source_records || []
    });

    setStatus("回复完成", "success");
  } catch (error) {
    pendingMessage.remove();
    appendMessage({
      role: "assistant",
      text: `这次请求没有成功：${error.message}`,
      meta: ["接口错误"]
    });
    setStatus("请求失败", "error");
  } finally {
    setComposerDisabled(false);
    questionInput.focus();
  }
}

chatForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (isSending) return;

  const question = questionInput.value.trim();
  if (!question) return;

  questionInput.value = "";
  await sendQuestion(question);
});

clearChatButton.addEventListener("click", () => {
  sessionId = `web-${crypto.randomUUID()}`;
  chatFeed.innerHTML = `
    <article class="message assistant intro">
      <div class="avatar">AI</div>
      <div class="bubble">
        <p class="message-text">会话已经清空啦。你可以继续问我社团活动、报名方式、部门介绍或者签到规则。</p>
      </div>
    </article>
  `;
  setStatus("会话已清空", "normal");
  questionInput.focus();
});

questionInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    chatForm.requestSubmit();
  }
});

loadFaqs();
