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
   Fact-check API   Semantic search      Style classifier
   (Google Fact     (embeddings / TF-IDF (Sensationalism,
   Check Tools)     over fact-check DB)  ALL CAPS, urgency)
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
> 1. **Fact-check retrieval:** Looks for relevant local records and, when configured, published reviews from Google Fact Check Tools.
> 2. **Local text search:** TF-IDF similarity over the small bundled fact-check database (not a general web or knowledge search).
> 3. **Style heuristics/classifier:** Flags ALL CAPS, urgency keywords, forwarding pressure, and sensational wording; style alone does not establish truth.
> 4. **Source links:** Displays URLs included with matched reviews; it does not independently verify domain authority or corroborate every URL.
>
> The UI exposes signal weights for explanation, but verdicts are currently rule-based: a sufficiently relevant retrieved review supplies the True/False rating; without one the result is Unverified. The confidence number is a heuristic, not a calibrated probability.

---

## 🚀 Quickstart & Setup

### 1. Prerequisites
- Python 3.10+
- FFmpeg on `PATH` for video frame extraction
- Tesseract OCR on `PATH` for text extraction from images/video frames

### 2. Installation
```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
```

On Windows, install Tesseract OCR (for example, with `winget install --id UB-Mannheim.TesseractOCR -e`), then close and reopen the terminal. Check that it is available with:
```powershell
where.exe tesseract
tesseract --version
```
If Tesseract is installed but not on `PATH`, set its executable path in the project's `.env` file:
```dotenv
TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe
```
Alternatively, set it for the current PowerShell session before starting the app:
```powershell
$env:TESSERACT_CMD = "C:\Program Files\Tesseract-OCR\tesseract.exe"
python run.py
```
Use the actual installation path if it differs. Install FFmpeg and add its `bin` folder to `PATH`; `FFMPEG_PATH` can be used to point to a specific executable.

### 3. Run tests
```powershell
python -m unittest tests.test_pipeline
python -m pytest -q tests/test_server_endpoints.py
```

### 4. Start the dashboard and API
```powershell
python run.py
```
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

## 🌐 Enable external fact-check search

The verifier can query Google's **Fact Check Tools API** for previously published fact-checks. It does not search the entire web and cannot guarantee a result for every real-world event.

1. Create or select a project in Google Cloud, enable the Fact Check Tools API, and create an API key with access to that API.
2. Copy `.env.example` to `.env` in the project root and set your key:

   ```dotenv
   GOOGLE_FACT_CHECK_API_KEY=your-google-api-key
   ```

   The app loads `.env` automatically when it starts. Keep `.env` private; it is excluded from Git. Restart the server after changing it. Alternatively, you can still set `GOOGLE_FACT_CHECK_API_KEY` in the server's environment.

3. Check `GET /api/integrations-status` or the verifier page to confirm external lookup is enabled.

Each claim verification makes a server-side request to `claims:search`, with the detected language where available. API errors are shown in the result and local records are still checked. Google API quotas and billing/availability are controlled by your Google Cloud project. If there is no relevant published review, the correct result remains **Unverified** rather than guessing from unrelated web pages.

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
- `GET /api/fact-checks`: Search & filter indexed fact-checks
- `GET /api/analytics`: Aggregated statistical metrics
- `GET /api/viva-info`: Viva defense details, metrics, limitations
- `GET /webhook/whatsapp`: Meta Cloud API handshake verification
- `POST /webhook/whatsapp`: Meta Cloud API incoming message handler

```powershell
python -m unittest tests/test_pipeline.py
```
