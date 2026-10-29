import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

path = Path(__file__).resolve().parents[1] / 'scripts/validate-p201-termination-background.py'
spec = importlib.util.spec_from_file_location('restoration_test', path)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
BASE = '/sys/bus/iio/devices/iio:device0/'
def snapshot(mode='slow_attack', gain='63.000000 dB'):
    fields = {'out_altvoltage0_RX_LO_frequency': '2455000000',
              'in_voltage_sampling_frequency': '2100000',
              'in_voltage_rf_bandwidth': '1500000',
              'in_voltage0_gain_control_mode': mode,
              'in_voltage0_hardwaregain': gain,
              'in_voltage0_rf_port_select': 'A_BALANCED',
              'in_voltage1_gain_control_mode': 'manual',
              'in_voltage1_hardwaregain': '20.000000 dB',
              'in_voltage1_rf_port_select': 'A_BALANCED',
              'scan_elements/in_voltage0_en': '0', 'buffer/enable': '0'}
    return ''.join(BASE+k+'\n'+v+'\n' for k,v in fields.items())
class RestorationTest(unittest.TestCase):
    def check(self, before, after, accepted):
        with patch.object(m, 'ssh', return_value=after), patch.object(m.time, 'sleep'):
            if accepted:
                self.assertEqual(m.restoration(before), after)
            else:
                with self.assertRaises(RuntimeError): m.restoration(before)
    def test_agc_gain_drift(self):
        for mode in ('slow_attack','fast_attack','hybrid'):
            self.check(snapshot(mode), snapshot(mode,'71.000000 dB'), True)
    def test_manual_gain_drift_rejected(self):
        self.check(snapshot('manual'), snapshot('manual','71.000000 dB'), False)
    def test_mode_change_rejected(self):
        self.check(snapshot(), snapshot('manual'), False)
    def test_other_changes_rejected(self):
        before=snapshot()
        for old,new in [('2455000000','2456000000'),('2100000','2000000'),('1500000','1400000'),
                        ('A_BALANCED','B_BALANCED'),('20.000000 dB','21.000000 dB'),
                        ('in_voltage0_en\n0','in_voltage0_en\n1'),('buffer/enable\n0','buffer/enable\n1')]:
            self.check(before,before.replace(old,new),False)
    def test_missing_field_rejected(self):
        self.check(snapshot(),snapshot().replace(BASE+'in_voltage0_hardwaregain\n63.000000 dB\n',''),False)
    def test_unknown_mode_gain_drift_rejected(self):
        self.check(snapshot('unknown'),snapshot('unknown','71.000000 dB'),False)
    def test_unchanged(self):
        self.check(snapshot(),snapshot(),True)
if __name__ == '__main__': unittest.main()
