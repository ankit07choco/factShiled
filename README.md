# FactShield AI: WhatsApp Misinformation Claim Verification System

FactShield AI is an end-to-end multi-signal claim verification system and web platform specifically engineered to detect and debunk viral WhatsApp misinformation forwards.

Unlike traditional academic models that treat misinformation as a simple binary text classification problem, FactShield uses a **claim verification pipeline** combining fact-check retrieval, semantic search, linguistic style heuristics, and source attribution.

---

## 🏛️ System Architecture

```
WhatsApp user → Meta Cloud API → FastAPI Webhook
                                     ↓
            Preprocess (language detect, OCR if image, URL extraction)
                                     ↓
        Claim extraction (pick checkable proposition(s))
                                     ↓
   ┌──────────────┬────────────────────┬──────────────────┐
   Local fact-check Web search          Semantic search      Style classifier
   (published       (Bing page,         (TF-IDF over         (Sensationalism,
   reviews)         cited AI assessment) fact-check DB)      ALL CAPS, urgency)
   └──────────────┴────────────────────┴──────────────────┘
                                     ↓
              Scoring Engine → Verdict + Explanation + Sources
                                     ↓
                      WhatsApp Reply (+ Dashboard Log)
```

---

## 🔑 Core Design Decision (Viva Defense)

> **Why not make a classifier the centerpiece?**
> A model trained purely on LIAR or ISOT learns *writing style*, not *factual truth*. Such models collapse when tested on real WhatsApp forwards which frequently combine sensational headings with real news, or colloquial Indian languages (Hinglish, Bengali, Tamil).
>
> In FactShield AI:
> 1. **Fact-check retrieval:** Looks for relevant published fact-check records in the bundled local database.
> 2. **Local text search:** TF-IDF similarity over the small bundled fact-check database (not a general web or knowledge search).
> 3. **Web search:** Fetches public Bing search results without an API key; a local Ollama model assesses the snippets and returns linked sources when no local fact-check matches. This is not an independent fact-check or a guarantee of truth.
> 4. **Style heuristics/classifier:** Flags ALL CAPS, urgency keywords, forwarding pressure, and sensational wording; style alone does not establish truth.
> 5. **Source links:** Displays fact-check and web-search citations; it does not independently verify domain authority or corroborate every URL.
>
> The UI exposes signal weights for explanation, but verdicts are currently rule-based: a sufficiently relevant retrieved review supplies the True/False rating; without one the result is Unverified. The confidence number is a heuristic, not a calibrated probability.

---

## 🚀 Quickstart & Setup

### 1. Prerequisites
- Python 3.10+
- FFmpeg for video frame extraction (optional)
- Tesseract OCR for text extraction from images/video frames (optional)

### 2. Installation
On macOS, install the optional media tools with Homebrew:
```sh
brew install ffmpeg tesseract
```

Create and activate a virtual environment, then install the project dependencies:
```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
```

On Windows PowerShell, use:
```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
```

On Windows, install Tesseract OCR (for example, with `winget install --id UB-Mannheim.TesseractOCR -e`) and FFmpeg, then ensure their executables are on `PATH`. If either tool is not on `PATH`, set its executable path in the project's `.env` file:
```dotenv
TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe
FFMPEG_PATH=C:\path\to\ffmpeg.exe
```
Copy `.env.example` to `.env` to configure optional executable paths and API credentials. Leave `TESSERACT_CMD` and `FFMPEG_PATH` blank when the tools are available on `PATH`; otherwise set them to the executable paths. Do not commit `.env`.

### 3. Run tests
```sh
python -m pytest -q
```

### 4. Start the dashboard and API
```sh
python run.py
```
On macOS/Linux, if the virtual environment is not activated, use `.venv/bin/python run.py`. On Windows, use `.\.venv\Scripts\python.exe run.py`.
Open **http://127.0.0.1:8000**. The frontend is served by FastAPI; no separate Node/npm frontend server is needed.

## 📲 Connect a real WhatsApp bot

The simulator works locally without Meta credentials. Live DMs require a Meta developer app with the WhatsApp product, a WhatsApp Business phone number, a public HTTPS deployment/tunnel, and Meta's webhook subscription. A local `127.0.0.1` address cannot receive Meta webhooks.

Set these environment variables in the server's environment (do not commit credentials):

| Variable | Description |
|---|---|
| `META_VERIFY_TOKEN` | Your private token, also entered as the webhook's Verify Token in Meta |
| `META_APP_SECRET` | App Secret from the Meta developer dashboard; used to verify webhook signatures |
| `META_WHATSAPP_TOKEN` | WhatsApp Cloud API access token |
| `META_PHONE_NUMBER_ID` | Phone Number ID from the WhatsApp API setup |
| `META_GRAPH_API_VERSION` | Optional Graph API version, defaults to `v26.0` |

For local PowerShell testing, set them before starting the process:
```powershell
$env:META_VERIFY_TOKEN = "choose-a-long-random-value"
$env:META_APP_SECRET = "your-meta-app-secret"
$env:META_WHATSAPP_TOKEN = "your-whatsapp-cloud-api-token"
$env:META_PHONE_NUMBER_ID = "your-phone-number-id"
python run.py
```

Deploy the app behind HTTPS (bind to `0.0.0.0` and the hosting platform's port) and configure the callback URL as `https://YOUR_PUBLIC_HOST/webhook/whatsapp`, using the same `META_VERIFY_TOKEN`; subscribe the WhatsApp webhook to `messages`. The app downloads image/video media from Meta and replies to the sender using the Cloud API. Keep the access token private and follow WhatsApp consent, messaging-window, and template rules.

For a self-hosted server, start without the development reloader:
```powershell
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Image and video analysis requires FFmpeg and Tesseract to be installed on the server. Videos are sampled for visible on-screen text only; audio/speech transcription is not currently supported. The displayed evaluation metrics are from the supplied evaluation data and should not be treated as a guarantee for new claims.

## 🌐 Enable no-key web search and local verdicts

The verifier searches public Bing result pages, with Wikipedia's no-key search endpoint as a fallback, and runs its assessment locally using Ollama. Neither step requires an API key. Public search pages are not a stable search API and may throttle or change their markup. Search results are presented as evidence, not as guaranteed authoritative findings.

1. Install [Ollama](https://ollama.com/download) and start the Ollama application/server.
2. Download the default local model (about 2.5 GB):
   ```sh
   ollama pull qwen3:4b
   ```
3. Copy `.env.example` to `.env` if needed. The default settings are `OLLAMA_BASE_URL=http://localhost:11434` and `OLLAMA_MODEL=qwen3:4b`. You can choose another locally installed model by changing `OLLAMA_MODEL`.
4. Restart FactShield and check `GET /api/integrations-status`; it reports whether the local model is installed and responding.

When a relevant local published fact-check matches, it takes precedence. Otherwise, FactShield searches Bing, falls back to Wikipedia when Bing has no relevant result, and sends the result titles/snippets to Ollama running on the same machine. Only linked search results are shown as sources. If both searches fail or Ollama is unavailable, the result remains **Unverified** with a status message. Search results can be incomplete or irrelevant; verify important claims independently. No cloud AI or external fact-check API is called by the verification pipeline.

## 📚 Optional FEVER research benchmark

The imported FEVER v1.0 training split contains 145,449 Wikipedia-derived, human-annotated research claims (SUPPORTS, REFUTES, or NOT ENOUGH INFO). It is not a collection of published fact-check reviews and is kept in a separate SQLite database; its labels are never used for live claim verdicts.

Import it with:
```sh
.venv/bin/python scripts/import_fever_benchmark.py
```

The importer downloads the official 33 MB JSONL source and builds a local full-text-searchable SQLite database. In the Fact-Check Database tab, use the separate FEVER benchmark search to browse records and linked Wikipedia evidence pages. The generated `data/fever_benchmark.sqlite3` is local and Git-ignored. To redistribute the dataset, follow the applicable Wikipedia article licenses and FEVER's [license terms](https://fever.ai/download/fever/license.html), including attribution and share-alike requirements. Cite: Thorne et al. (2018), “FEVER: a Large-scale Dataset for Fact Extraction and VERification,” NAACL-HLT. See the [FEVER dataset](https://fever.ai/dataset/fever.html).

## 🌟 Key Features

1. **Indian-Language Support:**
   - Detects and handles Indian languages including Hindi (`hi`), Bengali (`bn`), Tamil (`ta`), Marathi (`mr`), Telugu (`te`), and English (`en`).
   - Includes multilingual ClaimReview fact-checks from BOOM Live, AltNews, Factly, and PIB Fact Check.

2. **Image Forward OCR:**
   - Detects text in viral image forwards, screenshots, and propaganda posters.

3. **WhatsApp Bot Simulator & Webhook:**
   - Interactive live chat mockup mimicking a smartphone interface.
   - Live Meta WhatsApp Cloud API JSON payload viewer (`/webhook/whatsapp`).

4. **Transparent Scoring Formula:**
   $$S_{fake} = w_{fc} \cdot S_{fc} + w_{sem} \cdot S_{sem} + w_{style} \cdot S_{style} + w_{evid} \cdot S_{evid}$$
   - **Verdict Labels:** *Likely False*, *Disputed*, *Unverified*, *Likely True*.

5. **Stated Limitations (Honest AI Principles):**
   - *"Unverified"* is a legitimate and expected output for brand-new viral claims with no existing fact-checks.
   - Automated score represents a statistical confidence estimate, not absolute truth.

---

## 📊 Evaluation & Benchmarks

| Metric | In-domain (configured data) | ISOT train/test (configured data) | ISOT/LIAR → WhatsApp transfer (configured data) |
|---|---:|---:|---:|
| **Accuracy** | 100.0% | 88.5% | 54.1% |
| **Precision** | 100.0% | 87.9% | 51.5% |
| **Recall** | 100.0% | 89.1% | 56.2% |
| **F1 Score** | 100.0% | 88.5% | 52.6% |

These values are copied from `data/evaluation_metrics.json`; the corresponding evaluation datasets and reproducible evaluation procedure are not included here. Treat them as unverified project-reported metrics, not independently validated performance claims.

---

## 🛠️ REST API Endpoints

- `GET /`: Interactive Web Dashboard & Simulator
- `POST /api/verify`: Verify claim text or image file
- `GET /api/integrations-status`: Report configured external evidence integrations
- `GET /api/fact-checks`: Search & filter indexed fact-checks
- `GET /api/analytics`: Aggregated statistical metrics
- `GET /api/viva-info`: Viva defense details, metrics, limitations
- `GET /webhook/whatsapp`: Meta Cloud API handshake verification
- `POST /webhook/whatsapp`: Meta Cloud API incoming message handler

```powershell
python -m unittest tests/test_pipeline.py
```
