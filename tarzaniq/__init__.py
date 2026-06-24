"""TarzanIQ — local street-photography analytics for the jungle floor.

All processing happens on-device. Photos go in, stats come out.
Compressed photo copies are kept in a separate archive dir; the data
dir holds only derived stats (face embeddings stay in RAM, never
persisted). Data lives in ~/Documents/TarzanIQ Data so the app can
be reinstalled without losing history.
"""

APP_NAME = "TarzanIQ"
APP_VERSION = "1.0.0"
APP_CODENAME = "Silverback"
DEFAULT_PORT = 43117

# Comparability versions (Feature B). Bump MODEL_VERSION when the ONNX models
# change; bump ALGO_VERSION when engagement/stats/detection code changes the
# shape or meaning of outputs. Both feed the per-day processing fingerprint.
MODEL_VERSION = "1"
ALGO_VERSION = "1"
