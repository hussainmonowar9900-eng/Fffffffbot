# Telegram Reseller Bot

A complete Telegram bot for reselling digital products with wallet-based payments, built for **GitHub → Render** deployment.

## Features

- 🛒 Product catalog with plans and pricing
- 💰 Wallet system with UPI payment top-up
- 🔑 Key delivery after purchase
- 👥 User registration with phone verification
- 🔧 Admin panel for product/plan/PID management
- 💳 Manual payment approval (no fake payments)
- 📊 Statistics and broadcast messaging
- 🔄 SQLite database — survives restarts
- ⚡ Long polling architecture (single instance)
- 🛡️ Global error handling — never crashes on user errors
- 🔒 Admin authorization checked on every admin action

## Project Structure

```
├── bot.py              # Main entry point — startup checks + polling
├── config.py           # Environment variable loading and validation
├── database.py         # SQLite database layer (auto-init, migrations)
├── api_client.py       # External reseller API client
├── payment.py          # Payment gateway adapter (UPI manual)
├── user_handlers.py    # User-facing handlers (shop, wallet, keys, profile)
├── admin_handlers.py   # Admin panel handlers (products, plans, users, payments)
├── keyboards.py        # Telegram keyboard definitions
├── requirements.txt    # Python dependencies
├── .env.example        # Template for environment variables
├── .gitignore          # Git ignore rules
├── render.yaml         # Render deployment blueprint
└── README.md           # This file
```

## Deployment Guide

### Step 1: GitHub

1. Create a new repository on GitHub.
2. Upload all project files to the repository.
3. Push the files to the main branch.

**Important:** Never commit `.env` with real secrets. Only use `.env.example` as a template.

### Step 2: Render

1. Go to [render.com](https://render.com) and sign in.
2. Click **New +** → **Background Worker**.
3. Connect your GitHub account and select the repository.
4. Configure the service:
   - **Name:** `telegram-reseller-bot`
   - **Runtime:** Python 3
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `python bot.py`
5. Add Environment Variables (see below).
6. Click **Create Background Worker**.
7. Wait for the build to complete.
8. Check the logs for:
   ```
   [OK] Configuration loaded
   [OK] Database initialized
   [OK] Telegram authentication successful
   [OK] Bot initialized
   [OK] Polling started
   ```

### Step 3: Get Your Bot Token

1. Open Telegram and search for `@BotFather`.
2. Send `/newbot` and follow the prompts.
3. Copy the bot token — this is your `BOT_TOKEN`.

### Step 4: Get Your Telegram User ID

1. Open Telegram and search for `@userinfobot`.
2. Send any message — it will reply with your user ID.
3. This is your `ADMIN_ID`.

## Environment Variables

### Required

| Variable    | Description                          | Example                        |
|-------------|--------------------------------------|--------------------------------|
| `BOT_TOKEN` | Telegram bot token from @BotFather   | `123456:ABC-DEF1234ghIkl-zyx57` |
| `ADMIN_ID`  | Your Telegram user ID               | `123456789`                    |

### Optional

| Variable           | Description                          | Example                     |
|--------------------|--------------------------------------|-----------------------------|
| `API_URL`          | External reseller API base URL       | `https://api.example.com/v1` |
| `API_KEY`          | API authentication key               | `your-api-key`              |
| `MASTER_KEY`       | API master key (if required)          | `your-master-key`           |
| `PAYMENT_API_KEY`  | Payment gateway API key               | `your-payment-key`          |
| `PAYMENT_SECRET`   | Payment gateway secret                | `your-payment-secret`       |
| `UPI_ID`           | UPI ID for manual payments            | `yourname@upi`              |
| `SUPPORT_USERNAME` | Telegram username for support         | `SupportTeam`               |

## Start Command

```
python bot.py
```

This is the only command used in `render.yaml` and this README.

## How It Works

### User Flow

1. User sends `/start` → bot asks for phone number
2. User shares phone → main menu appears
3. User browses shop → selects product → selects plan
4. Bot shows purchase confirmation with price
5. User confirms → balance deducted → key delivered
6. Key is stored in "My Keys" permanently

### Wallet Flow

1. User opens Wallet → Add Money
2. Selects amount (preset or custom)
3. Bot shows UPI payment instructions with reference ID
4. User pays via UPI and submits transaction ID
5. Admin verifies payment in Admin Panel
6. Admin approves → wallet credited

### Admin Flow

1. Admin sends `/admin` → admin panel appears
2. Add products → add PIDs → add plans
3. View pending payments → approve/reject
4. Manage users (find, adjust balance, ban)
5. Broadcast messages to all users

## Render Service Type

This bot uses **Background Worker** on Render — not a web service.

- Background Workers run continuously without an HTTP port.
- The bot uses Telegram long polling, which keeps the process alive.
- No web server or health check endpoint is needed.

## Database

- SQLite database is auto-created on first startup.
- Tables are auto-created if they don't exist.
- Schema migrations are additive only — existing data is never lost.
- Wallet balances, purchase history, and user data survive restarts.

## Payment Gateway

The bot includes a fully functional **manual UPI payment** gateway:
- Users pay via UPI to the configured UPI ID
- Users submit their transaction ID
- Admin verifies and approves the payment
- Wallet is credited only after admin approval

To use an automated payment gateway (e.g. Razorpay, Cashfree), implement
the `PaymentGateway` interface in `payment.py` and wire it in
`PaymentService.__init__`. The gateway-specific adapter requires the
gateway's official API documentation and credentials.

## Security

- Admin authorization is checked on every admin callback, not just the menu.
- All SQL queries use parameterized statements — no SQL injection.
- Secrets are never logged or printed.
- `.gitignore` excludes `.env`, database files, and Python cache.
- Global error handler catches all exceptions without exposing tracebacks to users.

## Local Development

```bash
# 1. Clone the repository
git clone <your-repo-url>
cd <project-dir>

# 2. Create virtual environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
# venv\Scripts\activate   # Windows

# 3. Install dependencies
pip install -r requirements.txt

# 4. Set environment variables
cp .env.example .env
# Edit .env with your values

# 5. Run the bot
python bot.py
```

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `Missing environment variable: BOT_TOKEN` | Set `BOT_TOKEN` in Render Environment Variables |
| `Missing environment variable: ADMIN_ID` | Set `ADMIN_ID` in Render Environment Variables |
| `Telegram authentication failed` | Check that `BOT_TOKEN` is correct and not revoked |
| `Could not connect to the external API` | Check `API_URL` and `API_KEY` — or leave them blank for manual mode |
| Bot not responding to `/start` | Check Render logs for errors — the bot must show `[OK] Polling started` |
| Duplicate purchases | The bot uses database transactions — concurrent requests are safe |
| Balance lost after restart | The bot uses SQLite — balances are stored permanently |
