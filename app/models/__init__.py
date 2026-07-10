from app.models.skincare import SkincareEntry
from app.models.reminder_settings import ReminderSettings
from app.models.push_subscription import PushSubscription
from app.models.reminder_dispatch_log import ReminderDispatchLog

# Gym module models (subpackage imports every gym table so create_all/Alembic see them).
import app.models.gym  # noqa: F401