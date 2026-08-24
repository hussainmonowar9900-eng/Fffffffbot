"""User-facing Telegram handlers — commands, callbacks, and conversation states."""

import logging
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)

from database import Database
from api_client import APIClient, APIError
from payment import PaymentService
from config import Config
import keyboards

logger = logging.getLogger(__name__)

# ── Conversation states ─────────────────────────────────────────────────────
(
    WAITING_PHONE,
    WAITING_CUSTOM_AMOUNT,
    WAITING_TXN_ID,
    WAITING_ADMIN_INPUT,
) = range(4)

# State keys for admin conversations (kept separate to avoid collision)
ADMIN_ADD_PRODUCT = 10
ADMIN_ADD_PID = 11
ADMIN_ADD_PLAN = 12
ADMIN_FIND_USER = 13
ADMIN_ADJUST_BALANCE = 14
ADMIN_BROADCAST = 15
ADMIN_PAY_APPROVE = 16
ADMIN_PAY_REJECT = 17


class UserHandlers:
    """All user-facing command and callback handlers."""

    def __init__(self, db: Database, api: APIClient, payments: PaymentService, config: Config):
        self.db = db
        self.api = api
        self.payments = payments
        self.config = config

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _check_banned(self, user_id: int) -> bool:
        return self.db.is_banned(user_id)

    async def _send_main_menu(self, update: Update, text: str = None) -> None:
        if text is None:
            user = self.db.get_user(update.effective_user.id)
            name = (update.effective_user.first_name or "User")
            balance = user["balance"] if user else 0
            text = (
                f"👋 Welcome, *{name}*!\n\n"
                f"💰 Balance: ₹{balance}\n\n"
                f"Choose an option below:"
            )
        await update.message.reply_text(
            text,
            reply_markup=keyboards.main_menu_reply(),
            parse_mode="Markdown",
        )

    # ── /start ───────────────────────────────────────────────────────────────

    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        user = update.effective_user
        user_id = user.id

        # Create or update user record
        self.db.get_or_create_user(user_id, user.username or "", user.first_name or "")

        if self._check_banned(user_id):
            await update.message.reply_text(
                "🚫 Your account has been banned. Please contact support."
            )
            return ConversationHandler.END

        # Check if phone is set
        db_user = self.db.get_user(user_id)
        if db_user and db_user["phone"]:
            await self._send_main_menu(update)
            return ConversationHandler.END

        # Ask for phone number
        await update.message.reply_text(
            "👋 Welcome to the Reseller Bot!\n\n"
            "To get started, please verify your phone number.",
            reply_markup=keyboards.phone_request_reply(),
        )
        return WAITING_PHONE

    # ── Phone contact handler ───────────────────────────────────────────────

    async def handle_phone(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        contact = update.message.contact
        if contact is None:
            await update.message.reply_text("Please use the button to share your phone number.")
            return WAITING_PHONE

        user_id = update.effective_user.id
        phone = contact.phone_number
        self.db.update_phone(user_id, phone)
        await update.message.reply_text(
            f"✅ Phone number verified!\n",
            reply_markup=keyboards.main_menu_reply(),
        )
        await update.message.reply_text(
            "Use the menu below to explore the bot:",
            reply_markup=keyboards.main_menu_inline(),
        )
        return ConversationHandler.END

    # ── Phone text fallback ──────────────────────────────────────────────────

    async def handle_phone_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        text = update.message.text or ""
        if text == "❌ Cancel":
            await update.message.reply_text(
                "Phone verification is required to use this bot. Send /start to try again."
            )
            return ConversationHandler.END
        await update.message.reply_text(
            "Please tap the button to share your phone number.",
            reply_markup=keyboards.phone_request_reply(),
        )
        return WAITING_PHONE

    # ── /menu ────────────────────────────────────────────────────────────────

    async def cmd_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        self.db.get_or_create_user(user_id, update.effective_user.username or "", update.effective_user.first_name or "")

        if self._check_banned(user_id):
            await update.message.reply_text("🚫 Your account has been banned.")
            return

        user = self.db.get_user(user_id)
        name = update.effective_user.first_name or "User"
        balance = user["balance"] if user else 0
        await update.message.reply_text(
            f"👋 *{name}*\n💰 Balance: ₹{balance}\n\nChoose an option:",
            reply_markup=keyboards.main_menu_inline(),
            parse_mode="Markdown",
        )

    # ── /help ───────────────────────────────────────────────────────────────

    async def cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        support = self.config.support_username or "SupportTeam"
        await update.message.reply_text(
            "📖 *Help*\n\n"
            "🛒 *Shop* — Browse and purchase products\n"
            "🔑 *My Keys* — View your purchased activation keys\n"
            "💰 *Wallet* — Add money and check balance\n"
            "👤 *Profile* — View your account info\n"
            "📞 *Support* — Contact support\n\n"
            f"Support: @{support}",
            parse_mode="Markdown",
        )

    # ── /cancel ─────────────────────────────────────────────────────────────

    async def cmd_cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        await update.message.reply_text(
            "❌ Action cancelled.",
            reply_markup=keyboards.main_menu_reply(),
        )
        return ConversationHandler.END

    # ── Reply keyboard text routing ──────────────────────────────────────────

    async def handle_reply_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        text = update.message.text or ""
        user_id = update.effective_user.id

        if self._check_banned(user_id):
            await update.message.reply_text("🚫 Your account has been banned.")
            return

        if text == "🛒 Shop":
            await self._show_shop(update)
        elif text == "🔑 My Keys":
            await self._show_keys(update)
        elif text == "💰 Wallet":
            await self._show_wallet(update)
        elif text == "👤 Profile":
            await self._show_profile(update)
        elif text == "📞 Support":
            await self._show_support(update)
        elif text == "ℹ️ Help":
            await self.cmd_help(update, context)
        elif text == "❌ Cancel":
            await update.message.reply_text(
                "Action cancelled.",
                reply_markup=keyboards.main_menu_reply(),
            )
        else:
            await update.message.reply_text(
                "Please use the menu buttons below.",
                reply_markup=keyboards.main_menu_reply(),
            )

    # ── Inline callback router ──────────────────────────────────────────────

    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        await query.answer()

        user_id = query.from_user.id

        if self._check_banned(user_id):
            await query.answer("🚫 Your account has been banned.", show_alert=True)
            return

        data = query.data or ""

        # ── Admin callbacks ──────────────────────────────────────────────────
        if data.startswith("admin_"):
            # Admin authorization check for every admin callback
            if not self.config.is_admin(user_id):
                await query.answer("⛔ Access denied.", show_alert=True)
                return
            # Defer to admin handlers via context
            context.user_data["admin_handler"] = True
            await self._handle_admin_callback(update, context, data)
            return

        # ── User callbacks ────────────────────────────────────────────────────
        if data == "main_menu":
            user = self.db.get_user(user_id)
            name = query.from_user.first_name or "User"
            balance = user["balance"] if user else 0
            await query.edit_message_text(
                f"👋 *{name}*\n💰 Balance: ₹{balance}\n\nChoose an option:",
                reply_markup=keyboards.main_menu_inline(),
                parse_mode="Markdown",
            )

        elif data == "shop":
            await self._show_shop_inline(update, query)

        elif data == "my_keys":
            await self._show_keys_inline(update, query)

        elif data == "wallet":
            await self._show_wallet_inline(update, query)

        elif data == "profile":
            await self._show_profile_inline(update, query)

        elif data == "support":
            await self._show_support_inline(update, query)

        elif data == "wallet_add":
            await query.edit_message_text(
                "💰 *Add Money to Wallet*\n\nSelect an amount:",
                reply_markup=keyboards.wallet_add_amounts(),
                parse_mode="Markdown",
            )

        elif data == "wallet_balance":
            balance = self.db.get_balance(user_id)
            await query.edit_message_text(
                f"💰 Your current balance: *₹{balance}*",
                reply_markup=keyboards.back_to_wallet(),
                parse_mode="Markdown",
            )

        elif data == "add_custom":
            context.user_data["state"] = WAITING_CUSTOM_AMOUNT
            await query.edit_message_text(
                "✏️ Enter the amount you want to add (₹10 – ₹10000):",
                reply_markup=keyboards.back_to_wallet(),
            )

        elif data.startswith("add_"):
            await self._handle_add_amount(update, query, data)

        elif data == "pay_upi":
            await self._process_payment_request(update, query, context)

        elif data.startswith("prod_"):
            await self._show_product_plans(update, query, data)

        elif data.startswith("buy_"):
            await self._show_purchase_confirm(update, query, data)

        elif data.startswith("confirm_"):
            await self._execute_purchase(update, query, data)

        elif data.startswith("keys_"):
            await self._show_keys_page(update, query, data)

        elif data == "noop":
            pass

        else:
            logger.warning("Unhandled callback: %s", data)

    async def handle_stateful_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
        """Dispatch text messages that belong to an active user flow."""
        state = context.user_data.get("state")
        if state == WAITING_CUSTOM_AMOUNT:
            result = await self.handle_custom_amount(update, context)
            if result != WAITING_CUSTOM_AMOUNT:
                context.user_data.pop("state", None)
            return True

        if context.user_data.get("pending_payment_id"):
            await self.handle_txn_id_input(update, context)
            return True

        return False

    # ── Shop display ─────────────────────────────────────────────────────────

    async def _show_shop(self, update: Update) -> None:
        products = self.db.list_products(active_only=True)
        if not products:
            await update.message.reply_text(
                "🛒 No products available yet. Please check back later.",
                reply_markup=keyboards.main_menu_reply(),
            )
            return
        await update.message.reply_text(
            "🛒 *Shop*\n\nSelect a product:",
            reply_markup=keyboards.product_list(products),
            parse_mode="Markdown",
        )

    async def _show_shop_inline(self, update: Update, query) -> None:
        products = self.db.list_products(active_only=True)
        if not products:
            await query.edit_message_text(
                "🛒 No products available yet. Please check back later.",
                reply_markup=keyboards.back_to_main(),
            )
            return
        await query.edit_message_text(
            "🛒 *Shop*\n\nSelect a product:",
            reply_markup=keyboards.product_list(products),
            parse_mode="Markdown",
        )

    # ── Product plans ────────────────────────────────────────────────────────

    async def _show_product_plans(self, update: Update, query, data: str) -> None:
        try:
            product_id = int(data.replace("prod_", ""))
        except ValueError:
            await query.edit_message_text("Invalid product.")
            return

        product = self.db.get_product(product_id)
        if not product:
            await query.edit_message_text("Product not found.")
            return

        plans = self.db.list_plans(product_id, active_only=True)
        if not plans:
            await query.edit_message_text(
                f"📦 *{product['name']}*\n\nNo plans available for this product.",
                reply_markup=keyboards.back_to_shop(),
                parse_mode="Markdown",
            )
            return

        desc = f"\n\n_{product['description']}_" if product["description"] else ""
        await query.edit_message_text(
            f"📦 *{product['name']}*{desc}\n\nSelect a plan:",
            reply_markup=keyboards.plan_list(plans, product_id),
            parse_mode="Markdown",
        )

    # ── Purchase confirmation ────────────────────────────────────────────────

    async def _show_purchase_confirm(self, update: Update, query, data: str) -> None:
        parts = data.replace("buy_", "").split("_")
        if len(parts) != 2:
            await query.edit_message_text("Invalid selection.")
            return
        try:
            product_id = int(parts[0])
            plan_id = int(parts[1])
        except ValueError:
            await query.edit_message_text("Invalid selection.")
            return

        product = self.db.get_product(product_id)
        plan = self.db.get_plan(plan_id)
        if not product or not plan:
            await query.edit_message_text("Product or plan not found.")
            return

        balance = self.db.get_balance(query.from_user.id)
        price = plan["price"]

        if balance < price:
            await query.edit_message_text(
                f"⚠️ *Insufficient Balance*\n\n"
                f"Product: {product['name']}\n"
                f"Plan: {plan['name']}\n"
                f"Price: ₹{price}\n"
                f"Your balance: ₹{balance}\n\n"
                f"Please add money to your wallet first.",
                reply_markup=keyboards.back_to_wallet(),
                parse_mode="Markdown",
            )
            return

        await query.edit_message_text(
            f"🛒 *Confirm Purchase*\n\n"
            f"Product: {product['name']}\n"
            f"Plan: {plan['name']}\n"
            f"Duration: {plan['duration_days']} days\n"
            f"Price: ₹{price}\n"
            f"Your balance: ₹{balance}\n"
            f"Balance after purchase: ₹{balance - price}\n\n"
            f"Proceed with purchase?",
            reply_markup=keyboards.purchase_confirm(product_id, plan_id, price),
            parse_mode="Markdown",
        )

    # ── Execute purchase ─────────────────────────────────────────────────────

    async def _execute_purchase(self, update: Update, query, data: str) -> None:
        parts = data.replace("confirm_", "").split("_")
        if len(parts) != 2:
            await query.edit_message_text("Invalid selection.")
            return
        try:
            product_id = int(parts[0])
            plan_id = int(parts[1])
        except ValueError:
            await query.edit_message_text("Invalid selection.")
            return

        product = self.db.get_product(product_id)
        plan = self.db.get_plan(plan_id)
        if not product or not plan:
            await query.edit_message_text("Product or plan not found.")
            return

        user_id = query.from_user.id
        price = plan["price"]
        balance = self.db.get_balance(user_id)

        if balance < price:
            await query.edit_message_text(
                "⚠️ Insufficient balance. Please add money to your wallet first.",
                reply_markup=keyboards.back_to_wallet(),
            )
            return

        # Get PID for this product
        pid_row = self.db.get_pid_for_product(product_id)
        if not pid_row:
            await query.edit_message_text(
                "⚠️ This product is not ready for purchase yet (no PID configured). Please contact support.",
                reply_markup=keyboards.back_to_shop(),
            )
            return

        pid_value = pid_row["pid_value"]

        # Try to place order with external API
        key_data = ""
        order_ref = ""
        if self.api.is_configured:
            try:
                result = self.api.place_order(pid_value, plan["name"])
                key_data = result.get("key", "")
                order_ref = result.get("order_id", "")
            except APIError as e:
                logger.error("API purchase failed: %s", e)
                await query.edit_message_text(
                    "⚠️ Service temporarily unavailable. Please try again later.\n"
                    "Your balance was *not* deducted.",
                    reply_markup=keyboards.back_to_shop(),
                    parse_mode="Markdown",
                )
                return
        else:
            await query.edit_message_text(
                "⚠️ Service temporarily unavailable. Please try again later.\n"
                "The reseller API is not configured, so your balance was not deducted.",
                reply_markup=keyboards.back_to_shop(),
            )
            return

        # Atomically deduct balance and store key
        try:
            self.db.process_purchase(user_id, product_id, plan_id, price, key_data, order_ref)
        except ValueError as e:
            await query.edit_message_text(
                f"⚠️ Purchase failed: {e}\nYour balance was not deducted.",
                reply_markup=keyboards.back_to_shop(),
            )
            return

        new_balance = self.db.get_balance(user_id)
        await query.edit_message_text(
            f"✅ *Purchase Successful!*\n\n"
            f"Product: {product['name']}\n"
            f"Plan: {plan['name']}\n"
            f"Price: ₹{price}\n"
            f"New balance: ₹{new_balance}\n\n"
            f"🔑 Your Key:\n`{key_data}`\n\n"
            f"You can view this key anytime in *My Keys*.",
            reply_markup=keyboards.back_to_main(),
            parse_mode="Markdown",
        )

    # ── Keys display ─────────────────────────────────────────────────────────

    async def _show_keys(self, update: Update) -> None:
        user_id = update.effective_user.id
        keys = self.db.get_user_keys(user_id)
        if not keys:
            await update.message.reply_text(
                "🔑 You have no purchased keys yet.\nVisit the Shop to make a purchase!",
                reply_markup=keyboards.main_menu_reply(),
            )
            return
        await self._send_keys_text(update.message.reply_text, keys, 0)

    async def _show_keys_inline(self, update: Update, query) -> None:
        user_id = query.from_user.id
        keys = self.db.get_user_keys(user_id)
        if not keys:
            await query.edit_message_text(
                "🔑 You have no purchased keys yet.\nVisit the Shop to make a purchase!",
                reply_markup=keyboards.back_to_main(),
            )
            return
        await self._send_keys_text(query.edit_message_text, keys, 0)

    async def _show_keys_page(self, update: Update, query, data: str) -> None:
        try:
            page = int(data.replace("keys_", ""))
        except ValueError:
            page = 0
        user_id = query.from_user.id
        keys = self.db.get_user_keys(user_id)
        await self._send_keys_text(query.edit_message_text, keys, page)

    async def _send_keys_text(self, reply_func, keys: list, page: int, per_page: int = 5) -> None:
        total = len(keys)
        total_pages = max(1, (total + per_page - 1) // per_page)
        start = page * per_page
        end = start + per_page
        page_keys = keys[start:end]

        lines = [f"🔑 *My Keys* ({total} total)\n"]
        for i, k in enumerate(page_keys, start=start + 1):
            product_name = k["product_name"] or "Unknown"
            plan_name = k["plan_name"] or "N/A"
            key_data = k["key_data"] or "N/A"
            date = k["created_at"][:16] if k["created_at"] else ""
            lines.append(
                f"{i}. *{product_name}* — {plan_name}\n"
                f"   🔑 `{key_data}`\n"
                f"   📅 {date}"
            )

        await reply_func(
            "\n".join(lines),
            reply_markup=keyboards.keys_pagination(keys, page, per_page),
            parse_mode="Markdown",
        )

    # ── Wallet ───────────────────────────────────────────────────────────────

    async def _show_wallet(self, update: Update) -> None:
        balance = self.db.get_balance(update.effective_user.id)
        await update.message.reply_text(
            f"💰 *Wallet*\n\nCurrent balance: *₹{balance}*\n\nWhat would you like to do?",
            reply_markup=keyboards.wallet_menu(),
            parse_mode="Markdown",
        )

    async def _show_wallet_inline(self, update: Update, query) -> None:
        balance = self.db.get_balance(query.from_user.id)
        await query.edit_message_text(
            f"💰 *Wallet*\n\nCurrent balance: *₹{balance}*\n\nWhat would you like to do?",
            reply_markup=keyboards.wallet_menu(),
            parse_mode="Markdown",
        )

    async def _handle_add_amount(self, update: Update, query, data: str) -> None:
        """Handle preset amount selection."""
        try:
            amount = int(data.replace("add_", ""))
        except ValueError:
            await query.edit_message_text("Invalid amount.")
            return

        if amount < self.config.wallet_min_add or amount > self.config.wallet_max_add:
            await query.edit_message_text(
                f"⚠️ Amount must be between ₹{self.config.wallet_min_add} and ₹{self.config.wallet_max_add}.",
                reply_markup=keyboards.wallet_add_amounts(),
            )
            return

        # Create payment request
        payment_info = self.payments.create_payment_request(query.from_user.id, amount)

        instructions = payment_info["instructions"]
        upi_id = payment_info.get("upi_id")
        txn_id = payment_info["txn_id"]

        # Store txn_id in user_data for later
        # Note: we can't use context here since this is called from callback
        # We'll store it in DB and ask for txn_id separately

        kb = keyboards.payment_method_menu()
        await query.edit_message_text(
            instructions + f"\n\n🏷️ Your Transaction Reference: `{txn_id}`",
            reply_markup=kb,
            parse_mode="Markdown",
        )

    async def _process_payment_request(self, update: Update, query, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Show payment instructions and ask for txn_id."""
        # Find the most recent pending payment for this user
        pending = self.db.list_pending_payments()
        user_pending = [p for p in pending if p["user_id"] == query.from_user.id]

        if not user_pending:
            await query.edit_message_text(
                "⚠️ No pending payment found. Please select an amount first.",
                reply_markup=keyboards.back_to_wallet(),
            )
            return

        payment = user_pending[0]  # Most recent
        context.user_data["pending_payment_id"] = payment["id"]

        await query.edit_message_text(
            f"💳 *Payment Confirmation*\n\n"
            f"Amount: ₹{payment['amount']}\n"
            f"Reference: `{payment['txn_id']}`\n\n"
            f"After making the payment, please send your *12-digit UPI Transaction ID* "
            f"(e.g. 123456789012) as a message.",
            reply_markup=keyboards.back_to_wallet(),
            parse_mode="Markdown",
        )

    async def handle_custom_amount(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Handle custom amount input."""
        text = update.message.text or ""
        if text == "❌ Cancel":
            await update.message.reply_text(
                "Cancelled.",
                reply_markup=keyboards.main_menu_reply(),
            )
            return ConversationHandler.END

        try:
            amount = int(text)
        except ValueError:
            await update.message.reply_text(
                "⚠️ Please enter a valid number.",
                reply_markup=keyboards.cancel_reply(),
            )
            return WAITING_CUSTOM_AMOUNT

        if amount < self.config.wallet_min_add or amount > self.config.wallet_max_add:
            await update.message.reply_text(
                f"⚠️ Amount must be between ₹{self.config.wallet_min_add} and ₹{self.config.wallet_max_add}.",
                reply_markup=keyboards.cancel_reply(),
            )
            return WAITING_CUSTOM_AMOUNT

        payment_info = self.payments.create_payment_request(update.effective_user.id, amount)
        await update.message.reply_text(
            payment_info["instructions"] + f"\n\n🏷️ Reference: `{payment_info['txn_id']}`",
            reply_markup=keyboards.payment_method_menu(),
            parse_mode="Markdown",
        )
        return ConversationHandler.END

    async def handle_txn_id_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle user submitting their UPI transaction ID."""
        text = update.message.text or ""
        user_id = update.effective_user.id

        # Basic validation: UTR is typically 12 digits
        clean = re.sub(r"\s+", "", text)
        if not re.match(r"^\d{10,22}$", clean):
            await update.message.reply_text(
                "⚠️ Please enter a valid Transaction ID (10-22 digits).",
                reply_markup=keyboards.main_menu_reply(),
            )
            return

        # Find the most recent pending payment for this user
        pending = self.db.list_pending_payments()
        user_pending = [p for p in pending if p["user_id"] == user_id]

        if not user_pending:
            context.user_data.pop("pending_payment_id", None)
            await update.message.reply_text(
                "⚠️ No pending payment found. Please use the Wallet menu to add money.",
                reply_markup=keyboards.main_menu_reply(),
            )
            return

        payment = user_pending[0]
        # Update the payment txn_id with the user's submitted UTR
        # (the original generated txn_id was a reference; the UTR is the actual transaction ID)
        # We'll store the UTR in the payment record
        self.db.set_setting(f"utr_{payment['id']}", clean)
        context.user_data.pop("pending_payment_id", None)

        await update.message.reply_text(
            f"✅ Transaction ID submitted!\n\n"
            f"Your payment of ₹{payment['amount']} is now pending verification.\n"
            f"We'll notify you once it's approved by admin.\n\n"
            f"Reference: `{payment['txn_id']}`",
            reply_markup=keyboards.main_menu_reply(),
            parse_mode="Markdown",
        )

    # ── Profile ──────────────────────────────────────────────────────────────

    async def _show_profile(self, update: Update) -> None:
        user_id = update.effective_user.id
        user = self.db.get_user(user_id)
        if not user:
            await update.message.reply_text("Please send /start first.")
            return

        keys_count = self.db.count_keys(user_id)
        await update.message.reply_text(
            f"👤 *Profile*\n\n"
            f"🆔 ID: `{user_id}`\n"
            f"👤 Name: {user['first_name'] or 'N/A'}\n"
            f"📱 Phone: {user['phone'] or 'Not set'}\n"
            f"💬 Username: @{user['username'] or 'N/A'}\n"
            f"💰 Balance: ₹{user['balance']}\n"
            f"🔑 Keys purchased: {keys_count}\n"
            f"📅 Joined: {user['created_at'][:16] if user['created_at'] else 'N/A'}",
            reply_markup=keyboards.main_menu_reply(),
            parse_mode="Markdown",
        )

    async def _show_profile_inline(self, update: Update, query) -> None:
        user_id = query.from_user.id
        user = self.db.get_user(user_id)
        if not user:
            await query.edit_message_text("Please send /start first.")
            return

        keys_count = self.db.count_keys(user_id)
        await query.edit_message_text(
            f"👤 *Profile*\n\n"
            f"🆔 ID: `{user_id}`\n"
            f"👤 Name: {user['first_name'] or 'N/A'}\n"
            f"📱 Phone: {user['phone'] or 'Not set'}\n"
            f"💬 Username: @{user['username'] or 'N/A'}\n"
            f"💰 Balance: ₹{user['balance']}\n"
            f"🔑 Keys purchased: {keys_count}\n"
            f"📅 Joined: {user['created_at'][:16] if user['created_at'] else 'N/A'}",
            reply_markup=keyboards.back_to_main(),
            parse_mode="Markdown",
        )

    # ── Support ──────────────────────────────────────────────────────────────

    async def _show_support(self, update: Update) -> None:
        support = self.config.support_username or "SupportTeam"
        await update.message.reply_text(
            f"📞 *Support*\n\n"
            f"If you need help, please contact:\n"
            f"👤 @{support}\n\n"
            f"We'll respond as soon as possible.",
            reply_markup=keyboards.main_menu_reply(),
            parse_mode="Markdown",
        )

    async def _show_support_inline(self, update: Update, query) -> None:
        support = self.config.support_username or "SupportTeam"
        await query.edit_message_text(
            f"📞 *Support*\n\n"
            f"If you need help, please contact:\n"
            f"👤 @{support}\n\n"
            f"We'll respond as soon as possible.",
            reply_markup=keyboards.back_to_main(),
            parse_mode="Markdown",
        )

    # ── Admin callback delegation ────────────────────────────────────────────

    async def _handle_admin_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE, data: str) -> None:
        """Delegate admin callbacks to AdminHandlers."""
        from admin_handlers import AdminHandlers
        admin = AdminHandlers(self.db, self.api, self.payments, self.config)
        await admin.handle_callback(update, context, data)
