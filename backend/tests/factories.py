"""Object factories for tests.

These build model instances *without* touching the database. A test that needs them
persisted does the flush itself, under whatever tenant context it needs. Keeping the
factories pure means a test never inherits a fixture's tenant binding by accident.
"""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from xenovarients.core.security import hash_password
from xenovarients.models.customer import (
    Customer,
    CustomerOrder,
    OrderItem,
    OrderStatus,
    Product,
    ProductVariant,
)
from xenovarients.models.tenancy import Business, BusinessMembership, Role, User

DEFAULT_PASSWORD = "correct-horse-battery"


def business(
    *,
    name: str = "Test Business",
    timezone: str = "Asia/Dhaka",
    currency: str = "BDT",
) -> Business:
    return Business(name=name, timezone=timezone, currency=currency)


def user(
    *,
    email: str | None = None,
    name: str = "Test User",
    password: str = DEFAULT_PASSWORD,
    is_active: bool = True,
) -> User:
    return User(
        email=email or f"user-{uuid.uuid4().hex[:8]}@example.com",
        name=name,
        password_hash=hash_password(password),
        is_active=is_active,
    )


def membership(
    user: User,
    business_: Business,
    role: str = Role.staff.value,
) -> BusinessMembership:
    return BusinessMembership(business_id=business_.id, user_id=user.id, role=role)


def customer(
    business_: Business,
    *,
    name: str | None = None,
    phone_e164: str | None = None,
    email_normalised: str | None = None,
) -> Customer:
    return Customer(
        business_id=business_.id,
        source_customer_id=f"src-c-{uuid.uuid4().hex[:10]}",
        name=name,
        phone_e164=phone_e164,
        email_normalised=email_normalised,
    )


def product(
    business_: Business,
    *,
    name: str = "Test Product",
    category: str | None = None,
) -> Product:
    return Product(
        business_id=business_.id,
        source_product_id=f"src-p-{uuid.uuid4().hex[:10]}",
        name=name,
        category=category,
    )


def variant(
    business_: Business,
    product_: Product,
    *,
    name: str = "Default",
    stock_on_hand: int = 0,
    is_available: bool = False,
) -> ProductVariant:
    return ProductVariant(
        business_id=business_.id,
        product_id=product_.id,
        source_variant_id=f"src-v-{uuid.uuid4().hex[:10]}",
        name=name,
        stock_on_hand=stock_on_hand,
        is_available=is_available,
    )


def order(
    business_: Business,
    customer_: Customer,
    *,
    status: str = OrderStatus.completed.value,
    qualifying: bool = True,
    total: Decimal | str = "0.00",
    ordered_at: datetime | None = None,
) -> CustomerOrder:
    return CustomerOrder(
        business_id=business_.id,
        customer_id=customer_.id,
        source_order_id=f"src-o-{uuid.uuid4().hex[:10]}",
        status=status,
        qualifying=qualifying,
        total_amount=Decimal(str(total)),
        currency="BDT",
        ordered_at=ordered_at or datetime.now(UTC),
    )


def order_item(
    business_: Business,
    order_: CustomerOrder,
    product_: Product,
    *,
    variant_: ProductVariant | None = None,
    quantity: int = 1,
    unit_price: Decimal | str = "0.00",
) -> OrderItem:
    return OrderItem(
        business_id=business_.id,
        order_id=order_.id,
        product_id=product_.id,
        variant_id=variant_.id if variant_ is not None else None,
        product_name_snapshot=product_.name,
        quantity=quantity,
        line_total=Decimal(str(unit_price)) * quantity,
    )


def days_ago(days: int) -> datetime:
    return datetime.now(UTC) - timedelta(days=days)
