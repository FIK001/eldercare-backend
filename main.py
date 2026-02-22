from fastapi import FastAPI, Depends, HTTPException
from sqlmodel import Session, select
from database import create_db_and_tables, engine
from typing import List
from models import DailyCheckin, Alert
from models import User, Caregiver, Reminder, DailyCheckin, Alert
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # For now allow all
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    create_db_and_tables()


def get_session():
    with Session(engine) as session:
        yield session
        
# --------------------------
# Mock SMS Sender
# --------------------------
def send_mock_sms(phone: str, message: str):
    print(f"SMS sent to {phone}: {message}")



@app.get("/")
def read_root():
    return {"message": "ElderCare AI Backend Running"}


# --------------------------
# Create Caregiver
# --------------------------
@app.post("/caregivers/", response_model=Caregiver)
def create_caregiver(caregiver: Caregiver, session: Session = Depends(get_session)):
    session.add(caregiver)
    session.commit()
    session.refresh(caregiver)
    return caregiver


# --------------------------
# Create User
# --------------------------
@app.post("/users/", response_model=User)
def create_user(user: User, session: Session = Depends(get_session)):
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


# --------------------------
# Get All Users
# --------------------------
@app.get("/users/", response_model=List[User])
def get_users(session: Session = Depends(get_session)):
    users = session.exec(select(User)).all()
    return users

# --------------------------
# Daily Check-in
# --------------------------
@app.post("/daily-checkin/")
def daily_checkin(checkin: DailyCheckin, session: Session = Depends(get_session)):

    # Save new check-in
    session.add(checkin)
    session.commit()
    session.refresh(checkin)

    # Get last 5 check-ins for this user
    statement = (
        select(DailyCheckin)
        .where(DailyCheckin.user_id == checkin.user_id)
        .order_by(DailyCheckin.timestamp.desc())
        .limit(5)
    )

    recent_checkins = session.exec(statement).all()

    if len(recent_checkins) >= 3:
        scores = [c.orientation_score for c in recent_checkins]
        avg_score = sum(scores) / len(scores)

        # If current score is significantly lower than average
        if checkin.orientation_score < (avg_score - 1):

            alert = Alert(
                type="cognitive_decline",
                message="Possible cognitive decline detected.",
                user_id=checkin.user_id,
                timestamp=datetime.utcnow()
            )

            session.add(alert)
            session.commit()
            session.refresh(alert)

            return {
                "message": "Check-in saved. Alert triggered.",
                "alert": alert
            }

    return {"message": "Check-in saved. No alert triggered."}
# --------------------------
# Trigger Fall Alert
# --------------------------
@app.post("/trigger-fall/{user_id}")
def trigger_fall(user_id: int, session: Session = Depends(get_session)):

    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    alert = Alert(
        type="fall",
        message=f"Fall detected for {user.name}. Immediate attention required.",
        user_id=user_id
    )

    session.add(alert)
    session.commit()
    session.refresh(alert)
    
    caregiver = session.get(Caregiver, user.caregiver_id)
    if caregiver:
        send_real_sms(
        caregiver.phone,
        f"ALERT: {user.name} has fallen. Immediate attention required."
    )

    make_real_call(
        caregiver.phone,
        f"Emergency alert. {user.name} has fallen and needs immediate assistance."
    )
    return {
        "message": "Fall alert created.",
        "alert": alert
}

# --------------------------
# Voice Input
# --------------------------
@app.post("/voice-input/{user_id}")
def voice_input(user_id: int, payload: dict, session: Session = Depends(get_session)):

    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    text = payload.get("message", "").lower()
    user_language = user.language.lower()
    user_name = user.name

    emergency_keywords = [
        "fall", "help", "i fell", "emergency",
        "mo ti ṣubu", "mo ti subu", "egba mi o", "ran mi lowo",
        "enyem aka", "adawom",
        "taimake ni", "na fadi","who is there", "talo wa ni beyen"
    ]

    # Emergency detection
    for keyword in emergency_keywords:
        if keyword in text:
            alert = Alert(
                type="emergency_phrase",
                message=f"Emergency phrase detected from {user.name}.",
                user_id=user_id
            )

            session.add(alert)
            session.commit()
            session.refresh(alert)

            caregiver = session.get(Caregiver, user.caregiver_id)
            if caregiver:
                send_mock_sms(
                    caregiver.phone,
                    f"ALERT: Emergency phrase detected from {user.name}."
                )

            return {
                "message": "Emergency detected. Alert created.",
                "alert": alert
            }

    # Conversational responses
    if "how are you" in text or "bawo ni" in text or "kedu" in text or "lafiya" in text:

        if user_language == "english":
            return {"response": f"I am doing well, {user_name}. How are you feeling today?"}

        if user_language == "yoruba":
            return {"response": f"Mo wa daadaa, {user_name}. Iwo nko?"}

        if user_language == "igbo":
            return {"response": f"Adim mma, {user_name}. Kedu ka i mere?"}

        if user_language == "hausa":
            return {"response": f"Ina lafiya, {user_name}. Yaya kake ji?"}

    return {"response": f"I am here with you, {user_name}. How can I assist you today?"}



# --------------------------
# Get All Alerts
# --------------------------
@app.get("/alerts/", response_model=List[Alert])
def get_alerts(session: Session = Depends(get_session)):
    alerts = session.exec(select(Alert)).all()
    return alerts


# --------------------------
# Get Alerts For Specific User
# --------------------------
@app.get("/users/{user_id}/alerts", response_model=List[Alert])
def get_user_alerts(user_id: int, session: Session = Depends(get_session)):

    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    statement = select(Alert).where(Alert.user_id == user_id)
    alerts = session.exec(statement).all()
    return alerts


# --------------------------
# Resolve Alert
# --------------------------
@app.put("/alerts/{alert_id}/resolve")
def resolve_alert(alert_id: int, session: Session = Depends(get_session)):

    alert = session.get(Alert, alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    alert.resolved = True
    session.add(alert)
    session.commit()
    session.refresh(alert)

    return {"message": "Alert marked as resolved.", "alert": alert}
# --------------------------
# Create Reminder
# --------------------------
@app.post("/reminders/", response_model=Reminder)
def create_reminder(reminder: Reminder, session: Session = Depends(get_session)):

    user = session.get(User, reminder.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    session.add(reminder)
    session.commit()
    session.refresh(reminder)
    return reminder
# --------------------------
# Get Reminders For Specific User
# --------------------------
@app.get("/users/{user_id}/reminders", response_model=List[Reminder])
def get_user_reminders(user_id: int, session: Session = Depends(get_session)):

    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    statement = select(Reminder).where(Reminder.user_id == user_id)
    reminders = session.exec(statement).all()
    return reminders