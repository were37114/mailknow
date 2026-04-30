#!/bin/bash
# Run IMAP integration tests
# Usage: ./run_imap_tests.sh [email] [password]

set -e

# Check for credentials
if [ -z "$MAILMIND_TEST_EMAIL" ]; then
    if [ -n "$1" ]; then
        export MAILMIND_TEST_EMAIL="$1"
    else
        echo "Error: MAILMIND_TEST_EMAIL not set"
        echo "Usage: $0 [email] [password]"
        echo "Or set environment variables:"
        echo "  export MAILMIND_TEST_EMAIL=your-email@example.com"
        echo "  export MAILMIND_TEST_PASSWORD=your-password"
        exit 1
    fi
fi

if [ -z "$MAILMIND_TEST_PASSWORD" ]; then
    if [ -n "$2" ]; then
        export MAILMIND_TEST_PASSWORD="$2"
    else
        echo "Error: MAILMIND_TEST_PASSWORD not set"
        echo "Usage: $0 [email] [password]"
        exit 1
    fi
fi

# Run tests
cd "$(dirname "$0")/../.."
python -m pytest tests/integration/test_imap_real.py -m integration -v --tb=short "$@"
