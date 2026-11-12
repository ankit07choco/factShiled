const PRESETS = {
  unesco: "URGENT MUST SHARE!! UNESCO has declared our Indian National Anthem 'Jana Gana Mana' as the best national anthem in the world!! Forward to 10 groups immediately!",
  garlic: "BREAKING NEWS!! Drinking boiled garlic water cures COVID-19 infection overnight! Share maximum to save lives!!",
  recharge: "Government is giving free Rs 5000 recharge to all mobile users under PM Yojna. Click link to claim now!",
  nasa: "NASA satellite photos show India fully illuminated on Diwali night! Forward to all proud Indians!",
  isro: "ISRO launched Chandrayaan-3 mission successfully landing on the lunar south pole."
};

let chartInstance1 = null;
let chartInstance2 = null;
let allFactChecks = [];
let currentRole = "user";
let csrfToken = "";
let editingRecord = null;
let activeInputMode = "text";

function applyPreset(key) {
  const claimInput = document.getElementById("claimInput");
  claimInput.value = PRESETS[key] || "";
  document.getElementById("claimCharacterCount").textContent = claimInput.value.length;
  setInputMode("text");
}

async function fetchJson(url, options) {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || data.detail || `Request failed (${response.status})`);
  }
  return data;
}

function csrfHeaders() {
  return csrfToken ? { "X-CSRF-Token": csrfToken } : {};
}

function setInputMode(mode) {
  activeInputMode = mode;
  document.querySelectorAll("[data-input-mode]").forEach(button => {
    button.classList.toggle("active", button.dataset.inputMode === mode);
  });
  document.getElementById("imageInputGroup").classList.toggle("d-none", mode !== "image");
  if (mode !== "image") document.getElementById("imageInput").value = "";

  const claimInput = document.getElementById("claimInput");
  claimInput.placeholder = mode === "link"
    ? "Paste a public article URL to extract and verify its text..."
    : "Paste a WhatsApp forward, news claim, or link to verify...";
  if (mode === "image") {
    claimInput.placeholder = "Optional: add a caption or context for the image...";
  }
}

function showError(elementId, message) {
  const element = document.getElementById(elementId);
  element.textContent = message;
  element.classList.remove("d-none");
}

function hideError(elementId) {
  document.getElementById(elementId).classList.add("d-none");
}

async function submitVerification(event) {
  event.preventDefault();
  const text = document.getElementById("claimInput").value.trim();
  const image = activeInputMode === "image"
    ? document.getElementById("imageInput").files[0]
    : null;
  const button = document.getElementById("verifyBtn");
  hideError("verifyError");
  document.getElementById("savedRecordNotice").classList.add("d-none");

  if (!text && !image) {
    showError("verifyError", "Enter a claim or attach an image.");
    return;
  }

  const formData = new FormData();
  if (text) formData.append("text", text);
  if (image) formData.append("image", image);
  formData.append("input_mode", activeInputMode);

  document.getElementById("placeholderResult").classList.remove("d-none");
  document.getElementById("actualResult").classList.add("d-none");
  button.disabled = true;
  button.textContent = "Analyzing...";
  try {
    const data = await fetchJson("/api/verify", { method: "POST", body: formData });
    renderVerificationResults(data);
    await refreshDashboardData();
  } catch (error) {
    showError("verifyError", error.message);
  } finally {
    button.disabled = false;
    button.innerHTML = '<i class="fa-solid fa-shield-virus me-2"></i>Run Verification';
  }
}

function renderVerificationResults(data) {
  document.getElementById("placeholderResult").classList.add("d-none");
  document.getElementById("actualResult").classList.remove("d-none");

  const verdict = data.verdict || "Unverified";
  document.getElementById("resultClaim").textContent =
    data.primary_claim || data.input_text || "No readable claim text was extracted.";
  const savedNotice = document.getElementById("savedRecordNotice");
  savedNotice.textContent = data.saved_to_database
    ? `This ${verdict} result was saved to the shared verified-claims database${data.database_record_id ? ` (record #${data.database_record_id})` : ""}.`
    : "This result was not saved. Only Likely True and Likely False claim results are added to the database.";
  savedNotice.className = `alert ${data.saved_to_database ? "alert-success" : "alert-info"} mt-3`;
  const badge = document.getElementById("verdictBadge");
  badge.textContent = verdict.toUpperCase();
  badge.className = "badge-verdict";
  const badgeClass = {
    "Likely False": "badge-false",
    "Likely True": "badge-true",
    Disputed: "badge-disputed",
    Unverified: "badge-unverified"
  }[verdict] || "badge-unverified";
  badge.classList.add(badgeClass);

  const confidence = Number.isFinite(Number(data.confidence_score))
    ? Math.max(0, Math.min(100, Number(data.confidence_score)))
    : 0;
  document.getElementById("langBadge").textContent = data.language?.name || "Unknown";
  document.getElementById("confidenceScore").textContent = `${confidence}%`;
  const confidenceBar = document.getElementById("confidenceBar");
  confidenceBar.style.width = `${confidence}%`;
  confidenceBar.className = `progress-bar ${badgeClass === "badge-false" ? "bg-danger" : badgeClass === "badge-true" ? "bg-success" : badgeClass === "badge-disputed" ? "bg-warning" : "bg-info"}`;
  document.getElementById("explanationText").textContent = data.explanation || "No explanation was returned.";

  const imageOrigin = data.image_origin && typeof data.image_origin === "object"
    ? data.image_origin
    : null;
  const imageOriginBox = document.getElementById("imageOriginResult");
  imageOriginBox.classList.toggle("d-none", !imageOrigin);
  if (imageOrigin) {
    document.getElementById("imageOriginVerdict").textContent =
      imageOrigin.verdict || "Inconclusive";
    document.getElementById("imageOriginExplanation").textContent =
      imageOrigin.explanation || imageOrigin.message || "No image-origin assessment was returned.";
    document.getElementById("imageOriginDisclaimer").textContent =
      imageOrigin.disclaimer ||
      "Visual AI-image detection is uncertain and cannot prove an image's origin.";
  }

  const signals = data.signals || {};
  document.getElementById("signalFcScore").textContent = signals.fact_check_match
    ? `${signals.fact_check_match.score}% (${signals.fact_check_match.rating})`
    : "0%";
  document.getElementById("signalSemScore").textContent = signals.semantic_similarity
    ? `${signals.semantic_similarity.score}%`
    : "0%";
  document.getElementById("signalStyleScore").textContent = signals.style_classifier
    ? `${signals.style_classifier.score}% (Caps: ${signals.style_classifier.caps_ratio})`
    : "0%";
  document.getElementById("signalEvidScore").textContent = signals.source_evidence
    ? `${signals.source_evidence.score}%`
    : "0%";

  const sources = document.getElementById("sourcesList");
  sources.replaceChildren();
  if (Array.isArray(data.sources) && data.sources.length) {
    const list = document.createElement("ul");
    list.className = "list-unstyled mb-0";
    data.sources.forEach(source => {
      const item = document.createElement("li");
      item.className = "mb-1";
      const link = document.createElement("a");
      link.href = source.url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.className = "text-info text-decoration-none";
      link.textContent = `${source.source_type || source.publisher || "Source"}: ${source.title || source.url}`;
      item.append(link);
      list.append(item);
    });
    sources.append(list);
  } else {
    sources.textContent = "No citable source was returned.";
  }

  const mediaNotice = document.getElementById("mediaNotice");
  const notices = [];
  if (data.ocr_result?.error && data.input_text) notices.push(data.ocr_result.error);
  if (data.fact_check_lookup?.message) notices.push(data.fact_check_lookup.message);
  if (data.web_search?.message) notices.push(data.web_search.message);
  if (data.article_extraction?.message) notices.push(data.article_extraction.message);
  mediaNotice.textContent = notices.join(" ");
}

function appendChatBubble(container, text, type) {
  const bubble = document.createElement("div");
  bubble.className = `chat-bubble ${type}`;
  bubble.textContent = text;
  container.append(bubble);
  container.scrollTop = container.scrollHeight;
  return bubble;
}

async function sendSimulatedMsg() {
  const input = document.getElementById("simInput");
  const mediaInput = document.getElementById("simMediaInput");
  const text = input.value.trim();
  const media = mediaInput.files[0];
  if (!text && !media) return;

  const chat = document.getElementById("chatContainer");
  appendChatBubble(chat, text || `Attached ${media.name}`, "user");
  input.value = "";
  mediaInput.value = "";
  const typingBubble = appendChatBubble(chat, "FactShield is checking...", "bot text-muted");
  document.getElementById("simSendBtn").disabled = true;

  try {
    let reply;
    if (media) {
      const formData = new FormData();
      formData.append("image", media);
      if (text) formData.append("text", text);
      const result = await fetchJson("/api/verify", { method: "POST", body: formData });
      reply = result.whatsapp_reply || `${result.verdict}: ${result.explanation || "No explanation returned."}`;
      if (result.ocr_result?.error && text) reply += `\n\n⚠️ ${result.ocr_result.error}`;
    } else {
      const payload = {
        simulated: true,
        object: "whatsapp_business_account",
        entry: [{
          id: "LOCAL_SIMULATOR",
          changes: [{
            value: {
              messaging_product: "whatsapp",
              messages: [{
                from: "919876543210",
                id: `sim-${Date.now()}`,
                timestamp: String(Math.floor(Date.now() / 1000)),
                text: { body: text },
                type: "text"
              }]
            }
          }]
        }]
      };
      document.getElementById("webhookJsonInspector").textContent = JSON.stringify(payload, null, 2);
      const result = await fetchJson("/webhook/whatsapp", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      reply = result.reply_text || "The simulator did not return a reply.";
    }
    typingBubble.remove();
    appendChatBubble(chat, reply, "bot");
  } catch (error) {
    typingBubble.remove();
    appendChatBubble(chat, `Could not process the message: ${error.message}`, "bot");
  } finally {
    document.getElementById("simSendBtn").disabled = false;
  }
}

async function loadFactChecks() {
  const tbody = document.getElementById("dbTableBody");
  hideError("dbError");
  tbody.innerHTML = '<tr><td colspan="7" class="text-center text-muted">Loading fact checks...</td></tr>';
  try {
    const result = await fetchJson("/api/fact-checks");
    allFactChecks = Array.isArray(result.data) ? result.data : [];
    populateCategoryFilter();
    renderFactCheckTable(allFactChecks);
  } catch (error) {
    showError("dbError", error.message);
    tbody.innerHTML = '<tr><td colspan="7" class="text-center text-muted">Could not load fact checks.</td></tr>';
  }
  await loadBenchmarkStatus();
}

async function loadBenchmarkStatus() {
  const statusBox = document.getElementById("benchmarkStatus");
  try {
    const status = await fetchJson("/api/benchmark/status");
    statusBox.textContent = status.available
      ? `${status.record_count.toLocaleString()} FEVER research claims are available. These are dataset annotations, not published fact-checks. ${status.attribution} License: ${status.license}.`
      : `FEVER benchmark is not imported. Run: .venv/bin/python scripts/import_fever_benchmark.py. The download is approximately 33 MB.`;
    statusBox.className = `alert ${status.available ? "alert-info" : "alert-warning"} small`;
  } catch (error) {
    statusBox.textContent = `Could not check the FEVER benchmark: ${error.message}`;
    statusBox.className = "alert alert-danger small";
  }
}

async function searchBenchmark(event) {
  event.preventDefault();
  const input = document.getElementById("benchmarkSearchInput");
  const tbody = document.getElementById("benchmarkTableBody");
  const button = document.getElementById("benchmarkSearchButton");
  hideError("benchmarkError");
  button.disabled = true;
  try {
    const params = new URLSearchParams({ q: input.value.trim(), limit: "10" });
    const result = await fetchJson(`/api/benchmark/search?${params}`);
    tbody.replaceChildren();
    if (!result.data.length) {
      const row = tbody.insertRow();
      const cell = row.insertCell();
      cell.colSpan = 3;
      cell.className = "text-center text-muted";
      cell.textContent = "No matching benchmark records.";
      return;
    }
    result.data.forEach(record => {
      const row = tbody.insertRow();
      row.insertCell().textContent = record.claim;
      const labelCell = row.insertCell();
      labelCell.textContent = record.label;
      const evidenceCell = row.insertCell();
      record.evidence_articles.forEach((article, index) => {
        if (index) evidenceCell.append(document.createTextNode(", "));
        const link = document.createElement("a");
        link.href = article.url;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        link.textContent = article.title;
        evidenceCell.append(link);
      });
      if (!record.evidence_articles.length) evidenceCell.textContent = "No evidence article recorded";
    });
  } catch (error) {
    showError("benchmarkError", error.message);
  } finally {
    button.disabled = false;
  }
}

function populateCategoryFilter() {
  const select = document.getElementById("dbCatFilter");
  const selected = select.value;
  const categories = [...new Set(allFactChecks.map(item => item.category).filter(Boolean))].sort();
  select.replaceChildren(new Option("All Categories", "All"));
  categories.forEach(category => select.add(new Option(category, category)));
  if ([...select.options].some(option => option.value === selected)) select.value = selected;
}

function renderFactCheckTable(items) {
  const tbody = document.getElementById("dbTableBody");
  tbody.replaceChildren();
  if (!items.length) {
    const row = tbody.insertRow();
    const cell = row.insertCell();
    cell.colSpan = 7;
    cell.className = "text-center text-muted";
    cell.textContent = "No fact-check items match the filter.";
    return;
  }

  items.forEach(item => {
    const row = tbody.insertRow();
    [item.id, item.claim].forEach(value => {
      const cell = row.insertCell();
      cell.textContent = value || "";
    });
    const verdictCell = row.insertCell();
    const verdictBadge = document.createElement("span");
    verdictBadge.className = `badge ${item.verdict === "False" ? "bg-danger" : "bg-success"}`;
    verdictBadge.textContent = item.verdict || "Unknown";
    verdictCell.append(verdictBadge);
    [item.category, item.language, item.publisher].forEach(value => {
      const cell = row.insertCell();
      cell.textContent = value || "";
    });
    const sourceCell = row.insertCell();
    if (item.url && /^https?:\/\//i.test(item.url)) {
      const link = document.createElement("a");
      link.href = item.url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.className = "btn btn-outline-success btn-sm";
      link.textContent = "Source";
      sourceCell.append(link);
    } else {
      sourceCell.textContent = "—";
    }
  });
}

function filterFactChecks() {
  const query = document.getElementById("dbSearchInput").value.trim().toLowerCase();
  const category = document.getElementById("dbCatFilter").value;
  const filtered = allFactChecks.filter(item => {
    const searchable = [
      item.claim,
      item.claim_hi,
      item.claim_bn,
      item.summary,
      ...(item.keywords || [])
    ].join(" ").toLowerCase();
    return (!query || searchable.includes(query)) && (category === "All" || item.category === category);
  });
  renderFactCheckTable(filtered);
}

function formatUpdatedAt(value) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function verdictClass(verdict) {
  return verdict === "Likely True" ? "badge-true" : "badge-false";
}

async function loadSavedVerifications() {
  const search = document.getElementById("savedDbSearchInput").value.trim();
  const params = new URLSearchParams({ limit: "100" });
  if (search) params.set("search", search);
  hideError("savedDbError");
  hideError("historyError");

  try {
    const result = await fetchJson(`/api/verifications?${params}`);
    const records = Array.isArray(result.data) ? result.data : [];
    renderSavedVerifications(records);
  } catch (error) {
    showError("savedDbError", error.message);
    showError("historyError", error.message);
  }
}

function renderSavedVerifications(records) {
  const savedBody = document.getElementById("savedDbTableBody");
  const historyBody = document.getElementById("historyTableBody");
  const recent = document.getElementById("recentVerifications");
  savedBody.replaceChildren();
  historyBody.replaceChildren();
  recent.replaceChildren();

  if (!records.length) {
    const savedRow = savedBody.insertRow();
    const savedCell = savedRow.insertCell();
    savedCell.colSpan = 7;
    savedCell.className = "text-center text-muted py-4";
    savedCell.textContent = "No conclusive verifications have been saved yet.";
    const historyRow = historyBody.insertRow();
    const historyCell = historyRow.insertCell();
    historyCell.colSpan = 5;
    historyCell.className = "text-center text-muted py-4";
    historyCell.textContent = "No conclusive verifications have been saved yet.";
    recent.textContent = "No conclusive results have been saved yet.";
    return;
  }

  records.forEach(record => {
    const row = savedBody.insertRow();
    [record.id, record.claim].forEach(value => {
      row.insertCell().textContent = value ?? "";
    });
    const verdictCell = row.insertCell();
    const verdictBadge = document.createElement("span");
    verdictBadge.className = `badge ${verdictClass(record.verdict)}`;
    verdictBadge.textContent = record.verdict;
    verdictCell.append(verdictBadge);
    row.insertCell().textContent = `${record.confidence_score}%`;
    row.insertCell().textContent = formatUpdatedAt(record.updated_at);
    row.insertCell().textContent = Number(record.verification_count || 1).toLocaleString();

    const actions = row.insertCell();
    actions.className = "admin-column";
    if (currentRole === "admin") {
      const editButton = document.createElement("button");
      editButton.type = "button";
      editButton.className = "btn btn-outline-info btn-sm me-1";
      editButton.textContent = "Edit";
      editButton.addEventListener("click", () => openEditVerification(record));
      const deleteButton = document.createElement("button");
      deleteButton.type = "button";
      deleteButton.className = "btn btn-outline-danger btn-sm";
      deleteButton.textContent = "Delete";
      deleteButton.addEventListener("click", () => deleteVerification(record));
      actions.append(editButton, deleteButton);
    } else {
      actions.classList.add("d-none");
    }

    const historyRow = historyBody.insertRow();
    historyRow.insertCell().textContent = record.claim;
    const historyVerdict = historyRow.insertCell();
    const historyBadge = document.createElement("span");
    historyBadge.className = `badge ${verdictClass(record.verdict)}`;
    historyBadge.textContent = record.verdict;
    historyVerdict.append(historyBadge);
    historyRow.insertCell().textContent = `${record.confidence_score}%`;
    historyRow.insertCell().textContent = formatUpdatedAt(record.updated_at);
    historyRow.insertCell().textContent = Number(record.verification_count || 1).toLocaleString();

    const recentItem = document.createElement("div");
    recentItem.className = "recent-item";
    const icon = document.createElement("span");
    icon.className = `recent-verdict-icon ${verdictClass(record.verdict)}`;
    icon.innerHTML = record.verdict === "Likely True"
      ? '<i class="fa-solid fa-check"></i>'
      : '<i class="fa-solid fa-xmark"></i>';
    const claim = document.createElement("span");
    claim.className = "recent-claim";
    claim.textContent = record.claim;
    claim.title = record.claim;
    const badge = document.createElement("span");
    badge.className = `badge ${verdictClass(record.verdict)}`;
    badge.textContent = record.verdict.replace("Likely ", "");
    recentItem.append(icon, claim, badge);
    recent.append(recentItem);
  });
}

async function loadDashboardSummary() {
  try {
    const analytics = await fetchJson("/api/analytics");
    document.getElementById("statFactChecks").textContent =
      Number(analytics.total_fact_checks_indexed || 0).toLocaleString();
    const saved = analytics.saved_verifications || {};
    const verdicts = saved.verdicts || {};
    document.getElementById("statVerifiedTotal").textContent =
      Number(saved.total || 0).toLocaleString();
    document.getElementById("statTrueCount").textContent =
      Number(verdicts["Likely True"] || 0).toLocaleString();
    document.getElementById("statFalseCount").textContent =
      Number(verdicts["Likely False"] || 0).toLocaleString();
  } catch (error) {
    document.getElementById("statFactChecks").textContent = "—";
    document.getElementById("statFactChecks").title = error.message;
    document.getElementById("statVerifiedTotal").textContent = "—";
    document.getElementById("statTrueCount").textContent = "—";
    document.getElementById("statFalseCount").textContent = "—";
  }
}

async function refreshDashboardData() {
  await Promise.all([loadSavedVerifications(), loadDashboardSummary()]);
}

function updateRoleControls() {
  const isAdmin = currentRole === "admin";
  const badge = document.getElementById("roleBadge");
  badge.textContent = isAdmin ? "Admin" : "User";
  badge.classList.toggle("role-admin", isAdmin);
  document.getElementById("adminLoginButton").classList.toggle("d-none", isAdmin);
  document.getElementById("adminLogoutButton").classList.toggle("d-none", !isAdmin);
  document.getElementById("adminDatabaseHint").textContent = isAdmin
    ? "Admin mode: you can edit saved verdicts or remove database records."
    : "Browsing as a credential-free user. Admin sign-in enables editing and deletion.";
  document.querySelectorAll(".admin-column").forEach(column => {
    column.classList.toggle("d-none", !isAdmin);
  });
}

async function loadCurrentSession() {
  try {
    const session = await fetchJson("/api/session");
    currentRole = session.role === "admin" ? "admin" : "user";
    csrfToken = typeof session.csrf_token === "string" ? session.csrf_token : "";
  } catch (error) {
    currentRole = "user";
    csrfToken = "";
    document.getElementById("roleBadge").title =
      `Could not check the session: ${error.message}`;
  }
  updateRoleControls();
}

async function submitAdminLogin(event) {
  event.preventDefault();
  const errorBox = document.getElementById("adminLoginError");
  const submitButton = document.getElementById("adminLoginSubmit");
  errorBox.classList.add("d-none");
  submitButton.disabled = true;
  try {
    const credentials = {
      username: document.getElementById("adminUsername").value,
      password: document.getElementById("adminPassword").value
    };
    const session = await fetchJson("/api/admin/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(credentials)
    });
    currentRole = "admin";
    csrfToken = session.csrf_token;
    document.getElementById("adminPassword").value = "";
    updateRoleControls();
    bootstrap.Modal.getOrCreateInstance(
      document.getElementById("adminLoginModal")
    ).hide();
    await loadSavedVerifications();
  } catch (error) {
    errorBox.textContent = error.message;
    errorBox.classList.remove("d-none");
  } finally {
    submitButton.disabled = false;
  }
}

async function logoutAdmin() {
  try {
    await fetchJson("/api/admin/logout", {
      method: "POST",
      headers: csrfHeaders()
    });
    currentRole = "user";
    csrfToken = "";
    updateRoleControls();
    await loadSavedVerifications();
  } catch (error) {
    showError("savedDbError", error.message);
  }
}

function openEditVerification(record) {
  editingRecord = record;
  document.getElementById("editRecordId").value = record.id;
  document.getElementById("editClaim").value = record.claim;
  document.getElementById("editVerdict").value = record.verdict;
  document.getElementById("editConfidence").value = record.confidence_score;
  document.getElementById("editExplanation").value = record.explanation || "";
  hideError("editVerificationError");
  bootstrap.Modal.getOrCreateInstance(
    document.getElementById("editVerificationModal")
  ).show();
}

async function submitVerificationEdit(event) {
  event.preventDefault();
  if (!editingRecord) return;
  hideError("editVerificationError");
  const recordId = document.getElementById("editRecordId").value;
  const changes = {
    claim: document.getElementById("editClaim").value,
    verdict: document.getElementById("editVerdict").value,
    confidence_score: Number(document.getElementById("editConfidence").value),
    explanation: document.getElementById("editExplanation").value,
    sources: editingRecord.sources || []
  };
  try {
    await fetchJson(`/api/verifications/${recordId}`, {
      method: "PUT",
      headers: { ...csrfHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify(changes)
    });
    editingRecord = null;
    bootstrap.Modal.getOrCreateInstance(
      document.getElementById("editVerificationModal")
    ).hide();
    await refreshDashboardData();
  } catch (error) {
    showError("editVerificationError", error.message);
  }
}

async function deleteVerification(record) {
  if (!window.confirm(`Delete saved record #${record.id}?`)) return;
  try {
    await fetchJson(`/api/verifications/${record.id}`, {
      method: "DELETE",
      headers: csrfHeaders()
    });
    await refreshDashboardData();
  } catch (error) {
    showError("savedDbError", error.message);
  }
}

async function loadAnalytics() {
  hideError("analyticsError");
  try {
    const data = await fetchJson("/api/analytics");
    if (typeof Chart === "undefined") {
      throw new Error("Chart.js did not load. Check your internet connection and refresh.");
    }
    if (chartInstance1) chartInstance1.destroy();
    if (chartInstance2) chartInstance2.destroy();
    chartInstance1 = new Chart(document.getElementById("verdictChart"), {
      type: "doughnut",
      data: {
        labels: Object.keys(data.verdict_distribution || {}),
        datasets: [{
          data: Object.values(data.verdict_distribution || {}),
          backgroundColor: ["#ef4444", "#f59e0b", "#3b82f6", "#10b981"]
        }]
      },
      options: { responsive: true, plugins: { legend: { labels: { color: "#e9edef" } } } }
    });
    chartInstance2 = new Chart(document.getElementById("categoryChart"), {
      type: "bar",
      data: {
        labels: Object.keys(data.category_breakdown || {}),
        datasets: [{
          label: "Fact checks",
          data: Object.values(data.category_breakdown || {}),
          backgroundColor: "#25D366"
        }]
      },
      options: {
        responsive: true,
        scales: {
          x: { ticks: { color: "#8696a0" } },
          y: { beginAtZero: true, ticks: { color: "#8696a0", precision: 0 } }
        },
        plugins: { legend: { labels: { color: "#e9edef" } } }
      }
    });
  } catch (error) {
    showError("analyticsError", error.message);
  }
}

async function loadVivaInfo() {
  hideError("vivaError");
  try {
    const data = await fetchJson("/api/viva-info");
    const metrics = data.evaluation_metrics || {};
    const percent = value => Number.isFinite(Number(value)) ? `${(Number(value) * 100).toFixed(1)}%` : "N/A";
    const container = document.getElementById("vivaMetricsContent");
    container.replaceChildren();
    const row = document.createElement("div");
    row.className = "row g-3";
    [
      ["Accuracy", metrics.accuracy],
      ["Precision", metrics.precision],
      ["Recall", metrics.recall],
      ["F1 score", metrics.f1_score]
    ].forEach(([label, value]) => {
      const column = document.createElement("div");
      column.className = "col-sm-6 col-lg-3";
      const card = document.createElement("div");
      card.className = "p-3 bg-dark border border-secondary rounded text-center";
      const heading = document.createElement("h6");
      heading.className = "text-muted small";
      heading.textContent = label;
      const metric = document.createElement("h4");
      metric.className = "text-success mb-0";
      metric.textContent = percent(value);
      card.append(heading, metric);
      column.append(card);
      row.append(column);
    });
    container.append(row);

    const crossFinding = data.cross_dataset_test?.cross_dataset_transfer_test?.key_finding;
    if (crossFinding) {
      const finding = document.createElement("p");
      finding.className = "mt-3 mb-0 small text-muted";
      finding.textContent = crossFinding;
      container.append(finding);
    }
    const limitations = document.getElementById("limitationsList");
    limitations.replaceChildren();
    (data.limitations || []).forEach(text => {
      const item = document.createElement("li");
      item.textContent = text;
      limitations.append(item);
    });
  } catch (error) {
    showError("vivaError", error.message);
  }
}

async function loadWhatsAppStatus() {
  const statusBox = document.getElementById("whatsappStatus");
  try {
    const status = await fetchJson("/api/whatsapp-status");
    const missing = [];
    if (!status.verify_token_configured) missing.push("META_VERIFY_TOKEN");
    if (!status.app_secret_configured) missing.push("META_APP_SECRET");
    if (!status.access_token_configured) missing.push("META_WHATSAPP_TOKEN");
    if (!status.phone_number_id_configured) missing.push("META_PHONE_NUMBER_ID");
    if (status.live_messaging_ready) {
      statusBox.textContent = `Meta credentials are configured. Register your public HTTPS URL + ${status.webhook_path} in Meta and subscribe to WhatsApp messages.`;
      statusBox.className = "alert alert-success small";
      document.getElementById("botStatus").textContent = "Meta configured";
    } else {
      statusBox.textContent = `Local demo is ready. Live WhatsApp needs Meta setup and these environment variables: ${missing.join(", ")}.`;
      statusBox.className = "alert alert-warning small";
      document.getElementById("botStatus").textContent = "Local demo";
    }
  } catch (error) {
    statusBox.textContent = `Could not check Meta setup: ${error.message}`;
    statusBox.className = "alert alert-danger small";
  }
}

async function loadFactCheckApiStatus() {
  const statusBox = document.getElementById("factCheckApiStatus");
  try {
    const status = await fetchJson("/api/integrations-status");
    statusBox.textContent =
      `Bing web search requires no API key. ${status.local_fact_check_records} local published fact-check records are available. ` +
      `${status.local_model_provider} (${status.local_model}): ${status.local_model_message} ` +
      `Image-origin checks (${status.image_origin_model}): ${status.image_origin_model_message}`;
    statusBox.className = status.local_model_available && status.image_origin_model_available
      ? "alert alert-info mt-3 small"
      : "alert alert-warning mt-3 small";
  } catch (error) {
    statusBox.textContent = `Could not check external fact-check service: ${error.message}`;
    statusBox.className = "alert alert-danger mt-3 small";
  }
}

document.getElementById("verifyForm").addEventListener("submit", submitVerification);
document.getElementById("verifyNavButton").addEventListener("click", () => {
  bootstrap.Tab.getOrCreateInstance(
    document.getElementById("dashboard-tab")
  ).show();
  document.getElementById("verifyForm").scrollIntoView({
    behavior: "smooth",
    block: "center"
  });
  document.getElementById("claimInput").focus({ preventScroll: true });
});
document.querySelectorAll("[data-input-mode]").forEach(button => {
  button.addEventListener("click", () => setInputMode(button.dataset.inputMode));
});
document.getElementById("claimInput").addEventListener("input", event => {
  document.getElementById("claimCharacterCount").textContent = event.target.value.length;
});
document.getElementById("simSendBtn").addEventListener("click", sendSimulatedMsg);
document.getElementById("simInput").addEventListener("keydown", event => {
  if (event.key === "Enter") sendSimulatedMsg();
});
document.getElementById("dbSearchInput").addEventListener("input", filterFactChecks);
document.getElementById("dbCatFilter").addEventListener("change", filterFactChecks);
document.getElementById("savedDbSearchInput").addEventListener("input", loadSavedVerifications);
document.getElementById("benchmarkSearchForm").addEventListener("submit", searchBenchmark);
document.getElementById("adminLoginForm").addEventListener("submit", submitAdminLogin);
document.getElementById("adminLogoutButton").addEventListener("click", logoutAdmin);
document.getElementById("editVerificationForm").addEventListener("submit", submitVerificationEdit);
document.getElementById("refreshHistoryButton").addEventListener("click", loadSavedVerifications);
document.querySelectorAll('#mainTab button[data-bs-toggle="tab"]').forEach(button => {
  button.addEventListener("shown.bs.tab", event => {
    if (event.target.id === "history-tab") loadSavedVerifications();
    if (event.target.id === "db-tab") {
      loadSavedVerifications();
      loadFactChecks();
    }
    if (event.target.id === "analytics-tab") loadAnalytics();
    if (event.target.id === "viva-tab") loadVivaInfo();
  });
});
loadCurrentSession().then(refreshDashboardData);
loadWhatsAppStatus();
loadFactCheckApiStatus();
