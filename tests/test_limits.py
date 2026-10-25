"""Temperature limits from the hardware itself (and the fallbacks when it doesn't say)."""

import unittest
from collections import namedtuple
from unittest import mock

from sparescreen import sensors

Temp = namedtuple("Temp", "label current high critical")

NEW_DRIVER = """
    Temperature
        GPU Current Temp                               : 51.47 C
        GPU Current T.Limit Temp                       : 37.6 C
        GPU Slowdown T.Limit Temp Specification        : N/A
"""
OLD_DRIVER = """
    Temperature
        GPU Current Temp                  : 45 C
        GPU Shutdown Temp                 : 98 C
        GPU Slowdown Temp                 : 95 C
        GPU Max Operating Temp            : 93 C
"""


class NvidiaLimitTest(unittest.TestCase):
    def test_newer_drivers_report_the_margin(self):
        self.assertEqual(sensors.parse_nvidia_limit(NEW_DRIVER, 51.47), 89)

    def test_older_drivers_report_the_slowdown_point(self):
        self.assertEqual(sensors.parse_nvidia_limit(OLD_DRIVER, 45), 95)

    def test_nothing_known(self):
        self.assertIsNone(sensors.parse_nvidia_limit("GPU Current Temp : 40 C", 40))
        self.assertIsNone(sensors.parse_nvidia_limit("", None))


class CpuTableTest(unittest.TestCase):
    def test_families(self):
        self.assertEqual(sensors.cpu_limit("Ryzen 5 7600X"), 95)
        self.assertEqual(sensors.cpu_limit("Ryzen 7 7800X3D"), 89)
        self.assertEqual(sensors.cpu_limit("Ryzen 9 5950X"), 90)
        self.assertEqual(sensors.cpu_limit("Ryzen 7 9700X"), 95)
        self.assertEqual(sensors.cpu_limit("Core i7-12700K"), 100)
        self.assertIsNone(sensors.cpu_limit("Some ARM board"))


class LibreHardwareMonitorLimitsTest(unittest.TestCase):
    def test_intel_distance_to_tjmax(self):
        lhm = sensors.LibreHardwareMonitor()
        hardware = {"Children": [{"Text": "Temperatures", "Children": [
            {"Text": "CPU Package", "Value": "62,0 °C"},
            {"Text": "CPU Core #1", "Value": "60,0 °C"},
            {"Text": "CPU Core #1 Distance to TjMax", "Value": "40,0 °C"},
        ]}]}
        self.assertEqual(lhm._cpu(hardware)["limit"], 100)

    def test_amd_has_no_limit_sensor(self):
        hardware = {"Children": [{"Text": "Temperatures", "Children": [
            {"Text": "Core (Tctl/Tdie)", "Value": "48,0 °C"}]}]}
        self.assertIsNone(sensors.LibreHardwareMonitor()._cpu(hardware)["limit"])

    def test_nvme_warning_temperature(self):
        hardware = {"Text": "KINGSTON SNV3S2000G", "Children": [{"Text": "Temperatures", "Children": [
            {"Text": "Composite Temperature", "Value": "32,0 °C"},
            {"Text": "Warning Temperature", "Value": "74,0 °C"},
            {"Text": "Critical Temperature", "Value": "79,0 °C"}]}]}
        drive = sensors.LibreHardwareMonitor()._drive(hardware)
        self.assertEqual((drive["temp"], drive["temp_limit"]), (32.0, 74.0))


class LinuxLimitTest(unittest.TestCase):
    def limit(self, sensor):
        with mock.patch.object(sensors.psutil, "sensors_temperatures", create=True,
                               return_value={"coretemp": [sensor]}):
            return sensors.linux_cpu_limit()

    def test_high_or_a_bit_under_critical(self):
        self.assertEqual(self.limit(Temp("Package id 0", 50.0, 100.0, 105.0)), 100.0)
        self.assertEqual(self.limit(Temp("Package id 0", 50.0, None, 100.0)), 95.0)
        self.assertIsNone(self.limit(Temp("Package id 0", 50.0, None, None)))


if __name__ == "__main__":
    unittest.main()
