import json
from database import get_db
from models import Event
import uuid

def import_events_from_json():
    with open("events.json", "r", encoding="utf-8") as f:
        events = json.load(f)
        events = events["events"]

    db = next(get_db())

    for item in events:
        event = Event(
            id=item.get("event_id"),
            title=item.get("title"),
            summary=item.get("summary"),
            start_time=item.get("start_time"),
            end_time=item.get("end_time"),
            location=item.get("location"),
            campus=item.get("campus"),
            organizer=item.get("organizer"),
            source_id = None,
            source_url=item.get("source_url"),
            tags=item.get("tags"),
        )
        db.add(event)
    db.commit()
    db.close()

if __name__ == "__main__":
    import_events_from_json()