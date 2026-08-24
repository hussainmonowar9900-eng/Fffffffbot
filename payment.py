"""Payment adapter — abstract interface for payment gateways.

This module provides a clean adapter interface for payment processing.
The UPI/manual gateway is fully implemented.  If you wish to use a
specific payment gateway (e.g. Razorpay, Cashfree, etc.), implement the
PaymentGateway interface in a new adapter class and wire it in
`PaymentService.__init__`.

NOTE: No payment is ever marked as successful automatically.  Only
explicit admin approval or a verified gateway callback credits the
wallet.
"""

import logging
import secrets
from typing import Optional
from database import Database
from config import Config

logger = logging.getLogger(__name__)


class PaymentGateway:
    """Abstract payment gateway interface."""

    name: str = "base"

    def create_payment(self, amount: int, txn_id: str, user_id: int) -> dict:
        """Create a payment request. Returns dict with payment URL / instructions."""
        raise NotImplementedError

    def verify_payment(self, txn_id: str) -> bool:
        """Verify a payment with the gateway. Returns True only if confirmed."""
        raise NotImplementedError


class UPIManualGateway(PaymentGateway):
    """Manual UPI payment gateway — generates a UPI payment link and
    requires admin approval to credit the wallet.

    This is a fully functional manual-payment flow: the user pays via UPI,
    submits their transaction ID, and an admin verifies and approves it.
    No fake success.
    """

    name = "upi_manual"

    def __init__(self, upi_id: str):
        self.upi_id = upi_id

    def create_payment(self, amount: int, txn_id: str, user_id: int) -> dict:
        if not self.upi_id:
            return {
                "instructions": (
                    "⚠️ UPI is not configured by the admin yet.\n"
                    "Please contact support to add money to your wallet."
                ),
                "payment_url": None,
                "upi_id": None,
            }

        upi_link = f"upi://pay?pa={self.upi_id}&pn=ResellerBot&am={amount}&cu=INR&tn={txn_id}"
        return {
            "instructions": (
                f"💳 Please pay ₹{amount} to the following UPI ID:\n\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"📱 UPI ID: `{self.upi_id}`\n"
                f"💰 Amount: ₹{amount}\n"
                f"🏷️ Reference: `{txn_id}`\n"
                f"━━━━━━━━━━━━━━━━━━\n\n"
                f"After payment, send your 12-digit UPI Transaction ID.\n"
                f"Your payment will be verified by admin before crediting."
            ),
            "payment_url": upi_link,
            "upi_id": self.upi_id,
        }

    def verify_payment(self, txn_id: str) -> bool:
        """Manual gateway — verification is done by admin, not automatically."""
        return False


class PaymentService:
    """Coordinates payment creation, storage, and wallet crediting."""

    def __init__(self, db: Database, config: Config):
        self.db = db
        self.config = config
        # Use the manual UPI gateway by default
        self.gateway: PaymentGateway = UPIManualGateway(config.upi_id)

    def generate_txn_id(self) -> str:
        """Generate a unique transaction reference."""
        return "TXN" + secrets.token_hex(8).upper()

    def create_payment_request(self, user_id: int, amount: int) -> dict:
        """Create a new payment request. Returns payment info dict."""
        txn_id = self.generate_txn_id()

        # Store in database as pending
        payment_id = self.db.create_payment(user_id, amount, txn_id, method="upi")

        # Get payment instructions from gateway
        payment_info = self.gateway.create_payment(amount, txn_id, user_id)
        payment_info["txn_id"] = txn_id
        payment_info["payment_id"] = payment_id
        payment_info["amount"] = amount

        return payment_info

    def approve_payment(self, payment_id: int) -> bool:
        """Admin approves a pending payment. Credits wallet atomically.

        Returns True on success, False if payment not found or not pending.
        """
        payment = self.db.approve_payment_atomic(payment_id)
        if payment is None:
            return False

        logger.info(
            "Payment %d approved — ₹%d credited to user %d",
            payment_id, payment["amount"], payment["user_id"],
        )
        return True

    def reject_payment(self, payment_id: int) -> bool:
        """Admin rejects a pending payment. No wallet credit."""
        payment = self.db.get_payment(payment_id)
        if payment is None:
            return False
        if payment["status"] != "pending":
            return False

        self.db.update_payment_status(payment_id, "rejected")
        logger.info("Payment %d rejected", payment_id)
        return True

    def submit_txn_id(self, user_id: int, txn_id: str) -> Optional[int]:
        """User submits their UPI transaction ID for a pending payment.

        Returns the payment_id if found, None otherwise.
        """
        payment = self.db.get_payment_by_txn(txn_id)
        if payment is None:
            return None
        if payment["user_id"] != user_id:
            return None
        if payment["status"] != "pending":
            return None
        return payment["id"]
