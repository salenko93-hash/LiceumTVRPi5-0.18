"""Record the exact unittest inventory; all tests use their own isolated fixtures."""
import argparse
import contextlib
import json
from pathlib import Path
import platform
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'server'), str(ROOT / 'tests')]


class Inventory(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.inventory = []

    def addSuccess(self, test):
        super().addSuccess(test)
        self.inventory.append({'test': test.id(), 'status': 'PASS'})

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self.inventory.append({'test': test.id(), 'status': 'SKIP', 'reason': reason})

    def addError(self, test, err):
        super().addError(test, err)
        self.inventory.append({'test': test.id(), 'status': 'ERROR', 'detail': self._exc_info_to_string(err, test)})

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.inventory.append({'test': test.id(), 'status': 'FAIL', 'detail': self._exc_info_to_string(err, test)})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    suite = unittest.defaultTestLoader.discover(str(ROOT / 'tests'))
    with contextlib.redirect_stdout(sys.stderr):
        result = unittest.TextTestRunner(verbosity=2, resultclass=Inventory).run(suite)
    payload = {'platform': platform.platform(), 'python': platform.python_version(), 'total': result.testsRun,
               'successful': result.wasSuccessful(), 'tests': result.inventory}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    else:
        print(json.dumps(payload, ensure_ascii=False))
    sys.exit(0 if result.wasSuccessful() else 1)
