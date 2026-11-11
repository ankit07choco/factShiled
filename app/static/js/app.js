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

function applyPreset(key) {
  document.getElementById("claimInput").value = PRESETS[key] || "";
}

async function fetchJson(url, options) {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || `Request failed (${response.status})`);
  }
  return data;
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
  const image = document.getElementById("imageInput").files[0];
  const video = document.getElementById("videoInput").files[0];
  const button = document.getElementById("verifyBtn");
  hideError("verifyError");

  if (!text && !image && !video) {
    showError("verifyError", "Enter a claim or attach an image or video.");
    return;
  }
  if (image && video) {
    showError("verifyError", "Upload either an image or a video, not both.");
    return;
  }

  const formData = new FormData();
  if (text) formData.append("text", text);
  if (image) formData.append("image", image);
  if (video) formData.append("video", video);

  button.disabled = true;
  button.textContent = "Analyzing...";
  try {
    const data = await fetchJson("/api/verify", { method: "POST", body: formData });
    renderVerificationResults(data);
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
  const videoResult = data.video_result;
  const notices = [];
  if (data.ocr_result?.error && data.input_text) notices.push(data.ocr_result.error);
  if (data.fact_check_lookup?.message) notices.push(data.fact_check_lookup.message);
  if (data.web_search?.message) notices.push(data.web_search.message);
  if (videoResult) {
    notices.push(videoResult.error || "Sampled on-screen text was analyzed.");
    notices.push("Video speech is not transcribed.");
  }
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
      formData.append(media.type.startsWith("video/") ? "video" : "image", media);
      if (text) formData.append("text", text);
      const result = await fetchJson("/api/verify", { method: "POST", body: formData });
      reply = result.whatsapp_reply || `${result.verdict}: ${result.explanation || "No explanation returned."}`;
      if (result.ocr_result?.error && text) reply += `\n\n⚠️ ${result.ocr_result.error}`;
      if (result.video_result?.error) reply += `\n\n${result.video_result.error}`;
      if (result.video_result) reply += "\nVideo speech is not transcribed.";
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
      document.getElementById("botStatus").textContent = "Meta credentials configured";
    } else {
      statusBox.textContent = `Local simulator is ready. Live DMs need Meta setup and these environment variables: ${missing.join(", ")}.`;
      statusBox.className = "alert alert-warning small";
      document.getElementById("botStatus").textContent = "Local simulator";
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
      `${status.local_model_provider} (${status.local_model}): ${status.local_model_message}`;
    statusBox.className = status.local_model_available
      ? "alert alert-info mt-3 small"
      : "alert alert-warning mt-3 small";
  } catch (error) {
    statusBox.textContent = `Could not check external fact-check service: ${error.message}`;
    statusBox.className = "alert alert-danger mt-3 small";
  }
}

document.getElementById("verifyForm").addEventListener("submit", submitVerification);
document.getElementById("simSendBtn").addEventListener("click", sendSimulatedMsg);
document.getElementById("simInput").addEventListener("keydown", event => {
  if (event.key === "Enter") sendSimulatedMsg();
});
document.getElementById("dbSearchInput").addEventListener("input", filterFactChecks);
document.getElementById("dbCatFilter").addEventListener("change", filterFactChecks);
document.getElementById("benchmarkSearchForm").addEventListener("submit", searchBenchmark);
document.querySelectorAll('#mainTab button[data-bs-toggle="tab"]').forEach(button => {
  button.addEventListener("shown.bs.tab", event => {
    if (event.target.id === "db-tab") loadFactChecks();
    if (event.target.id === "analytics-tab") loadAnalytics();
    if (event.target.id === "viva-tab") loadVivaInfo();
  });
});
loadWhatsAppStatus();
loadFactCheckApiStatus();
