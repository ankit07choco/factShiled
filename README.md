# FactShield AI:  Misinformation Claim Verification System

FactShield AI is an end-to-end multi-signal claim verification system and web platform specifically engineered to detect and debunk viral  misinformation forwards.

Unlike traditional academic models that treat misinformation as a simple binary text classification problem, FactShield uses a **claim verification pipeline** combining fact-check retrieval, semantic search, linguistic style heuristics, and source attribution.

---

## 🏛️ System Architecture

```
WhatsApp user → Meta WhatsApp Cloud API → FastAPI Webhook
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
> 5. **Article links:** Link mode fetches readable text from a public HTTP/HTTPS article page, extracts a central factual claim, and checks it against the local fact-check index and web search. The verdict applies to that claim, not the whole article; claims that lack independent corroboration remain Unverified. Private/local addresses, non-HTML pages, and pages over 2 MB are rejected. Some publishers block automated access; when that happens, paste the article text in Text mode or try a publicly accessible link. The submitted article is not treated as independent evidence for itself.
> 6. **Source links:** Displays fact-check and web-search citations; it does not independently verify domain authority or corroborate every URL.
>
> The UI exposes signal weights for explanation, but verdicts are currently rule-based: a sufficiently relevant retrieved review supplies the True/False rating; without one the result is Unverified. The confidence number is a heuristic, not a calibrated probability.

---

## 🚀 Quickstart & Setup

### Requirements

**Backend**
- Python 3.10 or newer and pip.
- Ollama running on the same host as FactShield, or at a private network address reachable by it.
- About 5.7 GB of disk space for the default text (`qwen3:4b`) and vision (`qwen2.5vl:3b`) models. Allow additional space for the operating system and project. A VPS with at least 16 GB RAM and 30 GB disk is recommended; CPU-only inference works but can be slow.
- Tesseract OCR is optional. Without it, image-origin assessment still works, but OCR of text inside images is unavailable.

**Mobile development/builds**
- Node.js and npm.
- Android builds additionally require Android Studio/SDK and the Java version required by the Expo/Gradle toolchain.
- iOS builds require macOS, Xcode, and Apple signing configuration.

The website UI is served directly by FastAPI; there is no separate Node server or frontend build for the website.

### Install Python dependencies

macOS/Linux:
```sh
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
```

For development and tests, install the development requirements instead:
```sh
.venv/bin/pip install -r requirements-dev.txt
```

Windows PowerShell:
```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\pip.exe install -r requirements-dev.txt
```

### Optional: install Tesseract OCR

macOS:
```sh
brew install tesseract
```

Ubuntu/Debian:
```sh
sudo apt update
sudo apt install -y tesseract-ocr
```

Windows: install Tesseract (for example, with `winget install --id UB-Mannheim.TesseractOCR -e`) and ensure `tesseract.exe` is on `PATH`. Otherwise set `TESSERACT_CMD` in `.env` to its full path. The Python `pytesseract` package is installed with the project requirements; the separate Tesseract executable is optional.

### Configure Ollama and environment

Install Ollama from [ollama.com/download](https://ollama.com/download), start its service, then download the default models:
```sh
ollama pull qwen3:4b
ollama pull qwen2.5vl:3b
```

If you do not already have a `.env` file, copy `.env.example` to `.env` and adjust settings as needed. Do not overwrite an existing `.env`, commit it, or share its contents. `.env` is ignored by Git.

| Variable | Default | Purpose |
|---|---|---|
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama server URL; use a private address if Ollama is on another host |
| `OLLAMA_MODEL` | `qwen3:4b` | Local text-verification model |
| `OLLAMA_VISION_MODEL` | `qwen2.5vl:3b` | Local experimental image-origin model |
| `TESSERACT_CMD` | blank | Optional full path to the Tesseract executable |
| `HOST` | `127.0.0.1` | Host used by `run.py` for local development |
| `PORT` | `8000` | Port used by `run.py` |
| `FACTSHIELD_DATABASE_PATH` | `data/factshield_verifications.sqlite3` | SQLite file for saved conclusive verification results |
| `FACTSHIELD_ADMIN_USERNAME` | blank | Admin username; admin login stays disabled unless all three admin settings are configured |
| `FACTSHIELD_ADMIN_PASSWORD` | blank | Strong, unique admin password; do not commit it |
| `FACTSHIELD_SESSION_SECRET` | blank | Random secret used to sign admin session cookies |
| `FACTSHIELD_SESSION_COOKIE_SECURE` | `false` | Set to `true` behind HTTPS in production |
| `META_VERIFY_TOKEN` | blank | Optional Meta webhook verification token |
| `META_APP_SECRET` | blank | Optional Meta webhook signature verification secret |
| `META_WHATSAPP_TOKEN` | blank | Optional WhatsApp Cloud API access token |
| `META_PHONE_NUMBER_ID` | blank | Optional WhatsApp Cloud API phone number ID |
| `META_GRAPH_API_VERSION` | `v26.0` | Optional Meta Graph API version |

No search or AI API key is required for the local Ollama/Bing/Wikipedia flow.

### Run the website and API locally

macOS/Linux:
```sh
.venv/bin/python run.py
```

Windows PowerShell:
```powershell
.\.venv\Scripts\python.exe run.py
```

Open **http://127.0.0.1:8000**. The development server uses auto-reload and binds to localhost by default.

Check model readiness at **http://127.0.0.1:8000/api/integrations-status**. It reports whether both local Ollama models are installed. FastAPI's interactive API documentation is available at **http://127.0.0.1:8000/docs**.

### User and admin roles; automatic database updates

- **User:** Every visitor is automatically treated as an anonymous user. No credentials or account setup are needed to verify claims or browse saved records.
- **Admin:** Admin sign-in is available only after setting `FACTSHIELD_ADMIN_USERNAME`, a unique `FACTSHIELD_ADMIN_PASSWORD` of at least 12 characters, and a random `FACTSHIELD_SESSION_SECRET` of at least 32 characters in `.env`, then restarting the server. Generate a session secret with `python3 -c "import secrets; print(secrets.token_urlsafe(48))"`. There is no built-in/default admin password. The admin can verify claims through the same form and edit or delete saved database records.
- **Automatic saving:** Only `Likely True` and `Likely False` claim results are saved. `Unverified` and `Disputed` results are not. Rechecking an equivalent claim updates the existing SQLite record and increments its check count instead of creating duplicates.
- **Privacy:** Saved claims, verdicts, explanations, confidence values, and source links are shared with site visitors. Original image files are not stored, but claim text extracted from an image may be saved if its verdict is conclusive. Do not submit private or sensitive material.
- **Database file:** The app creates `data/factshield_verifications.sqlite3` on first use. It is local and Git-ignored. Back it up with the rest of the app data; do not delete the file if you want to keep saved results.

### Run tests

Install `requirements-dev.txt`, then run:
```sh
.venv/bin/python -m pytest -q
```

On Windows:
```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

## 📱 Android and iOS app

The website remains available at the same address. The Expo app in `mobile/` lets users paste text, pick an image, or share text/images to FactShield from another app. It sends inputs to the existing `POST /api/verify` endpoint and displays the claim verdict, the separate experimental image-origin estimate, explanations, and sources. Image analysis runs on the backend, so the phone must be able to reach the FactShield server.

Install dependencies and start Expo:
```sh
cd mobile
npm ci
npm start
```

For development, a `127.0.0.1` address on a phone points to the phone itself, not the computer running FactShield. Deploy the backend to an HTTPS host or use a trusted HTTPS tunnel, then enter that server's base address in the app under **Connect your server**. The address is saved on the device. `EXPO_PUBLIC_API_URL` in `mobile/.env` can set an initial server address, but the in-app setting can be changed without rebuilding. It is a public server address, not a place for credentials.

To install a native development build on a connected Android device or emulator:
```sh
cd mobile
export ANDROID_HOME="$HOME/Library/Android/sdk"
export ANDROID_SDK_ROOT="$ANDROID_HOME"
npx expo run:android
```

To build the Android APK that the website serves:
```sh
cd mobile
npx expo prebuild --platform android
export ANDROID_HOME="$HOME/Library/Android/sdk"
export ANDROID_SDK_ROOT="$ANDROID_HOME"
cd android
./gradlew :app:assembleRelease
cd ../..
cp mobile/android/app/build/outputs/apk/release/app-release.apk \
  app/static/downloads/factshield-android.apk
```

The website serves the APK from `/downloads/android`. Android may ask users to allow installing apps from their browser. The current downloadable build is signed with a development key for testing; use your own protected release key before Play Store or production distribution. Increase `android.versionCode` in `mobile/app.json` for each Android update.

For iPhone, use macOS with the full Xcode installation and a configured signing team:
```sh
cd mobile
npm ci
npx expo run:ios
```

Sharing from other apps requires a native build; Expo Go does not include the share extension. Local iOS builds and device distribution require Apple's signing setup. An iPhone release build has not been produced by this project yet.

## 📲 Connect a real WhatsApp bot

FactShield connects directly to the Meta WhatsApp Cloud API, with no Twilio intermediary fee. A local `127.0.0.1` address cannot receive Meta webhooks; expose the app through a public HTTPS tunnel or deploy it.

Set these environment variables in the untracked local `.env` file:

| Variable | Description |
|---|---|
| `META_VERIFY_TOKEN` | A private string you choose and also enter in Meta's webhook setup |
| `META_APP_SECRET` | App Secret from the Meta developer dashboard; verifies webhook signatures |
| `META_WHATSAPP_TOKEN` | WhatsApp Cloud API access token |
| `META_PHONE_NUMBER_ID` | Phone Number ID from the WhatsApp API setup |
| `META_GRAPH_API_VERSION` | Optional Graph API version, defaults to `v26.0` |

In the Meta developer dashboard, create an app with the WhatsApp product and configure the callback URL as `https://YOUR_PUBLIC_HOST/webhook/whatsapp`. Enter the same `META_VERIFY_TOKEN` in Meta, verify the webhook, and subscribe to `messages`. Restart FactShield after changing `.env`. Use the test phone number and test recipient provided by Meta to begin. For longer-term use, configure a suitable access token and an approved business sender. Keep all credentials private.

Meta's current pricing includes 1,000 free service messages per business phone number each month; charges can apply above that and for other message categories, depending on recipient country. User-to-business messages are not charged by Meta. Check [Meta's current WhatsApp pricing](https://developers.facebook.com/documentation/business-messaging/whatsapp/pricing) before production use. Local simulator use is free and does not send real WhatsApp messages.

For a production server, use the VPS guide below. Bind Uvicorn to `127.0.0.1` behind an HTTPS reverse proxy; do not expose the development server or Ollama directly to the internet.

Image OCR requires Tesseract to be installed on the server. Published fact-check matches skip web search and model inference for faster responses. New claims still require public search and local-model assessment and can take longer. The displayed evaluation metrics are from the supplied evaluation data and should not be treated as a guarantee for new claims.

## 🌐 Enable no-key web search and local verdicts

The verifier searches public Bing result pages, with Wikipedia's no-key search endpoint as a fallback, and runs its assessment locally using Ollama. Neither step requires an API key. Public search pages are not a stable search API and may throttle or change their markup. Search results are presented as evidence, not as guaranteed authoritative findings.

1. Install [Ollama](https://ollama.com/download) and start the Ollama application/server.
2. Download the default local model (about 2.5 GB):
   ```sh
   ollama pull qwen3:4b
   ```
3. Pull the local vision model (about 3.2 GB) for experimental AI-image-origin assessments:
   ```sh
   ollama pull qwen2.5vl:3b
   ```
4. Copy `.env.example` to `.env` if needed. The defaults are `OLLAMA_BASE_URL=http://localhost:11434`, `OLLAMA_MODEL=qwen3:4b`, and `OLLAMA_VISION_MODEL=qwen2.5vl:3b`. You can set `OLLAMA_VISION_MODEL` to another locally installed Ollama vision model.
5. Restart FactShield and check `GET /api/integrations-status`; it reports whether both local models are installed and responding.

When a relevant local published fact-check matches, it takes precedence. Otherwise, FactShield searches Bing, falls back to Wikipedia when Bing has no relevant result, and sends the result titles/snippets to Ollama running on the same machine. Uploaded images are also sent to the local vision model for a separate, experimental image-origin estimate. Images are not sent to a cloud AI service by this pipeline. Visual AI-image detection is unreliable and cannot prove authenticity; editing, compression, and new generators can change visible clues. Search results can also be incomplete or irrelevant, so verify important claims independently.

## ☁️ Host FactShield online

The simplest always-on setup is one Ubuntu VPS running FastAPI and Ollama, with a domain and HTTPS reverse proxy in front. A static host alone (for example, GitHub Pages) cannot run the Python API or Ollama. The current temporary `trycloudflare.com` tunnel is useful for testing but depends on your computer and tunnel process staying online; it is not permanent hosting.

### Server requirements

- Ubuntu 22.04/24.04 or another supported Linux server.
- Recommended: 4 or more CPU cores, 16 GB RAM, and at least 30 GB free disk. The two default models occupy about 5.7 GB; model execution needs additional memory and disk. CPU-only inference works but can be slow; a compatible GPU can improve response time.
- A domain name with an A/AAAA DNS record pointing to the server.
- Public inbound ports **80/443** for the HTTPS proxy and **22** for SSH. Do not open ports **8000** or **11434** publicly.

On Ubuntu with UFW, allow SSH before enabling the firewall, then allow only SSH and the HTTPS proxy. Apply equivalent rules in your VPS provider's firewall:
```sh
sudo apt install -y ufw
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
sudo ufw status
```

### Deploy on one VPS

1. Push or transfer the latest FactShield code to the server. Do not upload or commit `.env` through Git. For a private repository, use an SSH deploy key or another secure Git credential method.
2. Install the system packages and Python dependencies:
   ```sh
   sudo apt update
   sudo apt install -y git python3 python3-venv python3-pip tesseract-ocr
   # Clone/copy the repository into /opt/factshield, then:
   cd /opt/factshield
   python3 -m venv .venv
   .venv/bin/pip install --upgrade pip
   .venv/bin/pip install -r requirements.txt
   ```
   Tesseract is optional; omit it if OCR is not required.
3. Install Ollama using its [official Linux instructions](https://ollama.com/download/linux), enable/start its service, then download both models:
   ```sh
   sudo systemctl enable --now ollama
   ollama pull qwen3:4b
   ollama pull qwen2.5vl:3b
   ```
   Keep Ollama bound to localhost. The application defaults to `http://localhost:11434`; if Ollama runs on another machine, use only a private network address and firewall it to the application server.
4. Create `/opt/factshield/.env` on the server from `.env.example` only if no `.env` exists (from the project directory, run `[ -f .env ] || cp .env.example .env`), then configure the model settings and any optional WhatsApp credentials. Set `FACTSHIELD_ADMIN_USERNAME`, a strong unique `FACTSHIELD_ADMIN_PASSWORD`, a generated `FACTSHIELD_SESSION_SECRET`, and `FACTSHIELD_SESSION_COOKIE_SECURE=true` for the HTTPS site. Restrict `.env` permissions (`chmod 600 .env`). Never paste secrets into the README or a public issue.
5. Run FactShield as a system service so it restarts automatically. For example, create `/etc/systemd/system/factshield.service` with `sudo nano /etc/systemd/system/factshield.service` (change `ubuntu` to the Linux account that owns the project):
   ```ini
   [Unit]
   Description=FactShield API
   After=network-online.target ollama.service
   Wants=network-online.target

   [Service]
   Type=simple
   User=ubuntu
   WorkingDirectory=/opt/factshield
   ExecStart=/opt/factshield/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
   UMask=0077
   Restart=always
   RestartSec=5

   [Install]
   WantedBy=multi-user.target
   ```
   The app loads `/opt/factshield/.env`. Ensure the service account can read it and the application files.
   ```sh
   sudo systemctl daemon-reload
   sudo systemctl enable --now factshield
   sudo systemctl status factshield
   ```
   To inspect service logs, use `sudo journalctl -u factshield -f`; Ollama logs are available with `sudo journalctl -u ollama -f`.
6. Install [Caddy](https://caddyserver.com/docs/install) and point your domain to the VPS. Add a Caddy site (replace the hostname):
   ```caddyfile
   factshield.example.com {
       reverse_proxy 127.0.0.1:8000
   }
   ```
   Put this in `/etc/caddy/Caddyfile`, then run `sudo systemctl reload caddy`. Caddy obtains and renews the HTTPS certificate when DNS and ports 80/443 are configured correctly. Keep the firewall closed to ports 8000 and 11434.
7. Verify `https://factshield.example.com/` and `https://factshield.example.com/api/integrations-status`. Both text and vision models should report as available. The website APK link is `https://factshield.example.com/downloads/android`.
8. In the mobile app, open **Connect your server** and save `https://factshield.example.com`. If using WhatsApp, set the Meta callback URL to `https://factshield.example.com/webhook/whatsapp`.

The server stores the project files and any optional local benchmark data on its disk. Back up files you need to preserve when replacing the server. If deploying from Git, include the APK at `app/static/downloads/factshield-android.apk` if you want the website's Android download route to work.

### Public deployment security

Verification and read-only database routes are intentionally available to anonymous users; admin-only database edits and deletes require an authenticated admin session and CSRF token. There is no application-level rate limiting, so anyone who can reach the site may submit text/images and consume server/model resources. Add reverse-proxy rate limiting, monitor usage, and keep dependencies updated before public launch. The API limits image uploads to 16 MB, but this alone does not prevent abuse. Do not expose Ollama's API, `.env`, or an unauthenticated development server to the internet. FastAPI's `/docs` is enabled by default; restrict or disable it for a public production deployment if it should not be exposed.

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

2. **Image Forward Analysis:**
   - Extracts text from image forwards and provides an experimental local-model estimate of possible AI generation.

3. **WhatsApp Chatbot & Webhook:**
   - Interactive live chat mockup mimicking a smartphone interface.
   - Meta WhatsApp Cloud API webhook for incoming text and image messages (`/webhook/whatsapp`).
   - Local simulator remains available for testing without a WhatsApp account.

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

- `GET /`: Website dashboard and simulator.
- `GET /docs`: FastAPI interactive API documentation.
- `GET /api/integrations-status`: Availability of the local text and vision models.
- `POST /api/verify`: Multipart form with optional `text`, `image`, and `input_mode` fields. Set `input_mode=link` to extract and verify a public HTTP/HTTPS article URL pasted in `text`; private/local addresses, non-HTML pages, and pages over 2 MB are rejected. Image uploads are limited to 16 MB. An image response includes an `image_origin` result separate from the text-claim verdict; an image without readable text can still receive an image-origin assessment. Conclusive `Likely True` / `Likely False` claim results are automatically upserted into SQLite; uploaded image bytes are not retained.
- `GET /api/session`: Returns the current role (`user` by default; `admin` after sign-in).
- `POST /api/admin/login`, `POST /api/admin/logout`: Admin session sign-in and sign-out.
- `GET /api/verifications`: Search/list saved conclusive verification records; available to guests.
- `PUT /api/verifications/{id}`, `DELETE /api/verifications/{id}`: Edit or delete a saved record; admin session and CSRF token required.
- `GET /downloads/android`: Downloads the APK if it exists at `app/static/downloads/factshield-android.apk`.
- `GET /api/fact-checks`: Search and filter indexed published fact-checks.
- `GET /api/analytics`: Evaluation metrics and saved-verification counts.
- `GET /api/viva-info`: Project metrics and limitations.
- `GET /webhook/whatsapp`: Meta Cloud API handshake verification.
- `POST /webhook/whatsapp`: Meta Cloud API incoming-message handler and local simulator.

Example image request:
```sh
curl -F 'image=@/path/to/image.jpg' https://factshield.example.com/api/verify
```

The separate `image_origin` object reports a status, model name, a verdict (`Likely AI-generated`, `Likely not AI-generated`, or `Inconclusive`), explanation, and disclaimer. This is a visual model estimate, not forensic proof or a calibrated probability. Images are processed by the configured Ollama vision model on the backend host.

## 🧰 Troubleshooting

- **Text model unavailable:** Start Ollama and run `ollama pull qwen3:4b`. Check `GET /api/integrations-status`.
- **Image-origin status says the model is missing:** Run `ollama pull qwen2.5vl:3b`, then refresh the status endpoint. The app returns `Inconclusive` with setup guidance when the vision model cannot be used.
- **Image OCR does not return text:** Install the Tesseract executable and ensure it is on `PATH`, or set `TESSERACT_CMD` to its full path. The image-origin estimate does not depend on OCR.
- **A phone cannot reach FactShield:** Do not use `127.0.0.1` in the phone app; use the backend's public HTTPS domain. Keep the backend and Ollama running.
- **The `/downloads/android` route returns 404:** Add/build the APK at `app/static/downloads/factshield-android.apk` and redeploy.
- **Model responses are slow:** CPU-only local inference may take time. Use a server with more memory/compute, or a supported GPU. Do not expose Ollama publicly to make it faster.
- **An image is labeled Inconclusive:** This is expected when visual evidence is insufficient. Editing, resizing, compression, screenshots, and new generators can alter or remove visual clues; do not treat an AI-image estimate as proof.

## 🧪 Validation commands

Backend tests:
```sh
.venv/bin/python -m pytest -q
```

Mobile app checks:
```sh
cd mobile
npm ci
npm run lint
npm run typecheck
```
