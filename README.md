# ESTACLE

Modern, cross-platform messaging application built as a Progressive Web App (PWA).

## Features

- **Real-time messaging** with WebSocket support
- **One-to-one and group chats**
- **Voice and video calls** via WebRTC
- **Voice messages** with recording
- **File sharing** (images, videos, documents, etc.)
- **Push notifications** (Web Push)
- **Offline support** with service worker caching
- **Multi-device synchronization**
- **Light and Dark themes**
- **Responsive design** for phones, tablets, and desktops
- **Installable PWA**

## Technology Stack

- **Backend:** Python, Flask, Flask-SocketIO, SQLAlchemy
- **Database:** SQLite (easily migratable to PostgreSQL)
- **Frontend:** HTML5, CSS3, Vanilla JavaScript
- **Realtime:** WebSockets (Socket.IO)
- **Calls:** WebRTC with STUN
- **PWA:** Service Worker, Manifest, offline caching

## Requirements

- Python 3.10+
- pip

## Installation

```bash
# Clone or navigate to the project
cd ESTACLE

# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# The database is created automatically on first run
```

## Running the Application

```bash
# Development mode
python app.py

# The app will be available at http://localhost:5000
```

Or with environment variables:

```bash
export FLASK_ENV=development
export SECRET_KEY=your-secret-key-here
python app.py
```

## Production Deployment

```bash
# Using gunicorn with eventlet workers
gunicorn --worker-class eventlet -w 1 --bind 0.0.0.0:5000 app:app
```

For production:

1. Set a strong `SECRET_KEY` environment variable
2. Enable HTTPS (required for WebRTC, PWA, and secure cookies)
3. Configure TURN servers for WebRTC (for users behind restrictive NATs)
4. Generate VAPID keys for Web Push notifications
5. Consider migrating to PostgreSQL for larger scale

### VAPID Keys for Push Notifications

```bash
pip install pywebpush
vapid --gen
# Set VAPID_PRIVATE_KEY and VAPID_PUBLIC_KEY environment variables
```

### WebRTC Configuration

STUN servers are pre-configured (Google STUN). For production, add TURN servers in `config.py`:

```python
WEBRTC_TURN_SERVERS = [
    {
        'urls': 'turn:your-turn-server.com:3478',
        'username': 'user',
        'credential': 'pass'
    }
]
```

## PWA Installation

1. Open the app in a supported browser (Chrome, Edge, Safari, Firefox)
2. Look for the "Install" prompt or use the browser menu
3. On mobile: "Add to Home Screen"
4. The installed app runs in standalone mode

## Project Structure

```
ESTACLE/
├── app.py                 # Application entry point
├── config.py              # Configuration
├── requirements.txt
├── manifest.json          # PWA manifest
├── service-worker.js      # Service worker
├── database/
│   ├── database.py        # DB connection
│   └── models.py          # SQLAlchemy models
├── routes/                # API blueprints
│   ├── auth.py
│   ├── users.py
│   ├── chats.py
│   ├── groups.py
│   ├── messages.py
│   ├── files.py
│   ├── calls.py
│   └── notifications.py
├── realtime/
│   └── websocket.py       # Socket.IO handlers
├── templates/             # HTML templates
├── static/
│   ├── css/
│   ├── js/
│   └── icons/
├── uploads/               # User uploads
└── instance/              # SQLite database
```

## API Overview

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/auth/register` | POST | Create account |
| `/api/auth/login` | POST | Sign in |
| `/api/auth/logout` | POST | Sign out |
| `/api/auth/me` | GET | Current user |
| `/api/chats/` | GET | List conversations |
| `/api/chats/private` | POST | Start private chat |
| `/api/messages/:id` | GET/POST | Get/send messages |
| `/api/groups/` | POST | Create group |
| `/api/files/upload` | POST | Upload file |
| `/api/calls/start` | POST | Start call |
| `/api/users/search` | GET | Search users |

## Security

- Password hashing with scrypt
- Session-based authentication
- CSRF protection
- Input validation
- Secure file upload handling
- SQL injection protection via SQLAlchemy
- XSS protection via content escaping

## License

MIT
