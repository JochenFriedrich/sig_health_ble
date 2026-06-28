"""Constants for the Glucose Meter device."""

GLUCOSE_SERVICE_UUID      = "00001808-0000-1000-8000-00805f9b34fb"
GLUCOSE_MEASUREMENT_UUID  = "00002a18-0000-1000-8000-00805f9b34fb"
GLUCOSE_CONTEXT_UUID      = "00002a34-0000-1000-8000-00805f9b34fb"
GLUCOSE_FEATURE_UUID      = "00002a51-0000-1000-8000-00805f9b34fb"
RACP_UUID                 = "00002a52-0000-1000-8000-00805f9b34fb"

# ── RACP Op Codes ─────────────────────────────────────────────────────────────
RACP_OP_REPORT_STORED_RECORDS = 0x01
RACP_OP_ABORT                 = 0x03
RACP_OP_RESPONSE              = 0x06
RACP_OPERATOR_ALL             = 0x01

# ── RACP Response Codes ───────────────────────────────────────────────────────
RACP_RESPONSE_SUCCESS    = 0x01
RACP_RESPONSE_NO_RECORDS = 0x06

# ── Measurement flag bits ──────────────────────────────────────────────────────
FLAG_TIME_OFFSET          = 0x01
FLAG_CONCENTRATION_PRESENT = 0x02
FLAG_CONCENTRATION_MOL    = 0x04
FLAG_SENSOR_STATUS        = 0x08
FLAG_CONTEXT_INFO         = 0x10

# ── Context flag bits ─────────────────────────────────────────────────────────
CTX_FLAG_CARBOHYDRATE    = 0x01
CTX_FLAG_MEAL            = 0x02
CTX_FLAG_TESTER_HEALTH   = 0x04
CTX_FLAG_EXERCISE        = 0x08
CTX_FLAG_MEDICATION      = 0x10
CTX_FLAG_MEDICATION_LITERS = 0x20
CTX_FLAG_HBA1C           = 0x40
CTX_FLAG_EXTENDED        = 0x80

# ── Lookup tables ─────────────────────────────────────────────────────────────
SAMPLE_TYPE = {
    0x01: "Capillary Whole Blood", 0x02: "Capillary Plasma",
    0x03: "Venous Whole Blood",    0x04: "Venous Plasma",
    0x05: "Arterial Whole Blood",  0x06: "Arterial Plasma",
    0x07: "Undetermined Whole Blood", 0x08: "Undetermined Plasma",
    0x09: "Interstitial Fluid",    0x0A: "Control Solution",
}
SAMPLE_LOCATION = {
    0x01: "Finger", 0x02: "Alternate Site Test",
    0x03: "Earlobe", 0x04: "Control Solution", 0x0F: "Not Available",
}
MEAL_LABEL = {
    0x01: "Preprandial", 0x02: "Postprandial", 0x03: "Fasting",
    0x04: "Casual", 0x05: "Bedtime",
}
TESTER_LABEL = {
    0x01: "Self", 0x02: "Health Care Professional",
    0x03: "Lab Test", 0x0F: "Not Available",
}
HEALTH_LABEL = {
    0x00: "None", 0x01: "Minor Health Issues", 0x02: "Major Health Issues",
    0x03: "During Menses", 0x04: "Under Stress",
    0x05: "No Health Issues", 0x0F: "Not Available",
}
CARBOHYDRATE_LABEL = {
    0x01: "Breakfast", 0x02: "Lunch", 0x03: "Dinner",
    0x04: "Snack", 0x05: "Drink", 0x06: "Supper", 0x07: "Brunch",
}
MEDICATION_LABEL = {
    0x01: "Rapid Acting Insulin", 0x02: "Short Acting Insulin",
    0x03: "Intermediate Acting Insulin", 0x04: "Long Acting Insulin",
    0x05: "Pre-Mixed Insulin",
}

# ── Units and conversion ───────────────────────────────────────────────────────
UNIT_MOL_PER_L = "mol/L"
UNIT_KG_PER_L  = "kg/L"
MOL_TO_MMOL    = 1000.0
KG_L_TO_MG_DL  = 100000.0

# ── Timing ────────────────────────────────────────────────────────────────────
RACP_WRITE_TIMEOUT             = 5.0
FIRST_RECORD_TIMEOUT           = 20.0
RACP_RESPONSE_TIMEOUT          = 30.0
IDLE_AFTER_LAST_RECORD_TIMEOUT = 3.0
