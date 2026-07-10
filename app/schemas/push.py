from pydantic import BaseModel


class PushSubscriptionKeys(BaseModel):
    p256dh: str
    auth: str


class PushSubscriptionRequest(BaseModel):
    """Matches the browser's `subscription.toJSON()` shape."""

    endpoint: str
    keys: PushSubscriptionKeys