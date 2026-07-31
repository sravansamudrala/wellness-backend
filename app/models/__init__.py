from app.models.user import User
from app.models.password_reset_token import PasswordResetToken
from app.models.skincare import SkincareEntry, SkincareHabit, SkincareEntryHabit
from app.models.reminder_settings import ReminderSettings
from app.models.push_subscription import PushSubscription
from app.models.reminder_dispatch_log import ReminderDispatchLog
from app.models.water import WaterEntry, WaterSettings
from app.models.food import FoodEntry

# Gym module models (subpackage imports every gym table so create_all/Alembic see them).
import app.models.gym  # noqa: F401