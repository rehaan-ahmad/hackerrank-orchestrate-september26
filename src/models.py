"""
Domain models for the Buy or Wait? pipeline.
Pydantic models for validation and type safety.
"""
from __future__ import annotations
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Optional, List, Set
from pydantic import BaseModel, Field, field_validator


class EventType(str, Enum):
    EXPENSE = "expense"
    SUBSCRIPTION = "subscription"
    INCOME = "income"
    DEBT_PAYMENT = "debt_payment"
    INVESTMENT_PURCHASE = "investment_purchase"
    REFUND = "refund"
    INVESTMENT_VALUATION = "investment_valuation"
    INVESTMENT_SALE = "investment_sale"


class Direction(str, Enum):
    DEBIT = "debit"
    CREDIT = "credit"
    NON_CASH = "non_cash"


class EventStatus(str, Enum):
    SETTLED = "settled"
    PENDING = "pending"
    SCHEDULED = "scheduled"
    CANCELLED = "cancelled"
    FAILED = "failed"
    UNREALIZED = "unrealized"


class Flexibility(str, Enum):
    FIXED = "fixed"
    REDUCIBLE = "reducible"
    STOPPABLE = "stoppable"
    REDUCIBLE_OR_STOPPABLE = "reducible_or_stoppable"


class PaymentMethod(str, Enum):
    FULL_PAYMENT = "full_payment"
    PARTIAL_PAYMENT = "partial_payment"
    INSTALLMENTS = "installments"
    WAIT = "wait"
    NOT_RECOMMENDED = "not_recommended"


class AffordabilityStatus(str, Enum):
    AFFORDABLE_NOW = "affordable_now"
    AFFORDABLE_WITH_PLAN = "affordable_with_plan"
    AFFORDABLE_LATER = "affordable_later"
    NOT_AFFORDABLE = "not_affordable"


class MessageSource(str, Enum):
    EMPLOYER = "employer"
    SERVICE_PROVIDER = "service_provider"
    FINANCIAL_SERVICE = "financial_service"
    BANK = "bank"
    MERCHANT = "merchant"


class RequestType(str, Enum):
    PURCHASE = "purchase"
    TRAVEL = "travel"
    EDUCATION = "education"
    FAMILY_TRANSFER = "family_transfer"
    DEBT_REPAYMENT = "debt_repayment"
    INVESTMENT = "investment"
    HOUSING = "housing"
    EMERGENCY_EXPENSE = "emergency_expense"
    OTHER = "other"


class UserProfile(BaseModel):
    user_id: str
    home_currency: str
    current_available_balance: Decimal
    minimum_balance_to_keep: Decimal
    financial_priorities: Set[str] = Field(default_factory=set)
    protected_categories: Set[str] = Field(default_factory=set)
    reducible_categories: Set[str] = Field(default_factory=set)
    stoppable_categories: Set[str] = Field(default_factory=set)
    accepted_payment_methods: Set[PaymentMethod] = Field(default_factory=set)
    max_installment_months: Optional[int] = None

    @field_validator("financial_priorities", "protected_categories", 
                     "reducible_categories", "stoppable_categories", mode="before")
    @classmethod
    def parse_pipe_separated(cls, v):
        if v is None or (isinstance(v, float) and v != v):  # NaN check
            return set()
        if isinstance(v, str):
            return set(v.split("|")) if v else set()
        return set()

    @field_validator("accepted_payment_methods", mode="before")
    @classmethod
    def parse_payment_methods(cls, v):
        if v is None or (isinstance(v, float) and v != v):
            return set()
        if isinstance(v, str):
            return set(PaymentMethod(p.strip()) for p in v.split("|") if p.strip())
        return set()

    @field_validator("max_installment_months", mode="before")
    @classmethod
    def parse_max_installment(cls, v):
        if v is None or (isinstance(v, float) and v != v):
            return None
        try:
            return int(v)
        except (ValueError, TypeError):
            return None


class FinancialEvent(BaseModel):
    event_id: str
    user_id: str
    event_type: EventType
    description: str
    category: str
    direction: Direction
    amount: Optional[Decimal] = None
    currency: str
    event_date: date
    settlement_date: date
    status: EventStatus
    linked_event_id: Optional[str] = None
    flexibility: Flexibility = Flexibility.FIXED
    minimum_allowed_amount: Optional[Decimal] = None
    # Classification fields (populated by classify_events)
    is_recurring: bool = False
    is_income: bool = False
    is_expense: bool = False
    is_cancelled: bool = False
    is_failed: bool = False
    is_pending: bool = False
    is_settled: bool = False
    is_flexible: bool = False

    @field_validator("amount", mode="before")
    @classmethod
    def parse_amount(cls, v):
        if v is None or (isinstance(v, float) and v != v) or v == "":
            return None
        try:
            return Decimal(str(v))
        except (ValueError, TypeError):
            return None

    @field_validator("minimum_allowed_amount", mode="before")
    @classmethod
    def parse_min_allowed(cls, v):
        if v is None or (isinstance(v, float) and v != v) or v == "":
            return None
        try:
            return Decimal(str(v))
        except (ValueError, TypeError):
            return None

    @field_validator("linked_event_id", mode="before")
    @classmethod
    def parse_linked_event(cls, v):
        if v is None or (isinstance(v, float) and v != v) or v == "":
            return None
        return str(v)

    @field_validator("event_type", mode="before")
    @classmethod
    def parse_event_type(cls, v):
        if isinstance(v, str):
            try:
                return EventType(v.lower())
            except ValueError:
                return EventType.EXPENSE
        return EventType.EXPENSE

    @field_validator("direction", mode="before")
    @classmethod
    def parse_direction(cls, v):
        if isinstance(v, str):
            try:
                return Direction(v.lower())
            except ValueError:
                return Direction.DEBIT
        return Direction.DEBIT

    @field_validator("status", mode="before")
    @classmethod
    def parse_status(cls, v):
        if isinstance(v, str):
            try:
                return EventStatus(v.lower())
            except ValueError:
                return EventStatus.SETTLED
        return EventStatus.SETTLED

    @field_validator("flexibility", mode="before")
    @classmethod
    def parse_flexibility(cls, v):
        if v is None or (isinstance(v, float) and v != v) or v == "":
            return Flexibility.FIXED
        if isinstance(v, str):
            try:
                return Flexibility(v.lower())
            except ValueError:
                return Flexibility.FIXED
        return Flexibility.FIXED


class PaymentOption(BaseModel):
    payment_option_id: str
    request_id: str
    payment_method: PaymentMethod
    payment_amount: Decimal
    number_of_payments: int
    first_payment_date: date
    payment_frequency_days: Optional[int] = None
    financing_fee: Decimal
    total_payable_amount: Decimal

    @field_validator("payment_frequency_days", mode="before")
    @classmethod
    def parse_freq_days(cls, v):
        if v is None or (isinstance(v, float) and v != v) or v == "":
            return None
        try:
            return int(v)
        except (ValueError, TypeError):
            return None

    @field_validator("payment_method", mode="before")
    @classmethod
    def parse_payment_method(cls, v):
        if isinstance(v, str):
            try:
                return PaymentMethod(v.lower())
            except ValueError:
                return PaymentMethod.FULL_PAYMENT
        return PaymentMethod.FULL_PAYMENT


class Message(BaseModel):
    message_id: str
    user_id: str
    request_id: Optional[str] = None
    related_event_id: Optional[str] = None
    sent_at: date
    source_type: MessageSource
    message_text: str

    @field_validator("request_id", "related_event_id", mode="before")
    @classmethod
    def parse_optional_id(cls, v):
        if v is None or (isinstance(v, float) and v != v) or v == "":
            return None
        return str(v)

    @field_validator("source_type", mode="before")
    @classmethod
    def parse_source_type(cls, v):
        if isinstance(v, str):
            try:
                return MessageSource(v.lower())
            except ValueError:
                return MessageSource.EMPLOYER
        return MessageSource.EMPLOYER


class ImageRef(BaseModel):
    image_id: str
    user_id: str
    request_id: str
    related_event_id: str
    image_path: str


class PaymentOptionDetail(BaseModel):
    """Extended payment option with computed fields for decision engine."""
    payment_option_id: str
    payment_method: PaymentMethod
    payment_amount: Decimal
    number_of_payments: int
    first_payment_date: date
    payment_frequency_days: Optional[int]
    financing_fee: Decimal
    total_payable_amount: Decimal
    installment_months: int  # computed


class RequestContext(BaseModel):
    request_id: str
    user_id: str
    request_date: date
    request_type: RequestType
    requested_amount: Decimal
    desired_completion_date: date
    allows_partial_payment: bool
    request_text: str
    request_currency: str
    user_profile: UserProfile
    events: List[FinancialEvent] = Field(default_factory=list)
    payment_options: List[PaymentOptionDetail] = Field(default_factory=list)
    messages: List[Message] = Field(default_factory=list)
    images: List[ImageRef] = Field(default_factory=list)


class ExchangeRate(BaseModel):
    rate_date: date
    from_currency: str
    to_currency: str
    rate: Decimal


class Dataset(BaseModel):
    """Container for all loaded datasets with pre-built indexes."""
    profiles: dict[str, UserProfile]
    events_by_user: dict[str, List[FinancialEvent]]
    events_by_id: dict[str, FinancialEvent]
    rates_index: dict[tuple[date, str, str], Decimal]
    payment_options_by_req: dict[str, List[PaymentOption]]
    messages_by_req: dict[str, List[Message]]
    messages_by_event: dict[str, List[Message]]
    images_by_event: dict[str, ImageRef]
    requests: List[dict]  # raw request rows for iteration


def build_fx_index(rates_df) -> dict[tuple[date, str, str], Decimal]:
    """Build lookup index for exchange rates: (rate_date, from_currency, to_currency) -> rate."""
    index = {}
    for _, row in rates_df.iterrows():
        key = (row["rate_date"], row["from_currency"], row["to_currency"])
        index[key] = Decimal(str(row["rate"]))
    return index