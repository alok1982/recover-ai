"""Pydantic models: API requests and Gemini response schemas."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Country = Literal["IN", "MY"]
Lang = Literal["en", "hi", "ms"]
ScamType = Literal[
    "digital_arrest", "fake_courier_customs", "investment_trading", "job_task", "kyc_update",
    "loan_app", "romance", "phishing_link", "other",
]
PaymentMethod = Literal["UPI", "IMPS", "NEFT", "RTGS", "DuitNow", "IBG", "card", "wallet", "other"]

EXTRACTION_FIELDS = [
    "reference_id", "amount", "currency", "occurred_at", "payment_method", "payer_bank",
    "beneficiary.name", "beneficiary.account_or_vpa", "beneficiary.bank", "beneficiary.ifsc_or_code",
    "scammer_contacts", "urls", "scam_type",
]


# ---------------------------------------------------------------- PRD §9.1 schema (canonical)
class Beneficiary(BaseModel):
    name: str | None = None
    account_or_vpa: str | None = None
    bank: str | None = None
    ifsc_or_code: str | None = None


class Extraction(BaseModel):
    reference_id: str | None = None
    amount: float | None = None
    currency: str | None = None
    occurred_at: str | None = None
    payment_method: PaymentMethod | None = None
    payer_bank: str | None = None
    beneficiary: Beneficiary = Field(default_factory=Beneficiary)
    scammer_contacts: list[str] = Field(default_factory=list)
    urls: list[str] = Field(default_factory=list)
    scam_type: ScamType = "other"
    narrative_en: str = ""
    narrative_local: str = ""
    confidence: dict[str, float] = Field(default_factory=dict)
    missing_fields: list[str] = Field(default_factory=list)


# Gemini's response_schema cannot express free-form maps, so confidence is sent as a fixed object
# and converted to the canonical dict above.
class FieldConfidence(BaseModel):
    reference_id: float | None = None
    amount: float | None = None
    currency: float | None = None
    occurred_at: float | None = None
    payment_method: float | None = None
    payer_bank: float | None = None
    beneficiary_name: float | None = None
    beneficiary_account_or_vpa: float | None = None
    beneficiary_bank: float | None = None
    beneficiary_ifsc_or_code: float | None = None
    scammer_contacts: float | None = None
    urls: float | None = None
    scam_type: float | None = None


class ExtractionLLM(BaseModel):
    reference_id: str | None
    amount: float | None
    currency: str | None
    occurred_at: str | None
    payment_method: PaymentMethod | None
    payer_bank: str | None
    beneficiary: Beneficiary
    scammer_contacts: list[str]
    urls: list[str]
    scam_type: ScamType
    narrative_en: str
    narrative_local: str
    confidence: FieldConfidence
    missing_fields: list[str]

    def to_canonical(self) -> Extraction:
        conf = {}
        for k, v in self.confidence.model_dump().items():
            if v is None:
                continue
            key = k.replace("beneficiary_", "beneficiary.", 1) if k.startswith("beneficiary_") else k
            conf[key] = max(0.0, min(1.0, float(v)))
        d = self.model_dump(exclude={"confidence"})
        return Extraction(**d, confidence=conf)


class Transcript(BaseModel):
    transcript: str
    language: str


class DraftPair(BaseModel):
    en: str
    local: str


class GuardResult(BaseModel):
    is_recovery_scam: bool
    reason: str
    route: Literal["light", "full"] = "full"  # F17: can this turn be answered from the case summary alone?


# ---------------------------------------------------------------- API requests
class CreateCaseReq(BaseModel):
    country: Country = "IN"
    language: Lang = "en"


class UpdateCaseReq(BaseModel):
    country: Country | None = None
    language: Lang | None = None


class ChatReq(BaseModel):
    text: str | None = Field(default=None, max_length=4000)
    audioPath: str | None = None
    evidenceIds: list[str] = Field(default_factory=list)
    trigger: str | None = None  # e.g. "card_action": no user text, co-pilot continues from latest system_event


class UploadUrlReq(BaseModel):
    mimeType: str
    sizeBytes: int | None = None
    purpose: Literal["evidence", "voice"] = "evidence"


class RegisterEvidenceReq(BaseModel):
    type: Literal["image", "text", "audio"]
    gcsPath: str | None = None
    mimeType: str | None = None
    textContent: str | None = Field(default=None, max_length=20000)
    fileName: str | None = None


class ExtractionPatch(BaseModel):
    fields: dict[str, object] = Field(default_factory=dict)  # dotted keys e.g. "beneficiary.bank"
    confirm: bool = False


class StepPatch(BaseModel):
    status: Literal["pending", "done"] = "done"
    reference: str | None = Field(default=None, max_length=120)


class ClockReq(BaseModel):
    addDays: float | None = None
    jumpToDay: int | None = None  # relative to report_bank done time (falls back to incident time)
    reset: bool = False


class GuardReq(BaseModel):
    text: str = Field(max_length=8000)


class SendToBankReq(BaseModel):
    consent: bool
    consentVersion: str = "v1"


class DecisionReq(BaseModel):
    decision: Literal["APPROVE_HOLD", "REQUEST_INFO", "REJECT"]
    note: str | None = Field(default=None, max_length=1000)
