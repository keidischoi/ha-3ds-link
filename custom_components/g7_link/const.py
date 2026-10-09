"""G7 연결 — 상수."""

DOMAIN = "g7_link"

CONF_SITE = "site"
CONF_CODE = "code"
CONF_DEVICE_ID = "device_id"
CONF_TOKEN = "token"
CONF_PUSH_URL = "push_url"
CONF_TARGET = "target"
CONF_LOCATION = "location"
CONF_PRINTER_ID = "printer_id"
CONF_EQUIPMENT_ID = "equipment_id"
CONF_NAME = "name"

# 보낼 값을 읽어 올 엔티티 (사이트의 ent_* 칸과 같은 이름)
CONF_HUM = "ent_hum"
CONF_TEMP = "ent_temp"
CONF_STATE = "ent_state"
CONF_PROGRESS = "ent_progress"
CONF_REMAINING = "ent_remaining"
CONF_JOB = "ent_job"
CONF_CAMERA = "camera"

CONF_HUMIDITY_MAX = "humidity_max"
CONF_TEMP_MAX = "temp_max"
CONF_SNAP_PUBLIC = "snap_public"
CONF_DEVICES = "devices"  # 한꺼번에 연결한 통합: 기기 여러 대 [{device_id, token, push_url, name, ent_hum, ent_temp}]
CONF_BULK = "bulk"
CONF_AUTO = "auto"
CONF_ITEMS = "items"
CONF_KEY = "key"  # 여러 대짜리 통합에서 기기를 가리는 이름: p:<사이트 프린터 id> · h:<습도 센서>
CONF_SENSORS = "sensors"
CONF_HA_DEVICE = "ha_device"  # 설정 화면에서만 씀 — 고른 HA 기기에서 센서를 찾아 채움
CONF_INTERVAL = "interval"  # 회원이 고른 보내는 주기 (분) — 사이트가 정한 주기보다 짧을 수 없음

ENTITY_KEYS = (CONF_HUM, CONF_TEMP, CONF_STATE, CONF_PROGRESS, CONF_REMAINING, CONF_JOB)

# 엔티티 칸 → 사이트로 보내는 이름
PAYLOAD_KEYS = {
    CONF_TEMP: "temperature",
    CONF_HUM: "humidity",
    CONF_STATE: "state",
    CONF_PROGRESS: "progress",
    CONF_REMAINING: "remaining_min",
    CONF_JOB: "job",
}

HUB_PATH = "/api/plugins/custom-ha_link/hub/"

DEFAULT_INTERVAL_MIN = 10
DEFAULT_SNAP_GAP_MIN = 5
DEFAULT_SNAP_MAX = 400_000
SNAP_WIDTH = 640

# 「가동 중」으로 보는 상태 글 — 이때만 카메라 사진을 보냄 (사이트와 같은 목록)
ON_STATES = {
    "on", "true", "1", "printing", "print", "running", "busy", "starting", "resuming", "prepare", "preparing",
    "heating", "paused", "pause", "pausing", "printing from sd", "working", "active", "heat", "drying",
    "processing", "self-testing", "leveling", "calibrating", "homing",
}
SKIP_STATES = {"unknown", "unavailable", "none", ""}
