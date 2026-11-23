"""Shared test setup.

The coordinator tests need Home Assistant's test plugin
(``pip install -r requirements_test.txt``). Without it only the parser and
client tests run.
"""

import pytest

try:
    import pytest_homeassistant_custom_component  # noqa: F401
except ImportError:

    @pytest.fixture
    def socket_enabled():
        """Stand-in: without the plugin nothing blocks sockets."""
