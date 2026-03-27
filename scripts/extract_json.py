#!/usr/bin/env python3
"""
JSON Test Report Extraction Utility

Parses pytest JSON test reports and provides access to test results.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Optional


class TestReportExtractor:
    """Extract and query test results from JSON report."""
    
    def __init__(self, json_path: str):
        """
        Initialize extractor with JSON file path.
        
        Args:
            json_path: Path to the JSON test report file
        """
        self.json_path = Path(json_path)
        self.data = None
        self.tests = []
        self._load_json()
    
    def _load_json(self):
        """Load and parse JSON file."""
        if not self.json_path.exists():
            raise FileNotFoundError(f"JSON file not found: {self.json_path}")
        
        try:
            with open(self.json_path, 'r') as f:
                self.data = json.load(f)
            
            # Extract tests array
            if 'tests' in self.data:
                self.tests = self.data['tests']
            else:
                raise ValueError("JSON file does not contain 'tests' key")
                
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON file: {e}")
    
    def get_test_count(self) -> int:
        """
        Get the total number of tests in the report.
        
        Returns:
            Total number of tests
        """
        return len(self.tests)
    
    def get_test_param(self, testID: int, param: str) -> Optional[Any]:
        """
        Get a specific parameter value for a test by its ID.
        
        Args:
            testID: Test index (0-based)
            param: Parameter name to retrieve (e.g., 'test_name', 'status', 'message')
        
        Returns:
            Value of the parameter, or None if not found
        
        Raises:
            IndexError: If testID is out of range
        """
        if testID < 0 or testID >= len(self.tests):
            raise IndexError(f"testID {testID} out of range (0-{len(self.tests)-1})")
        
        test = self.tests[testID]
        return test.get(param, None)
    
    def get_test_by_id(self, testID: int) -> dict:
        """
        Get complete test data by ID.
        
        Args:
            testID: Test index (0-based)
        
        Returns:
            Complete test dictionary
        
        Raises:
            IndexError: If testID is out of range
        """
        if testID < 0 or testID >= len(self.tests):
            raise IndexError(f"testID {testID} out of range (0-{len(self.tests)-1})")
        
        return self.tests[testID]
    
    def get_all_tests(self) -> list:
        """Get all tests."""
        return self.tests
    
    def get_test_summary(self) -> dict:
        """
        Get summary statistics of test results.
        
        Returns:
            Dictionary with pass/fail/xfail counts
        """
        summary = {
            'total': len(self.tests),
            'pass': 0,
            'fail': 0,
            'xfail': 0,
            'skip': 0,
            'other': 0
        }
        
        for test in self.tests:
            status = test.get('status', 'unknown').lower()
            if status in summary:
                summary[status] += 1
            else:
                summary['other'] += 1
        
        return summary


def main():
    parser = argparse.ArgumentParser(
        description='Extract and query test results from JSON report'
    )
    parser.add_argument(
        '--json-dir',
        type=str,
        required=True,
        help='Path to JSON test report file'
    )
    parser.add_argument(
        '--test-id',
        type=int,
        help='Test ID to query (0-based index)'
    )
    parser.add_argument(
        '--param',
        type=str,
        help='Parameter name to extract (e.g., test_name, status, message)'
    )
    parser.add_argument(
        '--summary',
        action='store_true',
        help='Show test summary statistics'
    )
    parser.add_argument(
        '--list-tests',
        action='store_true',
        help='List all test names with IDs'
    )
    
    args = parser.parse_args()
    
    try:
        # Initialize extractor
        extractor = TestReportExtractor(args.json_dir)
        
        # Show summary if requested
        if args.summary:
            summary = extractor.get_test_summary()
            print(f"\n{'='*60}")
            print(f"Test Summary")
            print(f"{'='*60}")
            print(f"Total tests:  {summary['total']}")
            print(f"Passed:       {summary['pass']}")
            print(f"Failed:       {summary['fail']}")
            print(f"Expected Fail: {summary['xfail']}")
            print(f"Skipped:      {summary['skip']}")
            print(f"Other:        {summary['other']}")
            print(f"{'='*60}\n")
            return 0
        
        # List all tests if requested
        if args.list_tests:
            print(f"\n{'='*60}")
            print(f"Test List (Total: {extractor.get_test_count()})")
            print(f"{'='*60}")
            for i, test in enumerate(extractor.get_all_tests()):
                status = test.get('status', 'unknown').upper()
                test_name = test.get('test_name', 'unknown')
                print(f"[{i}] [{status:6s}] {test_name}")
            print(f"{'='*60}\n")
            return 0
        
        # Query specific test parameter
        if args.test_id is not None:
            if args.param:
                value = extractor.get_test_param(args.test_id, args.param)
                print(value)
            else:
                # Print entire test
                test = extractor.get_test_by_id(args.test_id)
                print(json.dumps(test, indent=2))
            return 0
        
        # Default: show count
        count = extractor.get_test_count()
        print(f"Total tests: {count}")
        return 0
        
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except IndexError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
