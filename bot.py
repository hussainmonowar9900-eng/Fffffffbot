"""Telegram Reseller Bot — main entry point.

Designed for GitHub → Render deployment.
Start command: python bot.py
"""

import sys
import logging
import asyncio
import traceback

# ── Logging setup (before anything else) ────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
# Reduce noise from telegram library
logging.getLogger("telegram").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)

logger = logging.getLogger("reseller-bot")

# ── Imports ────────────────────────────────────────────────────────────────
from config import Config, ConfigError, load_config, safe_log_value, SECRET_VARS
from database import Database
from api_client import APIClient
from payment import PaymentService
from user_handlers import UserHandlers, WAITING_PHONE, WAITING_CUSTOM_AMOUNT
from admin_handlers import AdminHandlers

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    filters,
    ContextTypes,
)


# ── Global error handler ────────────────────────────────────────────────────

async def global_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Catch unexpected exceptions. Keeps the bot alive, never exposes secrets."""
    error = context.error
    if error is None:
        return

    # Log the error
    logger.error("Unhandled exception: %s", error)
    logger.debug("Traceback:\n%s", traceback.format_exception(type(error), error, error.__traceback__))

    # Notify the user (without traceback)
    if isinstance(update, Update) and update.effective_chat:
        try:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="⚠️ An unexpected error occurred. Please try again later.\n"
                     "If the problem persists, contact support.",
            )
        except Exception:
            pass  # Don't let error notification crash the handler


# ── Startup sequence ────────────────────────────────────────────────────────

def startup_checks() -> Config:
    """Run all startup checks in order. Returns validated Config or exits."""

    # 1. Configuration check
    print("=" * 50)
    print("  Telegram Reseller Bot — Starting up")
    print("=" * 50)

    try:
        config = load_config()
        print("[OK] Configuration loaded")
        # Log non-secret config values
        print(f"  Admin IDs: {config.admin_ids}")
        print(f"  API URL: {safe_log_value('API_URL', config.api_url)}")
        print(f"  API Key: {safe_log_value('API_KEY', config.api_key)}")
        print(f"  Master Key: {safe_log_value('MASTER_KEY', config.master_key)}")
        print(f"  UPI ID: {config.upi_id if config.upi_id else '(not set)'}")
        print(f"  Support: @{config.support_username}")
        print(f"  DB Path: {config.db_path}")
    except ConfigError as e:
        print(f"[FAIL] Configuration error: {e}")
        print("\nCONFIGURATION ERROR:")
        print(f"  {e}")
        sys.exit(1)

    # 2. Database initialization
    try:
        db = Database(config.db_path)
        print("[OK] Database initialized")
    except Exception as e:
        print(f"[FAIL] Database initialization failed: {e}")
        sys.exit(1)

    # 3. External API configuration check
    api = APIClient(config)
    if api.is_configured:
        print(f"[OK] External API configured: {config.api_url}")
    else:
        print("[INFO] External API not configured (purchases will use manual PID reference)")

    # 4. Payment configuration check
    if config.upi_id:
        print(f"[OK] UPI payment configured: {config.upi_id}")
    else:
        print("[INFO] UPI not configured (wallet top-up will show contact-support message)")

    return config, db, api


async def post_init(application: Application) -> None:
    """Called after Application is initialized but before polling starts.

    Performs Telegram authentication (getMe) and final setup.
    """
    # 5. Telegram configuration validation + getMe
    try:
        me = await application.bot.get_me()
        print(f"[OK] Telegram authentication successful")
        print(f"  Bot: @{me.username} ({me.first_name})")
        print(f"  ID: {me.id}")
    except Exception as e:
        print(f"[FAIL] Telegram authentication failed: {e}")
        print("\nCONFIGURATION ERROR:")
        print(f"  Could not authenticate with Telegram. Check BOT_TOKEN.")
        # Don't exit here — let the polling attempt fail with a clearer message
        raise

    # 6. Bot initialized
    print("[OK] Bot initialized")


def build_application(config: Config, db: Database, api: APIClient) -> Application:
    """Build and configure the Telegram Application with all handlers."""
    payments = PaymentService(db, config)
    user_handlers = UserHandlers(db, api, payments, config)
    admin_handlers = AdminHandlers(db, api, payments, config)

    # Build application
    app = (
        Application.builder()
        .token(config.bot_token)
        .post_init(post_init)
        .build()
    )

    # ── Conversation handler for phone verification ─────────────────────────
    phone_conv = ConversationHandler(
        entry_points=[CommandHandler("start", user_handlers.cmd_start)],
        states={
            WAITING_PHONE: [
                MessageHandler(filters.CONTACT, user_handlers.handle_phone),
                MessageHandler(filters.TEXT & ~filters.COMMAND, user_handlers.handle_phone_text),
            ],
        },
        fallbacks=[CommandHandler("cancel", user_handlers.cmd_cancel)],
        allow_reentry=True,
    )

    async def route_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Route active admin and user text flows before normal menu text."""
        if context.user_data.get("admin_state"):
            await admin_handlers.handle_admin_text(update, context)
            return
        if await user_handlers.handle_stateful_text(update, context):
            return
        await user_handlers.handle_reply_text(update, context)

    # ── Register handlers ──────────────────────────────────────────────────
    app.add_handler(phone_conv)
    app.add_handler(CommandHandler("menu", user_handlers.cmd_menu))
    app.add_handler(CommandHandler("help", user_handlers.cmd_help))
    app.add_handler(CommandHandler("cancel", user_handlers.cmd_cancel))
    app.add_handler(CommandHandler("admin", admin_handlers.cmd_admin))

    # Stateful text flows and reply-keyboard routing
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        route_text,
    ))

    # Callback query handler (all inline buttons)
    app.add_handler(CallbackQueryHandler(user_handlers.handle_callback))

    # Global error handler
    app.add_error_handler(global_error_handler)

    return app


def main() -> None:
    """Main entry point — runs startup checks then starts polling."""
    # ── Steps 1-4: Config, DB, API, Payment checks ──────────────────────────
    config, db, api = startup_checks()

    # ── Step 5-6: Build application (Telegram auth happens in post_init) ────
    app = build_application(config, db, api)

    # ── Step 7: Start polling ───────────────────────────────────────────────
    print("[OK] Polling started")
    print("=" * 50)

    try:
        # run_polling blocks until stopped; it handles its own event loop
        app.run_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True,
        )
    except KeyboardInterrupt:
        print("\n[OK] Bot stopped by user")
    except Exception as e:
        logger.error("Fatal error during polling: %s", e)
        logger.debug("Traceback:\n%s", traceback.format_exc())
        print(f"[FAIL] Fatal error: {e}")
        sys.exit(1)
    finally:
        db.close()
        print("[OK] Database connection closed")


if __name__ == "__main__":
    main()
