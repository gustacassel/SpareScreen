import io
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from sparescreen import sensors

FIXTURES = Path(__file__).parent / "fixtures"
MB = 1024 ** 2


def _lhm_response():
    return io.BytesIO((FIXTURES / "lhm.json").read_bytes())


class NumberParsingTest(unittest.TestCase):
    def test_number_handles_both_decimal_separators(self):
        self.assertEqual(sensors._number("45,3 °C"), 45.3)
        self.assertEqual(sensors._number("45.3 °C"), 45.3)
        self.assertIsNone(sensors._number("[N/A]"))
        self.assertIsNone(sensors._number(None))

    def test_values_with_units(self):
        self.assertEqual(sensors._with_unit("512,0 KB/s", sensors._RATE_UNITS), 512 * 1024)
        self.assertEqual(sensors._with_unit("6144,0 MB", sensors._SIZE_UNITS), 6144 * MB)
        self.assertIsNone(sensors._with_unit("-", sensors._SIZE_UNITS))


class LibreHardwareMonitorTest(unittest.TestCase):
    def read(self):
        with mock.patch.object(sensors.urllib.request, "urlopen", return_value=_lhm_response()):
            return sensors.LibreHardwareMonitor().read()

    def test_cpu(self):
        cpu = self.read()["cpu"]
        self.assertEqual(cpu["temp"], 61.5)  # Tctl/Tdie is preferred over the CCD sensors
        self.assertEqual(cpu["power"], 72.4)
        self.assertEqual(cpu["clock"], 4500.0)
        self.assertEqual(cpu["clock_max"], 5400.0)  # "Effective" clocks are ignored

    def test_prefers_dedicated_gpu_over_integrated(self):
        gpu = self.read()["gpu"]
        self.assertEqual(gpu["name"], "Radeon RX 7800 XT")
        self.assertEqual(gpu["percent"], 88.0)
        self.assertEqual(gpu["temp"], 58.0)
        self.assertEqual(gpu["power"], 210.5)
        self.assertEqual(gpu["mem_used"], 6144 * MB)
        self.assertEqual(gpu["mem_total"], 16368 * MB)
        self.assertEqual(gpu["clock"], 2430.0)
        self.assertEqual(gpu["fan"], 42.0)
        self.assertFalse(gpu["integrated"])

    def test_fans_hide_empty_headers_and_keep_gpu_fan(self):
        fans = {f["name"]: f for f in self.read()["fans"]}
        self.assertEqual(set(fans), {"Fan 1", "Fan 3", "GPU"})  # Fan 2 is at 0 rpm
        self.assertIsNone(fans["Fan 1"]["percent"])  # "-" means not controllable
        self.assertEqual(fans["Fan 3"]["percent"], 65.0)
        self.assertTrue(fans["GPU"]["gpu"])
        self.assertEqual(fans["GPU"]["rpm"], 1650.0)

    def test_drives(self):
        (drive,) = self.read()["drives"]
        self.assertEqual(drive["name"], "Example NVMe SSD")
        self.assertEqual(drive["temp"], 39.0)
        self.assertEqual(drive["read"], 1.5 * MB)

    def test_unreachable_server_backs_off(self):
        lhm = sensors.LibreHardwareMonitor()
        with mock.patch.object(sensors.urllib.request, "urlopen", side_effect=OSError) as urlopen:
            self.assertIsNone(lhm.read())
            self.assertIsNone(lhm.read())
        self.assertEqual(urlopen.call_count, 1)  # the second read waits instead of retrying


class NvidiaGpuTest(unittest.TestCase):
    def test_parses_nvidia_smi_output(self):
        gpu = sensors.NvidiaGpu()
        gpu.exe = "nvidia-smi"
        out = "NVIDIA GeForce RTX 4070, 35, 52, 2048, 12282, 80.50, [N/A], 1800, 10501\n"
        done = subprocess.CompletedProcess([], 0, stdout=out, stderr="")
        with mock.patch.object(sensors.subprocess, "run", return_value=done):
            data = gpu.read()
        self.assertEqual(data["name"], "RTX 4070")
        self.assertEqual(data["percent"], 35.0)
        self.assertEqual(data["mem_total"], 12282 * MB)
        self.assertIsNone(data["fan"])
        self.assertEqual(data["mem_clock"], 10501.0)

    def test_missing_tool_returns_none(self):
        gpu = sensors.NvidiaGpu()
        gpu.exe = None
        self.assertIsNone(gpu.read())


class LinuxAmdGpuTest(unittest.TestCase):
    def test_reads_amdgpu_sysfs(self):
        with tempfile.TemporaryDirectory() as drm:
            dev = os.path.join(drm, "card0", "device")
            hwmon = os.path.join(dev, "hwmon", "hwmon3")
            os.makedirs(hwmon)
            files = {
                os.path.join(dev, "gpu_busy_percent"): "42\n",
                os.path.join(dev, "mem_info_vram_used"): str(2 * 1024 ** 3),
                os.path.join(dev, "mem_info_vram_total"): str(8 * 1024 ** 3),
                os.path.join(dev, "product_name"): "AMD Radeon RX 6600\n",
                os.path.join(dev, "pp_dpm_sclk"): "0: 500Mhz\n1: 2100Mhz *\n",
                os.path.join(hwmon, "temp1_input"): "55000\n",
                os.path.join(hwmon, "power1_average"): "120000000\n",
                os.path.join(hwmon, "fan1_input"): "1300\n",
            }
            for path, text in files.items():
                with open(path, "w", encoding="utf-8") as f:
                    f.write(text)
            gpu = sensors.linux_amd_gpu(drm)
        self.assertEqual(gpu["name"], "Radeon RX 6600")
        self.assertEqual(gpu["percent"], 42.0)
        self.assertEqual(gpu["temp"], 55.0)
        self.assertEqual(gpu["power"], 120.0)
        self.assertEqual(gpu["clock"], 2100.0)
        self.assertEqual(gpu["fan_rpm"], 1300.0)
        self.assertIsNone(gpu["mem_clock"])  # no pp_dpm_mclk file

    def test_no_amd_card(self):
        with tempfile.TemporaryDirectory() as drm:
            self.assertIsNone(sensors.linux_amd_gpu(drm))


class SensorsTest(unittest.TestCase):
    def test_nvidia_smi_wins_over_other_gpu_sources(self):
        s = sensors.Sensors()
        s.lhm = mock.Mock(read=mock.Mock(return_value={"cpu": {}, "gpu": {"name": "from LHM"}, "fans": [],
                                                       "drives": []}))
        s.nvidia = mock.Mock(read=mock.Mock(return_value={"name": "from nvidia-smi", "fan": 30.0}))
        data = s.read()
        self.assertEqual(data["gpu"]["name"], "from nvidia-smi")
        self.assertEqual([f["name"] for f in data["fans"]], ["GPU"])  # GPU fan added from nvidia-smi
        self.assertIsNone(data["hint"])

    def test_hint_when_librehardwaremonitor_is_not_running(self):
        s = sensors.Sensors()
        s.lhm = mock.Mock(read=mock.Mock(return_value=None))
        s.nvidia = mock.Mock(read=mock.Mock(return_value=None))
        data = s.read()
        self.assertIsNone(data["cpu_temp"])
        self.assertEqual(data["hint"], "open LibreHardwareMonitor")


if __name__ == "__main__":
    unittest.main()
