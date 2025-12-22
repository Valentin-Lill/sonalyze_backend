import pathlib
import sys
import unittest

CURRENT_DIR = pathlib.Path(__file__).resolve()
SIMULATION_DIR = CURRENT_DIR.parents[1]
SRC_DIR = SIMULATION_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from sonalyze_simulation.payload_adapter import normalize_simulation_payload  # noqa: E402


class NormalizeSimulationPayloadTests(unittest.TestCase):
    def test_passthrough_when_room_already_present(self):
        request = {
            "room": {
                "type": "shoebox",
                "dimensions_m": [6.0, 4.0, 2.7],
                "default_material": {"absorption": 0.2, "scattering": 0.1},
            },
            "sources": [{"id": "s1", "position_m": [1.0, 1.0, 1.2]}],
            "microphones": [{"id": "m1", "position_m": [4.0, 2.0, 1.4]}],
            "furniture": [],
            "sample_rate_hz": 16000,
            "max_order": 12,
            "air_absorption": True,
            "rir_duration_s": 2.0,
            "include_rir": False,
        }

        normalized = normalize_simulation_payload(request)
        self.assertEqual(normalized, request)

    def test_room_model_conversion_creates_polygon_and_defaults(self):
        room_model = {
            "version": "1.0",
            "rooms": [
                {
                    "dimensions": {"width": 6.0, "height": 2.7, "depth": 4.0},
                    "walls": [
                        {"start": {"x": -3.0, "y": 0.0, "z": -2.0}, "end": {"x": 3.0, "y": 0.0, "z": -2.0}},
                        {"start": {"x": 3.0, "y": 0.0, "z": -2.0}, "end": {"x": 3.0, "y": 0.0, "z": 2.0}},
                        {"start": {"x": 3.0, "y": 0.0, "z": 2.0}, "end": {"x": -3.0, "y": 0.0, "z": 2.0}},
                        {"start": {"x": -3.0, "y": 0.0, "z": 2.0}, "end": {"x": -3.0, "y": 0.0, "z": -2.0}},
                    ],
                    "furniture": [
                        {
                            "id": "table-1",
                            "position": {"x": 0.0, "y": 0.0, "z": 0.0},
                            "dimensions": {"width": 1.2, "depth": 0.8, "height": 0.75},
                        }
                    ],
                }
            ],
        }

        normalized = normalize_simulation_payload({"room_model": room_model})

        self.assertEqual(normalized["room"]["type"], "polygon")
        self.assertEqual(len(normalized["room"]["corners_m"]), 4)
        self.assertGreaterEqual(len(normalized["furniture"]), 1)
        self.assertEqual(len(normalized["sources"]), 1)
        self.assertEqual(len(normalized["microphones"]), 1)
        self.assertTrue(normalized["sources"][0]["position_m"][2] > 0)
        self.assertTrue(normalized["microphones"][0]["position_m"][2] > 0)

    def test_payload_level_loudspeaker_aliases_are_forwarded(self):
        room_model = {
            "version": "1.0",
            "rooms": [
                {
                    "dimensions": {"width": 6.0, "height": 2.7, "depth": 4.0},
                }
            ],
        }

        request = {
            "room_model": room_model,
            "loudspeakers": [
                {"id": "speaker-a", "position_m": [1.0, 0.0, 1.4]},
                {"id": "speaker-b", "position_m": [0.5, 0.5, 1.4]},
            ],
            "mics": [
                {"id": "mic-a", "position_m": [-1.0, 0.0, 1.2]},
            ],
        }

        normalized = normalize_simulation_payload(request)

        self.assertEqual([src["id"] for src in normalized["sources"]], ["speaker-a", "speaker-b"])
        self.assertEqual([mic["id"] for mic in normalized["microphones"]], ["mic-a"])

    def test_room_model_devices_section_is_used(self):
        room_model = {
            "version": "1.0",
            "rooms": [
                {
                    "dimensions": {"width": 5.0, "height": 2.5, "depth": 4.0},
                    "devices": {
                        "loudspeakers": [
                            {"id": "ls-room", "position_m": [0.0, -1.0, 1.4]},
                        ],
                        "microphones": [
                            {"id": "mic-room", "position_m": [1.0, 0.5, 1.2]},
                        ],
                    },
                }
            ],
        }

        normalized = normalize_simulation_payload({"room_model": room_model})

        self.assertEqual([src["id"] for src in normalized["sources"]], ["ls-room"])
        self.assertEqual([mic["id"] for mic in normalized["microphones"]], ["mic-room"])


if __name__ == "__main__":
    unittest.main()
