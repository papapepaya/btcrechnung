from pydantic import BaseModel
from typing import Optional, List, Dict
from datetime import date
from enum import Enum


class ExpenseCategory(str, Enum):
    EQUIPMENT = "equipment"
    EQUIPMENT_REPAIR = "equipment_repair"
    SOFTWARE = "software"
    STUDIO_SUPPLIES = "studio_supplies"
    OFFICE_SUPPLIES = "office_supplies"
    INTERNET_PHONE = "internet_phone"
    RENT = "rent"
    MARKETING = "marketing"
    WEBSITE = "website"
    TRAVEL = "travel"
    VEHICLE = "vehicle"
    EDUCATION = "education"
    INSURANCE = "insurance"
    LEGAL_TAX = "legal_tax"
    BANK_FEES = "bank_fees"
    OTHER = "other"


CATEGORY_LABELS = {
    "equipment": "Equipment",
    "equipment_repair": "Reparatur/Wartung",
    "software": "Software",
    "studio_supplies": "Studio-Bedarf",
    "office_supplies": "Büro",
    "internet_phone": "Internet/Telefon",
    "rent": "Miete",
    "marketing": "Marketing",
    "website": "Website",
    "travel": "Fahrtkosten",
    "vehicle": "Kfz",
    "education": "Weiterbildung",
    "insurance": "Versicherung",
    "legal_tax": "Steuerberatung",
    "bank_fees": "Bankgebühren",
    "other": "Sonstiges",
}

CATEGORY_EUER_LINE = {
    "equipment": 41,
    "equipment_repair": 48,
    "software": 48,
    "studio_supplies": 35,
    "office_supplies": 48,
    "internet_phone": 48,
    "rent": 45,
    "marketing": 46,
    "website": 46,
    "travel": 43,
    "vehicle": 43,
    "education": 48,
    "insurance": 48,
    "legal_tax": 48,
    "bank_fees": 48,
    "other": 48,
}


class ExpensePaymentMethod(str, Enum):
    BANK_TRANSFER = "bank_transfer"
    CREDIT_CARD = "credit_card"
    CASH = "cash"
    PAYPAL = "paypal"
    BITCOIN = "bitcoin"


PAYMENT_METHOD_LABELS = {
    "bank_transfer": "Überweisung",
    "credit_card": "Kreditkarte",
    "cash": "Bar",
    "paypal": "PayPal",
    "bitcoin": "Bitcoin",
}


class ExpenseCreate(BaseModel):
    date: date
    category: ExpenseCategory
    description: str
    vendor: Optional[str] = None
    amount: float
    payment_method: ExpensePaymentMethod = ExpensePaymentMethod.BANK_TRANSFER
    notes: Optional[str] = None


class Expense(ExpenseCreate):
    id: str


class InvoiceRecord(BaseModel):
    id: str
    date: date
    customer_name: str
    customer_address: str
    amount: float
    items_description: str
    payment_received: bool = False
    payment_date: Optional[date] = None
    invoice_filename: Optional[str] = None


class MonthlySummary(BaseModel):
    year: int
    month: int
    total_income: float
    total_expenses: float
    profit: float
    income_count: int
    expense_count: int
    expenses_by_category: Dict[str, float] = {}


class YearlySummary(BaseModel):
    year: int
    total_income: float
    total_expenses: float
    profit: float
    monthly_breakdown: List[MonthlySummary] = []


class EURData(BaseModel):
    year: int
    business_name: str
    business_address: str
    tax_id: str
    gross_revenue: float
    material_costs: float
    depreciation: float
    vehicle_costs: float
    rent_costs: float
    advertising_costs: float
    other_business_expenses: float
    operating_result: float
