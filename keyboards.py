"""Inline and reply keyboards for the Telegram bot."""

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
)

def _get(item: object, key: str, default=None):
    """Read a value from a mapping or sqlite3.Row."""
    try:
        value = item[key]
        return default if value is None else value
    except (KeyError, IndexError, TypeError):
        return item.get(key, default) if hasattr(item, "get") else default


# ── Reply keyboards ───────────────────────────────────────────────────────────

def main_menu_reply() -> ReplyKeyboardMarkup:
    kb = [
        [KeyboardButton("🛒 Shop"), KeyboardButton("🔑 My Keys")],
        [KeyboardButton("💰 Wallet"), KeyboardButton("👤 Profile")],
        [KeyboardButton("📞 Support"), KeyboardButton("ℹ️ Help")],
    ]
    return ReplyKeyboardMarkup(kb, resize_keyboard=True)


def phone_request_reply() -> ReplyKeyboardMarkup:
    kb = [[KeyboardButton("📱 Share Phone Number", request_contact=True)]]
    return ReplyKeyboardMarkup(kb, resize_keyboard=True, one_time_keyboard=True)


def cancel_reply() -> ReplyKeyboardMarkup:
    kb = [[KeyboardButton("❌ Cancel")]]
    return ReplyKeyboardMarkup(kb, resize_keyboard=True)


# ── Inline keyboards ─────────────────────────────────────────────────────────

def main_menu_inline() -> InlineKeyboardMarkup:
    kb = [
        [InlineKeyboardButton("🛒 Shop", callback_data="shop")],
        [InlineKeyboardButton("🔑 My Keys", callback_data="my_keys")],
        [InlineKeyboardButton("💰 Wallet", callback_data="wallet")],
        [InlineKeyboardButton("👤 Profile", callback_data="profile")],
        [InlineKeyboardButton("📞 Support", callback_data="support")],
    ]
    return InlineKeyboardMarkup(kb)


def wallet_menu() -> InlineKeyboardMarkup:
    kb = [
        [InlineKeyboardButton("💳 Add Money", callback_data="wallet_add")],
        [InlineKeyboardButton("📊 Balance", callback_data="wallet_balance")],
        [InlineKeyboardButton("🔙 Back", callback_data="main_menu")],
    ]
    return InlineKeyboardMarkup(kb)


def wallet_add_amounts() -> InlineKeyboardMarkup:
    kb = [
        [
            InlineKeyboardButton("₹50", callback_data="add_50"),
            InlineKeyboardButton("₹100", callback_data="add_100"),
            InlineKeyboardButton("₹200", callback_data="add_200"),
        ],
        [
            InlineKeyboardButton("₹500", callback_data="add_500"),
            InlineKeyboardButton("₹1000", callback_data="add_1000"),
        ],
        [InlineKeyboardButton("✏️ Custom Amount", callback_data="add_custom")],
        [InlineKeyboardButton("🔙 Back", callback_data="wallet")],
    ]
    return InlineKeyboardMarkup(kb)


def payment_method_menu() -> InlineKeyboardMarkup:
    kb = [
        [InlineKeyboardButton("📱 UPI Payment", callback_data="pay_upi")],
        [InlineKeyboardButton("🔙 Back", callback_data="wallet_add")],
    ]
    return InlineKeyboardMarkup(kb)


def product_list(products: list) -> InlineKeyboardMarkup:
    """Build product list keyboard from list of product dicts."""
    kb = []
    for p in products:
        name = _get(p, "name", "Unknown")
        pid = _get(p, "id")
        kb.append([InlineKeyboardButton(f"📦 {name}", callback_data=f"prod_{pid}")])
    kb.append([InlineKeyboardButton("🔙 Back", callback_data="main_menu")])
    return InlineKeyboardMarkup(kb)


def plan_list(plans: list, product_id: int) -> InlineKeyboardMarkup:
    """Build plan list keyboard from list of plan dicts."""
    kb = []
    for plan in plans:
        name = _get(plan, "name", "Unknown")
        price = _get(plan, "price", 0)
        pid = _get(plan, "id")
        kb.append([
            InlineKeyboardButton(
                f"⏱️ {name} — ₹{price}",
                callback_data=f"buy_{product_id}_{pid}",
            )
        ])
    kb.append([InlineKeyboardButton("🔙 Back", callback_data="shop")])
    return InlineKeyboardMarkup(kb)


def purchase_confirm(product_id: int, plan_id: int, price: int) -> InlineKeyboardMarkup:
    kb = [
        [
            InlineKeyboardButton("✅ Confirm Purchase", callback_data=f"confirm_{product_id}_{plan_id}"),
            InlineKeyboardButton("❌ Cancel", callback_data="shop"),
        ]
    ]
    return InlineKeyboardMarkup(kb)


def back_to_main() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Main Menu", callback_data="main_menu")]])


def back_to_wallet() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="wallet")]])


def back_to_shop() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="shop")]])


def keys_pagination(keys: list, page: int = 0, per_page: int = 5) -> InlineKeyboardMarkup:
    """Paginated keys display."""
    total_pages = max(1, (len(keys) + per_page - 1) // per_page)
    kb = []
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"keys_{page - 1}"))
    nav.append(InlineKeyboardButton(f"📄 {page + 1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("➡️ Next", callback_data=f"keys_{page + 1}"))
    if nav:
        kb.append(nav)
    kb.append([InlineKeyboardButton("🔙 Main Menu", callback_data="main_menu")])
    return InlineKeyboardMarkup(kb)


# ── Admin keyboards ──────────────────────────────────────────────────────────

def admin_menu() -> InlineKeyboardMarkup:
    kb = [
        [InlineKeyboardButton("📦 Products", callback_data="admin_products")],
        [InlineKeyboardButton("🔑 PIDs", callback_data="admin_pids")],
        [InlineKeyboardButton("📋 Plans", callback_data="admin_plans")],
        [InlineKeyboardButton("👥 Users", callback_data="admin_users")],
        [InlineKeyboardButton("💰 Payments", callback_data="admin_payments")],
        [InlineKeyboardButton("📊 Statistics", callback_data="admin_stats")],
        [InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast")],
        [InlineKeyboardButton("🔙 Main Menu", callback_data="main_menu")],
    ]
    return InlineKeyboardMarkup(kb)


def admin_products_menu() -> InlineKeyboardMarkup:
    kb = [
        [InlineKeyboardButton("➕ Add Product", callback_data="admin_prod_add")],
        [InlineKeyboardButton("📋 List Products", callback_data="admin_prod_list")],
        [InlineKeyboardButton("🗑️ Delete Product", callback_data="admin_prod_del")],
        [InlineKeyboardButton("🔙 Admin Menu", callback_data="admin_menu")],
    ]
    return InlineKeyboardMarkup(kb)


def admin_pids_menu() -> InlineKeyboardMarkup:
    kb = [
        [InlineKeyboardButton("➕ Add PID", callback_data="admin_pid_add")],
        [InlineKeyboardButton("📋 List PIDs", callback_data="admin_pid_list")],
        [InlineKeyboardButton("🗑️ Delete PID", callback_data="admin_pid_del")],
        [InlineKeyboardButton("🔙 Admin Menu", callback_data="admin_menu")],
    ]
    return InlineKeyboardMarkup(kb)


def admin_plans_menu() -> InlineKeyboardMarkup:
    kb = [
        [InlineKeyboardButton("➕ Add Plan", callback_data="admin_plan_add")],
        [InlineKeyboardButton("📋 List Plans", callback_data="admin_plan_list")],
        [InlineKeyboardButton("🗑️ Delete Plan", callback_data="admin_plan_del")],
        [InlineKeyboardButton("🔙 Admin Menu", callback_data="admin_menu")],
    ]
    return InlineKeyboardMarkup(kb)


def admin_users_menu() -> InlineKeyboardMarkup:
    kb = [
        [InlineKeyboardButton("📊 User Stats", callback_data="admin_user_stats")],
        [InlineKeyboardButton("🔍 Find User", callback_data="admin_user_find")],
        [InlineKeyboardButton("💰 Adjust Balance", callback_data="admin_user_balance")],
        [InlineKeyboardButton("🚫 Ban User", callback_data="admin_user_ban")],
        [InlineKeyboardButton("🔙 Admin Menu", callback_data="admin_menu")],
    ]
    return InlineKeyboardMarkup(kb)


def admin_payments_menu() -> InlineKeyboardMarkup:
    kb = [
        [InlineKeyboardButton("📋 Pending Payments", callback_data="admin_pay_pending")],
        [InlineKeyboardButton("✅ Approve Payment", callback_data="admin_pay_approve")],
        [InlineKeyboardButton("❌ Reject Payment", callback_data="admin_pay_reject")],
        [InlineKeyboardButton("📋 Payment History", callback_data="admin_pay_history")],
        [InlineKeyboardButton("🔙 Admin Menu", callback_data="admin_menu")],
    ]
    return InlineKeyboardMarkup(kb)


def admin_product_delete_list(products: list) -> InlineKeyboardMarkup:
    kb = []
    for p in products:
        kb.append([InlineKeyboardButton(
            f"🗑️ {p['name']}",
            callback_data=f"admin_prod_del_{p['id']}",
        )])
    kb.append([InlineKeyboardButton("🔙 Back", callback_data="admin_products")])
    return InlineKeyboardMarkup(kb)


def admin_pid_delete_list(pids: list) -> InlineKeyboardMarkup:
    kb = []
    for pid in pids:
        kb.append([InlineKeyboardButton(
            f"🗑️ {_get(pid, 'pid_value', 'N/A')} ({_get(pid, 'product_name', 'N/A')})",
            callback_data=f"admin_pid_del_{pid['id']}",
        )])
    kb.append([InlineKeyboardButton("🔙 Back", callback_data="admin_pids")])
    return InlineKeyboardMarkup(kb)


def admin_plan_delete_list(plans: list) -> InlineKeyboardMarkup:
    kb = []
    for plan in plans:
        kb.append([InlineKeyboardButton(
            f"🗑️ {plan['name']} — ₹{plan['price']}",
            callback_data=f"admin_plan_del_{plan['id']}",
        )])
    kb.append([InlineKeyboardButton("🔙 Back", callback_data="admin_plans")])
    return InlineKeyboardMarkup(kb)


def admin_payment_action(payment_id: int) -> InlineKeyboardMarkup:
    kb = [
        [
            InlineKeyboardButton("✅ Approve", callback_data=f"admin_pay_ok_{payment_id}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"admin_pay_no_{payment_id}"),
        ],
        [InlineKeyboardButton("🔙 Back", callback_data="admin_payments")],
    ]
    return InlineKeyboardMarkup(kb)


def admin_back() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Admin Menu", callback_data="admin_menu")]])
