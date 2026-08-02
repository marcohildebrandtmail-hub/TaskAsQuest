"""Constants for the Task as Quest integration."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "taskasquest"

DEFAULT_APP_URL = "https://app.taskasquest.de"

CONF_APP_URL = "app_url"
CONF_AUTH_TOKEN = "auth_token"
CONF_LOGIN_NAME = "login_name"
CONF_PASSWORD = "password"
CONF_TOTP_CODE = "totp_code"
CONF_USER_ID = "user_id"
CONF_RULES = "rules"
CONF_CONFIG_ENTRY_ID = "config_entry_id"

# Rule fields
RULE_ENTITY_ID = "entity_id"
RULE_ID = "id"
RULE_CONDITION = "condition"  # "below", "above", "equals", "not_equals"
RULE_VALUE = "value"
RULE_TASK_TITLE = "task_title"
RULE_DIFFICULTY = "difficulty"  # "easy", "medium", "hard", "epic"
RULE_COOLDOWN = "cooldown"  # Minuten bis der gleiche Task erneut erstellt wird
RULE_ASSIGNEES = "assignees"
RULE_DUE_DATE_OFFSET = "due_date_offset"
RULE_NOTIFY_APP = "notify_app"
RULE_ENABLED = "enabled"
RULE_TRIGGER_MODE = "trigger_mode"

CONDITIONS = ("below", "above", "equals", "not_equals")
DIFFICULTIES = ("easy", "medium", "hard", "epic")
TRIGGER_MODES = ("edge", "level")

DEFAULT_COOLDOWN = 1440  # 24 Stunden
DEFAULT_SCAN_INTERVAL = 60  # Sekunden
DEFAULT_UPDATE_INTERVAL = timedelta(seconds=DEFAULT_SCAN_INTERVAL)
DEFAULT_REQUEST_TIMEOUT = 15
STARTUP_RULE_GRACE = timedelta(minutes=5)

SERVICE_CREATE_QUEST = "create_quest"
SERVICE_ADD_RULES = "add_rules"

STORAGE_VERSION = 1
STORAGE_KEY_PREFIX = DOMAIN
