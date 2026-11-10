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
> 1. **Fact-check DB lookup (40% weight):** Matches against verified debunking claims (ClaimReview schema).
> 2. **Semantic search (25% weight):** Vector similarity search over indexed Indian & global fact-checks.
> 3. **Linguistic style classifier (20% weight):** Flags ALL CAPS, urgency keywords, forwarding pressure ("forward to 10 groups"), and authority hijacking ("UNESCO", "NASA").
> 4. **Evidence & domain authority (15% weight):** Checks URL credibility and news corroboration.

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

On Windows, install Tesseract OCR separately, then reopen the terminal so it is on `PATH`. If it is installed outside `PATH`, set `TESSERACT_CMD` to the full path of `tesseract.exe`. Install FFmpeg and add its `bin` folder to `PATH`; `FFMPEG_PATH` can be used to point to a specific executable.

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

| Metric | In-Domain (WhatsApp) | Cross-Dataset Transfer (ISOT ➔ WhatsApp) |
|---|---|---|
| **Accuracy** | 94.2% | 54.1% (Classification alone fails) |
| **Precision** | 93.8% | 51.5% |
| **Recall** | 95.0% | 56.2% |
| **F1 Score** | 94.4% | 53.7% |

*Conclusion:* Cross-dataset drop shows that pure NLP classification without retrieval fails on real WhatsApp misinformation. Retrieval over fact-check databases is mandatory.

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
