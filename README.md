# Local Help Connect — v6

A professional Flask-based local service marketplace connecting customers with skilled workers.

## What's New in v6

### 1. Profile Picture Upload
- Upload photos during **registration** or via **Settings → Profile Picture**
- Avatars display in: navbar, dashboards, chat, map popups, admin panels, worker cards
- Stored in `static/uploads/avatars/` with secure filename handling
- Supported formats: JPG, PNG, WEBP, GIF (max 10 MB)

### 2. File & Image Sharing in Chat
- Attach images (jpg/png/webp/gif) and files (pdf/doc/docx/txt/zip) in the chatbox
- Images auto-preview inline with a lightbox on click
- Files display with name, size, and download button
- Uploaded via `/chat/<req_id>/upload` endpoint
- Stored in `static/uploads/chat/` with MySQL reference

### 3. Auto-Generated Request IDs
- Every job request is assigned a unique code: `REQ2026XXXX`
- Visible everywhere: My Requests, Incoming Requests, Chat header, Track page, Admin
- Used for complaint reference, tracking, and customer support

### 4. Rich Customer & Worker Dashboards
- **Customer**: 5-stat grid, recent request feed with stage bar, activity timeline, quick action shortcuts, profile card
- **Worker**: 6-stat grid, badge + availability banner, performance bars (Punctuality/Quality/Communication), incoming request cards with accept/reject inline

### 5. Fixed Leaflet Map
- Workers appear with correct lat/lng pins
- **Indigo pin** = Available · **Amber pin** = Busy
- Auto-fit zoom to all visible pins
- Popup cards show: avatar, badge, stars, skill chips, View + Hire buttons
- Fallback message if no geocoded workers found

### 6. Brand Logo & Favicon
- Custom SVG logo in navbar, footer, browser tab
- Consistent across login/register/dashboard

### 7. Professional UI Polish
- Upgraded navbar with avatar image support
- Upgraded register page with role tabs + live phone availability check
- Upgraded settings page with avatar upload + preview
- Request code badges (`REQ2026XXXX`) on all list views
- Status pills, stage progress bars, and skill chips throughout

## Tech Stack
- **Backend**: Flask 3, Flask-SocketIO 5, Eventlet
- **Database**: MySQL (users, requests, jobs, ratings, chat, reports)
- **File Storage**: Local `static/uploads/` (production: swap for S3/GridFS)
- **Frontend**: Bootstrap 5, Phosphor Icons, Leaflet.js

## Setup

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Configure DB in app.py or via environment variables
#    DB_HOST, DB_USER, DB_PASSWORD, DB_NAME (default: lhc_v6)

# 3. Run (auto-creates DB + tables)
python app.py

# 4. Create admin account
#    Visit: http://localhost:5000/admin/setup

# 5. Login: Phone 0000000000 / Password: admin@1234
```

## Upload Directory Structure
```
static/uploads/
├── avatars/   ← profile photos  (avatar_<uid>.<ext>)
└── chat/      ← chat attachments (chat_<req>_<uid>_<ts>.<ext>)
```

## Migrating from v5
Use the ALTER statements at the bottom of `setup_v6.sql` to upgrade an existing `lhc_v5` database.

## Environment Variables
| Variable | Default | Description |
|---|---|---|
| SECRET_KEY | (hardcoded) | Flask session key |
| DB_HOST | localhost | MySQL host |
| DB_USER | root | MySQL user |
| DB_PASSWORD | Shah@#1909 | MySQL password |
| DB_NAME | lhc_v6 | Database name |
