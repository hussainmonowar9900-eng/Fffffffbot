"""Admin panel handlers — product/PID/plan management, user management, payments."""

import logging
from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

from database import Database
from api_client import APIClient
from payment import PaymentService
from config import Config
import keyboards

logger = logging.getLogger(__name__)

# Admin conversation states (must match user_handlers)
ADMIN_ADD_PRODUCT = 10
ADMIN_ADD_PID = 11
ADMIN_ADD_PLAN = 12
ADMIN_FIND_USER = 13
ADMIN_ADJUST_BALANCE = 14
ADMIN_BROADCAST = 15
ADMIN_PAY_APPROVE = 16
ADMIN_PAY_REJECT = 17

# Sub-states for multi-step admin inputs
ADMIN_PID_PRODUCT = 20
ADMIN_PLAN_PRODUCT = 21
ADMIN_PLAN_NAME = 22
ADMIN_PLAN_PRICE = 23
ADMIN_PLAN_DURATION = 24
ADMIN_BALANCE_USERID = 25
ADMIN_BALANCE_AMOUNT = 26
ADMIN_BAN_USERID = 27


class AdminHandlers:
    """All admin panel command and callback handlers."""

    def __init__(self, db: Database, api: APIClient, payments: PaymentService, config: Config):
        self.db = db
        self.api = api
        self.payments = payments
        self.config = config

    def _is_admin(self, user_id: int) -> bool:
        return self.config.is_admin(user_id)

    # ── /admin command ───────────────────────────────────────────────────────

    async def cmd_admin(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        if not self._is_admin(user_id):
            await update.message.reply_text("⛔ Access denied. You are not an admin.")
            return

        await update.message.reply_text(
            "🔧 *Admin Panel*\n\nSelect an option:",
            reply_markup=keyboards.admin_menu(),
            parse_mode="Markdown",
        )

    # ── Admin callback router ───────────────────────────────────────────────

    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE, data: str) -> None:
        query = update.callback_query
        user_id = query.from_user.id

        # Authorization check on EVERY admin callback
        if not self._is_admin(user_id):
            await query.answer("⛔ Access denied.", show_alert=True)
            return

        if data == "admin_menu":
            await query.edit_message_text(
                "🔧 *Admin Panel*\n\nSelect an option:",
                reply_markup=keyboards.admin_menu(),
                parse_mode="Markdown",
            )

        elif data == "admin_products":
            await query.edit_message_text(
                "📦 *Product Management*",
                reply_markup=keyboards.admin_products_menu(),
                parse_mode="Markdown",
            )

        elif data == "admin_pids":
            await query.edit_message_text(
                "🔑 *PID Management*",
                reply_markup=keyboards.admin_pids_menu(),
                parse_mode="Markdown",
            )

        elif data == "admin_plans":
            await query.edit_message_text(
                "📋 *Plan Management*",
                reply_markup=keyboards.admin_plans_menu(),
                parse_mode="Markdown",
            )

        elif data == "admin_users":
            await query.edit_message_text(
                "👥 *User Management*",
                reply_markup=keyboards.admin_users_menu(),
                parse_mode="Markdown",
            )

        elif data == "admin_payments":
            await query.edit_message_text(
                "💰 *Payment Management*",
                reply_markup=keyboards.admin_payments_menu(),
                parse_mode="Markdown",
            )

        elif data == "admin_stats":
            await self._show_stats(query)

        elif data == "admin_broadcast":
            context.user_data["admin_state"] = ADMIN_BROADCAST
            await query.edit_message_text(
                "📢 *Broadcast Message*\n\nSend the message you want to broadcast to all users:",
                reply_markup=keyboards.admin_back(),
                parse_mode="Markdown",
            )

        # ── Product management ──────────────────────────────────────────────
        elif data == "admin_prod_add":
            context.user_data["admin_state"] = ADMIN_ADD_PRODUCT
            await query.edit_message_text(
                "➕ *Add Product*\n\nSend the product name:",
                reply_markup=keyboards.admin_back(),
                parse_mode="Markdown",
            )

        elif data == "admin_prod_list":
            await self._list_products(query)

        elif data == "admin_prod_del":
            await self._delete_product_list(query)

        elif data.startswith("admin_prod_del_"):
            try:
                prod_id = int(data.replace("admin_prod_del_", ""))
            except ValueError:
                await query.edit_message_text("Invalid product ID.")
                return
            self.db.delete_product(prod_id)
            await query.edit_message_text(
                "✅ Product deleted.",
                reply_markup=keyboards.admin_products_menu(),
            )

        # ── PID management ──────────────────────────────────────────────────
        elif data == "admin_pid_add":
            await self._add_pid_start(query, context)

        elif data == "admin_pid_list":
            await self._list_pids(query)

        elif data == "admin_pid_del":
            await self._delete_pid_list(query)

        elif data.startswith("admin_pid_del_"):
            try:
                pid_id = int(data.replace("admin_pid_del_", ""))
            except ValueError:
                await query.edit_message_text("Invalid PID ID.")
                return
            self.db.delete_pid(pid_id)
            await query.edit_message_text(
                "✅ PID deleted.",
                reply_markup=keyboards.admin_pids_menu(),
            )

        # ── Plan management ──────────────────────────────────────────────────
        elif data == "admin_plan_add":
            await self._add_plan_start(query, context)

        elif data == "admin_plan_list":
            await self._list_plans(query)

        elif data == "admin_plan_del":
            await self._delete_plan_list(query)

        elif data.startswith("admin_plan_del_"):
            try:
                plan_id = int(data.replace("admin_plan_del_", ""))
            except ValueError:
                await query.edit_message_text("Invalid plan ID.")
                return
            self.db.delete_plan(plan_id)
            await query.edit_message_text(
                "✅ Plan deleted.",
                reply_markup=keyboards.admin_plans_menu(),
            )

        # ── User management ─────────────────────────────────────────────────
        elif data == "admin_user_stats":
            await self._user_stats(query)

        elif data == "admin_user_find":
            context.user_data["admin_state"] = ADMIN_FIND_USER
            await query.edit_message_text(
                "🔍 *Find User*\n\nSend the Telegram user ID:",
                reply_markup=keyboards.admin_back(),
                parse_mode="Markdown",
            )

        elif data == "admin_user_balance":
            context.user_data["admin_state"] = ADMIN_BALANCE_USERID
            await query.edit_message_text(
                "💰 *Adjust Balance*\n\nSend the Telegram user ID:",
                reply_markup=keyboards.admin_back(),
                parse_mode="Markdown",
            )

        elif data == "admin_user_ban":
            context.user_data["admin_state"] = ADMIN_BAN_USERID
            await query.edit_message_text(
                "🚫 *Ban/Unban User*\n\nSend the Telegram user ID:",
                reply_markup=keyboards.admin_back(),
                parse_mode="Markdown",
            )

        # ── Payment management ──────────────────────────────────────────────
        elif data == "admin_pay_pending":
            await self._list_pending_payments(query)

        elif data == "admin_pay_approve":
            await self._approve_payment_list(query)

        elif data == "admin_pay_reject":
            await self._reject_payment_list(query)

        elif data == "admin_pay_history":
            await self._payment_history(query)

        elif data.startswith("admin_pay_ok_"):
            try:
                pay_id = int(data.replace("admin_pay_ok_", ""))
            except ValueError:
                await query.edit_message_text("Invalid payment ID.")
                return
            success = self.payments.approve_payment(pay_id)
            if success:
                payment = self.db.get_payment(pay_id)
                await query.edit_message_text(
                    f"✅ Payment #{pay_id} approved.\n₹{payment['amount']} credited to user {payment['user_id']}.",
                    reply_markup=keyboards.admin_payments_menu(),
                )
            else:
                await query.edit_message_text(
                    "⚠️ Could not approve payment. It may not be pending.",
                    reply_markup=keyboards.admin_payments_menu(),
                )

        elif data.startswith("admin_pay_no_"):
            try:
                pay_id = int(data.replace("admin_pay_no_", ""))
            except ValueError:
                await query.edit_message_text("Invalid payment ID.")
                return
            success = self.payments.reject_payment(pay_id)
            if success:
                await query.edit_message_text(
                    f"❌ Payment #{pay_id} rejected. No balance credited.",
                    reply_markup=keyboards.admin_payments_menu(),
                )
            else:
                await query.edit_message_text(
                    "⚠️ Could not reject payment. It may not be pending.",
                    reply_markup=keyboards.admin_payments_menu(),
                )

        else:
            logger.warning("Unhandled admin callback: %s", data)

    # ── Admin text input handler ─────────────────────────────────────────────

    async def handle_admin_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle text input during admin conversations."""
        user_id = update.effective_user.id
        if not self._is_admin(user_id):
            return

        text = update.message.text or ""
        state = context.user_data.get("admin_state")

        if state is None:
            return

        # ── Add product ──────────────────────────────────────────────────────
        if state == ADMIN_ADD_PRODUCT:
            name = text.strip()
            if not name:
                await update.message.reply_text("Product name cannot be empty. Try again:")
                return
            prod_id = self.db.add_product(name)
            await update.message.reply_text(
                f"✅ Product '{name}' added (ID: {prod_id}).",
                reply_markup=keyboards.admin_menu(),
            )
            context.user_data.pop("admin_state", None)

        # ── Add PID (step 1: select product) ─────────────────────────────────
        elif state == ADMIN_PID_PRODUCT:
            try:
                prod_id = int(text.strip())
            except ValueError:
                await update.message.reply_text("Invalid product ID. Send a number:")
                return
            product = self.db.get_product(prod_id)
            if not product:
                await update.message.reply_text("Product not found. Send a valid product ID:")
                return
            context.user_data["pid_product_id"] = prod_id
            context.user_data["admin_state"] = ADMIN_ADD_PID
            await update.message.reply_text(
                f"Selected product: {product['name']}\n\nNow send the PID value:",
                reply_markup=keyboards.admin_back(),
            )

        elif state == ADMIN_ADD_PID:
            pid_value = text.strip()
            if not pid_value:
                await update.message.reply_text("PID value cannot be empty. Try again:")
                return
            prod_id = context.user_data.get("pid_product_id")
            if not prod_id:
                await update.message.reply_text("Session expired. Start again from Admin Panel.")
                context.user_data.pop("admin_state", None)
                return
            pid_id = self.db.add_pid(prod_id, pid_value)
            await update.message.reply_text(
                f"✅ PID '{pid_value}' added to product (ID: {pid_id}).",
                reply_markup=keyboards.admin_menu(),
            )
            context.user_data.pop("admin_state", None)
            context.user_data.pop("pid_product_id", None)

        # ── Add plan (multi-step) ────────────────────────────────────────────
        elif state == ADMIN_PLAN_PRODUCT:
            try:
                prod_id = int(text.strip())
            except ValueError:
                await update.message.reply_text("Invalid product ID. Send a number:")
                return
            product = self.db.get_product(prod_id)
            if not product:
                await update.message.reply_text("Product not found. Send a valid product ID:")
                return
            context.user_data["plan_product_id"] = prod_id
            context.user_data["admin_state"] = ADMIN_PLAN_NAME
            await update.message.reply_text(
                f"Selected product: {product['name']}\n\nNow send the plan name (e.g. '1 Month', '3 Months'):",
                reply_markup=keyboards.admin_back(),
            )

        elif state == ADMIN_PLAN_NAME:
            name = text.strip()
            if not name:
                await update.message.reply_text("Plan name cannot be empty. Try again:")
                return
            context.user_data["plan_name"] = name
            context.user_data["admin_state"] = ADMIN_PLAN_PRICE
            await update.message.reply_text(
                f"Plan name: {name}\n\nNow send the price in ₹ (e.g. 99):",
                reply_markup=keyboards.admin_back(),
            )

        elif state == ADMIN_PLAN_PRICE:
            try:
                price = int(text.strip())
            except ValueError:
                await update.message.reply_text("Invalid price. Send a number (e.g. 99):")
                return
            if price < 0:
                await update.message.reply_text("Price must be positive. Try again:")
                return
            context.user_data["plan_price"] = price
            context.user_data["admin_state"] = ADMIN_PLAN_DURATION
            await update.message.reply_text(
                f"Price: ₹{price}\n\nNow send the duration in days (e.g. 30):",
                reply_markup=keyboards.admin_back(),
            )

        elif state == ADMIN_PLAN_DURATION:
            try:
                duration = int(text.strip())
            except ValueError:
                await update.message.reply_text("Invalid duration. Send a number of days (e.g. 30):")
                return
            if duration < 1:
                await update.message.reply_text("Duration must be at least 1 day. Try again:")
                return
            prod_id = context.user_data.get("plan_product_id")
            name = context.user_data.get("plan_name")
            price = context.user_data.get("plan_price")
            if not all([prod_id, name, price is not None]):
                await update.message.reply_text("Session expired. Start again from Admin Panel.")
                context.user_data.pop("admin_state", None)
                return

            plan_id = self.db.add_plan(prod_id, name, price, duration)
            await update.message.reply_text(
                f"✅ Plan '{name}' added!\n"
                f"Product ID: {prod_id}\n"
                f"Price: ₹{price}\n"
                f"Duration: {duration} days\n"
                f"Plan ID: {plan_id}",
                reply_markup=keyboards.admin_menu(),
            )
            # Clean up
            for k in ["plan_product_id", "plan_name", "plan_price", "admin_state"]:
                context.user_data.pop(k, None)

        # ── Find user ────────────────────────────────────────────────────────
        elif state == ADMIN_FIND_USER:
            try:
                target_id = int(text.strip())
            except ValueError:
                await update.message.reply_text("Invalid user ID. Send a numeric Telegram ID:")
                return
            user = self.db.get_user(target_id)
            if not user:
                await update.message.reply_text(
                    "❌ User not found.",
                    reply_markup=keyboards.admin_menu(),
                )
            else:
                keys_count = self.db.count_keys(target_id)
                await update.message.reply_text(
                    f"👤 *User Found*\n\n"
                    f"🆔 ID: `{user['user_id']}`\n"
                    f"👤 Name: {user['first_name'] or 'N/A'}\n"
                    f"📱 Phone: {user['phone'] or 'Not set'}\n"
                    f"💬 Username: @{user['username'] or 'N/A'}\n"
                    f"💰 Balance: ₹{user['balance']}\n"
                    f"🔑 Keys: {keys_count}\n"
                    f"🚫 Banned: {'Yes' if user['is_banned'] else 'No'}\n"
                    f"📅 Joined: {user['created_at'][:16] if user['created_at'] else 'N/A'}",
                    reply_markup=keyboards.admin_menu(),
                    parse_mode="Markdown",
                )
            context.user_data.pop("admin_state", None)

        # ── Adjust balance ──────────────────────────────────────────────────
        elif state == ADMIN_BALANCE_USERID:
            try:
                target_id = int(text.strip())
            except ValueError:
                await update.message.reply_text("Invalid user ID. Send a numeric Telegram ID:")
                return
            user = self.db.get_user(target_id)
            if not user:
                await update.message.reply_text(
                    "❌ User not found.",
                    reply_markup=keyboards.admin_menu(),
                )
                context.user_data.pop("admin_state", None)
                return
            context.user_data["balance_target_id"] = target_id
            context.user_data["admin_state"] = ADMIN_BALANCE_AMOUNT
            await update.message.reply_text(
                f"User: {user['first_name'] or target_id}\n"
                f"Current balance: ₹{user['balance']}\n\n"
                f"Send the amount to add (use negative to deduct, e.g. -50):",
                reply_markup=keyboards.admin_back(),
            )

        elif state == ADMIN_BALANCE_AMOUNT:
            try:
                amount = int(text.strip())
            except ValueError:
                await update.message.reply_text("Invalid amount. Send a number (e.g. 100 or -50):")
                return
            target_id = context.user_data.get("balance_target_id")
            if not target_id:
                await update.message.reply_text("Session expired. Start again.")
                context.user_data.pop("admin_state", None)
                return
            try:
                new_balance = self.db.adjust_balance(target_id, amount)
                await update.message.reply_text(
                    f"✅ Balance adjusted.\n"
                    f"User: {target_id}\n"
                    f"Change: {'+' if amount >= 0 else ''}{amount}\n"
                    f"New balance: ₹{new_balance}",
                    reply_markup=keyboards.admin_menu(),
                )
            except ValueError as e:
                await update.message.reply_text(
                    f"⚠️ {e}",
                    reply_markup=keyboards.admin_menu(),
                )
            context.user_data.pop("admin_state", None)
            context.user_data.pop("balance_target_id", None)

        # ── Ban/unban ────────────────────────────────────────────────────────
        elif state == ADMIN_BAN_USERID:
            try:
                target_id = int(text.strip())
            except ValueError:
                await update.message.reply_text("Invalid user ID. Send a numeric Telegram ID:")
                return
            user = self.db.get_user(target_id)
            if not user:
                await update.message.reply_text(
                    "❌ User not found.",
                    reply_markup=keyboards.admin_menu(),
                )
                context.user_data.pop("admin_state", None)
                return
            new_ban = not bool(user["is_banned"])
            self.db.set_banned(target_id, new_ban)
            await update.message.reply_text(
                f"{'🚫 User banned' if new_ban else '✅ User unbanned'}: {target_id}",
                reply_markup=keyboards.admin_menu(),
            )
            context.user_data.pop("admin_state", None)

        # ── Broadcast ────────────────────────────────────────────────────────
        elif state == ADMIN_BROADCAST:
            message = text.strip()
            if not message:
                await update.message.reply_text("Message cannot be empty. Try again:")
                return
            user_ids = self.db.get_all_user_ids()
            sent = 0
            failed = 0
            for uid in user_ids:
                try:
                    await context.bot.send_message(
                        chat_id=uid,
                        text=f"📢 *Broadcast*\n\n{message}",
                        parse_mode="Markdown",
                    )
                    sent += 1
                except Exception as e:
                    logger.warning("Broadcast to %d failed: %s", uid, e)
                    failed += 1
            await update.message.reply_text(
                f"✅ Broadcast complete.\nSent: {sent}\nFailed: {failed}",
                reply_markup=keyboards.admin_menu(),
            )
            context.user_data.pop("admin_state", None)

        else:
            logger.warning("Unknown admin state: %s", state)

    # ── Admin display helpers ─────────────────────────────────────────────────

    async def _show_stats(self, query) -> None:
        users = self.db.count_users()
        keys = self.db.count_keys()
        purchases = self.db.count_keys()
        pending = self.db.count_payments("pending")
        approved = self.db.count_payments("approved")
        revenue = self.db.sum_revenue()
        products = len(self.db.list_products(active_only=False))

        await query.edit_message_text(
            f"📊 *Statistics*\n\n"
            f"👥 Total users: {users}\n"
            f"📦 Products: {products}\n"
            f"🔑 Keys sold: {keys}\n"
            f"⏳ Pending payments: {pending}\n"
            f"✅ Approved payments: {approved}\n"
            f"💰 Total revenue: ₹{revenue}",
            reply_markup=keyboards.admin_back(),
            parse_mode="Markdown",
        )

    async def _list_products(self, query) -> None:
        products = self.db.list_products(active_only=False)
        if not products:
            await query.edit_message_text(
                "📦 No products found.",
                reply_markup=keyboards.admin_products_menu(),
            )
            return
        lines = ["📦 *Products*\n"]
        for p in products:
            status = "✅" if p["is_active"] else "❌"
            lines.append(f"{status} *{p['name']}* (ID: {p['id']})")
            if p["description"]:
                lines.append(f"   _{p['description']}_")
        await query.edit_message_text(
            "\n".join(lines),
            reply_markup=keyboards.admin_products_menu(),
            parse_mode="Markdown",
        )

    async def _delete_product_list(self, query) -> None:
        products = self.db.list_products(active_only=False)
        if not products:
            await query.edit_message_text(
                "📦 No products to delete.",
                reply_markup=keyboards.admin_products_menu(),
            )
            return
        await query.edit_message_text(
            "🗑️ *Select product to delete:*",
            reply_markup=keyboards.admin_product_delete_list(products),
            parse_mode="Markdown",
        )

    async def _add_pid_start(self, query, context: ContextTypes.DEFAULT_TYPE) -> None:
        products = self.db.list_products(active_only=False)
        if not products:
            await query.edit_message_text(
                "⚠️ No products found. Add a product first.",
                reply_markup=keyboards.admin_pids_menu(),
            )
            return
        lines = ["Select a product by sending its ID:\n"]
        for p in products:
            lines.append(f"• {p['name']} — ID: {p['id']}")
        context.user_data["admin_state"] = ADMIN_PID_PRODUCT
        await query.edit_message_text(
            "🔑 *Add PID*\n\n" + "\n".join(lines),
            reply_markup=keyboards.admin_back(),
            parse_mode="Markdown",
        )

    async def _list_pids(self, query) -> None:
        pids = self.db.list_pids()
        if not pids:
            await query.edit_message_text(
                "🔑 No PIDs found.",
                reply_markup=keyboards.admin_pids_menu(),
            )
            return
        lines = ["🔑 *PIDs*\n"]
        for p in pids:
            lines.append(f"• {p['pid_value']} — {(p['product_name'] or 'N/A')} (ID: {p['id']})")
        await query.edit_message_text(
            "\n".join(lines),
            reply_markup=keyboards.admin_pids_menu(),
            parse_mode="Markdown",
        )

    async def _delete_pid_list(self, query) -> None:
        pids = self.db.list_pids()
        if not pids:
            await query.edit_message_text(
                "🔑 No PIDs to delete.",
                reply_markup=keyboards.admin_pids_menu(),
            )
            return
        await query.edit_message_text(
            "🗑️ *Select PID to delete:*",
            reply_markup=keyboards.admin_pid_delete_list(pids),
            parse_mode="Markdown",
        )

    async def _add_plan_start(self, query, context: ContextTypes.DEFAULT_TYPE) -> None:
        products = self.db.list_products(active_only=False)
        if not products:
            await query.edit_message_text(
                "⚠️ No products found. Add a product first.",
                reply_markup=keyboards.admin_plans_menu(),
            )
            return
        lines = ["Select a product by sending its ID:\n"]
        for p in products:
            lines.append(f"• {p['name']} — ID: {p['id']}")
        context.user_data["admin_state"] = ADMIN_PLAN_PRODUCT
        await query.edit_message_text(
            "📋 *Add Plan*\n\n" + "\n".join(lines),
            reply_markup=keyboards.admin_back(),
            parse_mode="Markdown",
        )

    async def _list_plans(self, query) -> None:
        plans = self.db.list_all_plans()
        if not plans:
            await query.edit_message_text(
                "📋 No plans found.",
                reply_markup=keyboards.admin_plans_menu(),
            )
            return
        lines = ["📋 *Plans*\n"]
        for p in plans:
            status = "✅" if p["is_active"] else "❌"
            lines.append(
                f"{status} *{p['name']}* — ₹{p['price']} "
                f"({(p['product_name'] or 'N/A')}, {p['duration_days']}d) "
                f"[ID: {p['id']}]"
            )
        await query.edit_message_text(
            "\n".join(lines),
            reply_markup=keyboards.admin_plans_menu(),
            parse_mode="Markdown",
        )

    async def _delete_plan_list(self, query) -> None:
        plans = self.db.list_all_plans()
        if not plans:
            await query.edit_message_text(
                "📋 No plans to delete.",
                reply_markup=keyboards.admin_plans_menu(),
            )
            return
        await query.edit_message_text(
            "🗑️ *Select plan to delete:*",
            reply_markup=keyboards.admin_plan_delete_list(plans),
            parse_mode="Markdown",
        )

    async def _user_stats(self, query) -> None:
        users = self.db.count_users()
        await query.edit_message_text(
            f"👥 *User Statistics*\n\nTotal registered users: {users}",
            reply_markup=keyboards.admin_users_menu(),
            parse_mode="Markdown",
        )

    async def _list_pending_payments(self, query) -> None:
        pending = self.db.list_pending_payments()
        if not pending:
            await query.edit_message_text(
                "✅ No pending payments.",
                reply_markup=keyboards.admin_payments_menu(),
            )
            return
        lines = ["⏳ *Pending Payments*\n"]
        for p in pending:
            name = p["first_name"] or p["username"] or p["user_id"]
            utr = self.db.get_setting(f"utr_{p['id']}") or "Not submitted"
            lines.append(
                f"• #{p['id']} — ₹{p['amount']} — {name}\n"
                f"  Ref: `{p['txn_id']}`\n"
                f"  UTR: `{utr}`\n"
                f"  Date: {p['created_at'][:16] if p['created_at'] else 'N/A'}"
            )
        await query.edit_message_text(
            "\n".join(lines),
            reply_markup=keyboards.admin_payments_menu(),
            parse_mode="Markdown",
        )

    async def _approve_payment_list(self, query) -> None:
        pending = self.db.list_pending_payments()
        if not pending:
            await query.edit_message_text(
                "✅ No pending payments to approve.",
                reply_markup=keyboards.admin_payments_menu(),
            )
            return
        lines = ["✅ *Approve Payment*\n\nSelect a payment:"]
        for p in pending:
            name = p["first_name"] or p["username"] or p["user_id"]
            lines.append(f"• #{p['id']} — ₹{p['amount']} — {name}")
        # Show first pending with action buttons
        first = pending[0]
        await query.edit_message_text(
            f"Payment #{first['id']}\n"
            f"Amount: ₹{first['amount']}\n"
            f"User: {first['first_name'] or first['username'] or first['user_id']}\n"
            f"Ref: `{first['txn_id']}`\n"
            f"UTR: `{self.db.get_setting(f'utr_{first['id']}') or 'Not submitted'}`",
            reply_markup=keyboards.admin_payment_action(first["id"]),
            parse_mode="Markdown",
        )

    async def _reject_payment_list(self, query) -> None:
        pending = self.db.list_pending_payments()
        if not pending:
            await query.edit_message_text(
                "✅ No pending payments to reject.",
                reply_markup=keyboards.admin_payments_menu(),
            )
            return
        first = pending[0]
        await query.edit_message_text(
            f"Payment #{first['id']}\n"
            f"Amount: ₹{first['amount']}\n"
            f"User: {first['first_name'] or first['username'] or first['user_id']}\n"
            f"Ref: `{first['txn_id']}`\n"
            f"UTR: `{self.db.get_setting(f'utr_{first['id']}') or 'Not submitted'}`",
            reply_markup=keyboards.admin_payment_action(first["id"]),
            parse_mode="Markdown",
        )

    async def _payment_history(self, query) -> None:
        history = self.db.list_payment_history(limit=20)
        if not history:
            await query.edit_message_text(
                "📋 No payment history.",
                reply_markup=keyboards.admin_payments_menu(),
            )
            return
        lines = ["📋 *Payment History*\n"]
        for p in history:
            status_icon = {"pending": "⏳", "approved": "✅", "rejected": "❌"}.get(p["status"], "❓")
            name = p["first_name"] or p["username"] or p["user_id"]
            lines.append(
                f"{status_icon} #{p['id']} — ₹{p['amount']} — {name} ({p['status']})"
            )
        await query.edit_message_text(
            "\n".join(lines),
            reply_markup=keyboards.admin_payments_menu(),
            parse_mode="Markdown",
        )
