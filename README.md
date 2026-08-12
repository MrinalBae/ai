# 🤖 Image AI Telegram Bot

A professional Telegram image-processing bot powered by the official Pixelcut API.

The bot provides **Background Removal, Image Upscaling and AI Image Expansion** through a clean, mobile-friendly Telegram interface.

Built with Python, FastAPI, python-telegram-bot and MongoDB persistence.

---

## ✨ Features

- 🪄 Remove Background
- 🔍 Upscale images to 2× or 4×
- 🖼️ AI Image Expand
- 📱 Professional mobile-friendly Telegram UI
- 🗂️ JPG / JPEG / PNG support
- 📁 Results returned as downloadable image documents
- 🔑 Multiple Pixelcut API keys
- 🔄 API rotation / failover
- 🗄️ MongoDB persistent settings
- 🔐 API-key encryption and privacy controls
- 👤 User settings via `/us`
- 🛠️ Admin settings via `/bs`
- 🏷️ Custom result filename prefix/suffix
- 🖼️ Optional result thumbnails

---

## ⚙️ Bot Commands

### `/start`

Starts the bot and asks:

> Send your image/document

After an image is uploaded:

```text
┌────────────┬────────────┬────────────┐
│ REMOVE BG  │   UPSCALE  │   EXPAND   │
└────────────┴────────────┴────────────┘
```

Settings are intentionally not shown in `/start`.

### `/us`

Opens user settings.

Users can manage available personal options such as:

- Output format
- Filename prefix
- Filename suffix
- Thumbnail preference
- Result naming
- Other personal processing preferences

User settings are stored in MongoDB.

### `/bs`

Admin-only bot settings.

The admin panel can manage:

- Pixelcut APIs
- Add / enable / disable / delete API
- API priority and rotation
- Privacy
- API-key visibility
- Encryption
- Filename settings
- Thumbnail settings
- Processing configuration
- Other configurable bot options

---

# 🔍 Upscale

The bot supports:

- **2×**
- **4×**

Workflow:

```text
Send Image
    ↓
UPSCALE
    ↓
2× or 4×
    ↓
Pixelcut API
    ↓
JPG/PNG Result
```

---

# 🪄 Remove Background

Workflow:

```text
Send Image
    ↓
REMOVE BG
    ↓
Pixelcut Background Removal
    ↓
2× or 4×
    ↓
JPG/PNG Result
```

---

# 🖼️ AI Expand

### Preset ratios

- **1:1**
- **4:3**
- **4:5**
- **9:16**
- **16:9**
- **2.39:1**
- **A4**
- **Letter**
- **Custom**

### Custom dimensions

Select:

```text
Custom
   ↓
Width
   ↓
Height
```

Example:

```text
1920 × 1080
```

### Expand direction

The bot allows the required expansion side to be selected before processing.

Depending on the configured Pixelcut capabilities:

- Top
- Bottom
- Left
- Right
- Horizontal
- Vertical
- All sides

After expansion, the bot asks for:

- **2×**
- **4×**

---

# 🔑 Multiple Pixelcut API Keys

There is **no fixed 10-key limit**.

The administrator can add as many API keys as required by the application.

Example:

```text
Pixelcut APIs

API 1   ✅ Enabled
API 2   ✅ Enabled
API 3   ✅ Enabled
API 4   ❌ Disabled
API 5   ✅ Enabled
...
```

Each API can be:

- Added
- Enabled
- Disabled
- Deleted
- Prioritized
- Used for rotation/failover

If one enabled API fails because of authentication, rate limiting or service failure, another available API can be attempted according to the configured rotation strategy.

---

# 🔐 Privacy & Encryption

Pixelcut API keys are sensitive credentials.

They must never be:

- Hardcoded in source code
- Exposed to normal users
- Sent to Telegram users
- Written to logs
- Committed to GitHub

The admin settings include privacy and encryption controls.

When encryption is enabled, API keys are not displayed in plain text in the Telegram admin interface.

---

# 🗄️ MongoDB Persistence

MongoDB provides persistent storage for configuration and user settings.

Settings survive:

- Bot restart
- Render restart
- Process restart
- Redeployment

Stored information can include:

- User settings
- Admin settings
- Pixelcut API configurations
- API status
- API priority
- Privacy settings
- Encryption settings
- Filename settings
- Thumbnail settings
- Processing preferences

---

# 🖼️ Result Files

Results are returned as downloadable:

- JPG
- PNG

### Filename customization

Example:

```text
Prefix: upscaled_
Original: photo.jpg
Suffix: _4x
```

Result:

```text
upscaled_photo_4x.jpg
```

The upscale level can optionally be included automatically:

```text
photo_2x.jpg
photo_4x.jpg
```

Result thumbnails can also be enabled/disabled through settings.

---

# 🧩 Architecture

```text
Telegram User
      │
      ▼
Telegram Bot API
      │
      ▼
Python Application
      │
 ┌────┴─────────────┐
 │                  │
 ▼                  ▼
MongoDB          Pixelcut API
 │                  │
 ▼          ┌───────┼────────┐
Settings    ▼       ▼        ▼
         Upscale  Remove BG  Expand
```

---

# 🌐 FastAPI Web Service

The application includes a lightweight FastAPI service.

Available endpoints:

```text
GET /
GET /api/healthz
GET /api/docs
GET /api/openapi.json
```

Temporary processed-media delivery may also be provided when required by the Telegram workflow.

---

# 🚀 Deployment

Production server:

```bash
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

The service listens on:

```text
0.0.0.0
```

and uses the platform-provided `PORT` environment variable.

---

# ☁️ Render

The project is designed to run as a Render Web Service.

Start command:

```bash
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

No frontend build is required.

---

# 🛠️ Technology Stack

- Python
- FastAPI
- Uvicorn
- python-telegram-bot
- MongoDB
- Motor / async MongoDB driver
- Jinja2
- HTML
- CSS
- Vanilla JavaScript
- Official Pixelcut API

---

# 🚫 No Frontend Build System

This project does **not** use:

- React
- Vite
- Node.js
- npm
- pnpm
- TypeScript frontend
- Webpack
- Separate frontend deployment
- Frontend build commands

There is no:

```text
npm install
npm run build
pnpm build
vite build
```

requirement.

---

# 📂 Project Structure

The project uses a modular Python architecture.

Example:

```text
app/
├── main.py
├── config.py
├── database.py
├── pixelcut.py
├── telegram.py
├── keyboards.py
├── start.py
│
├── handlers/
│   ├── image.py
│   ├── upscale.py
│   ├── remove_bg.py
│   ├── expand.py
│   ├── user_settings.py
│   └── admin.py
│
├── templates/
│   └── index.html
│
└── static/
    ├── style.css
    └── app.js
```

The exact structure may evolve as features are added.

---

# 🔑 Environment Variables

Sensitive credentials must be provided through the deployment platform's secret/environment-variable system.

Typical configuration:

```text
TELEGRAM_BOT_TOKEN
MONGODB_URI
PIXELCUT_API_KEY
ADMIN_ID
PORT
```

Additional variables may be required by the deployment configuration.

**Never commit real credentials to GitHub.**

---

# 🧪 Testing

Before production deployment, verify:

### FastAPI

```text
GET /
GET /api/healthz
GET /api/docs
GET /api/openapi.json
```

### Telegram

```text
/start
/us
/bs
```

### Image Processing

- JPG
- JPEG
- PNG
- Remove Background
- 2× Upscale
- 4× Upscale
- Expand
- Preset ratios
- 2.39:1
- Custom dimensions
- Expand direction
- Result download

### Settings

- User settings persistence
- Admin settings persistence
- API add
- API enable
- API disable
- API delete
- Multiple API rotation
- Encryption
- Privacy
- Filename prefix
- Filename suffix
- Thumbnail settings

---

# ⚠️ Pixelcut API Usage

Image processing depends on the availability and limits of the configured Pixelcut API account(s).

Usage may be subject to:

- Account limits
- Rate limits
- API availability
- Pricing
- Service restrictions

The bot does not guarantee unlimited Pixelcut processing.

---

# 🛡️ Privacy

Users should avoid uploading confidential or sensitive images unless they understand the processing and retention policies of the services involved.

The application is designed to minimize permanent image storage. Uploaded images necessarily pass through the configured image-processing service when processing is requested.

---

# 📄 License

This project is intended for personal or authorized use.

Review and replace this section with the appropriate license before distributing the project publicly.

---

## ⭐ Project

**Image AI Telegram Bot**

Professional Telegram image processing with:

**Remove Background • Upscale • Expand**

Powered by Python, MongoDB and the official Pixelcut API.
