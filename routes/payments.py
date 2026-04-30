from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from models.database import get_db, User, Payment
from routes.auth import get_user
import uuid

router = APIRouter()

class FundIn(BaseModel):
    recipient_id: str; amount: float
    card_number: str; expiration: str; cvv: str; passcode: str

class WithdrawIn(BaseModel):
    amount: float; bank_account: str | None = None

@router.post("/fund")
def fund_player(body: FundIn, db: Session = Depends(get_db),
                user: User = Depends(get_user)):
    recipient = db.query(User).filter(User.id == body.recipient_id).first()
    if not recipient:
        raise HTTPException(404, "Recipient not found")
    if body.amount <= 0:
        raise HTTPException(400, "Amount must be positive")
    # In production: integrate real payment gateway (Stripe, Paystack, etc.)
    payment = Payment(id=str(uuid.uuid4()), payer_id=user.id,
                      recipient_id=body.recipient_id, amount=body.amount)
    recipient.earned += body.amount
    db.add(payment); db.commit()
    return {"success": True, "transaction_id": payment.id}

@router.post("/withdraw")
def withdraw(body: WithdrawIn, db: Session = Depends(get_db),
             user: User = Depends(get_user)):
    if body.amount > user.earned:
        raise HTTPException(400, "Insufficient balance")
    user.earned -= body.amount
    db.commit()
    return {"success": True, "remaining_balance": user.earned}