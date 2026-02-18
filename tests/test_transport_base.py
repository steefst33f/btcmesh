"""Tests for transport/base.py — abstract transport interface and exceptions.

Tests verify:
- Exception hierarchy and inheritance
- ABC enforcement (all methods must be implemented)
- Contract behavior (context manager, state transitions)
- Module import structure
"""
import unittest

from transport.base import (
    BaseTransport,
    MessageHandler,
    TransportConnectionError,
    TransportError,
    TransportSendError,
)


# ---------------------------------------------------------------------------
# Helpers: minimal concrete stub for testing
# ---------------------------------------------------------------------------


class StubTransport(BaseTransport):
    """Minimal concrete implementation for testing BaseTransport contract."""

    def __init__(self):
        self._connected = False
        self._node_id = None
        self._handler = None
        self.disconnect_called = False

    def connect(self, device_path=None):
        self._connected = True
        self._node_id = "stub_node_01"

    def disconnect(self):
        self._connected = False
        self._node_id = None
        self.disconnect_called = True

    def send(self, message, destination):
        if not self._connected:
            raise TransportConnectionError("Not connected")

    def set_message_handler(self, handler):
        self._handler = handler

    def remove_message_handler(self):
        self._handler = None

    @property
    def is_connected(self):
        return self._connected

    @property
    def local_node_id(self):
        return self._node_id


# ---------------------------------------------------------------------------
# Exception hierarchy
# ---------------------------------------------------------------------------


class TestExceptionHierarchy(unittest.TestCase):
    """Verify exception classes and their inheritance."""

    def test_transport_error_is_exception(self):
        self.assertTrue(issubclass(TransportError, Exception))

    def test_connection_error_is_transport_error(self):
        self.assertTrue(issubclass(TransportConnectionError, TransportError))

    def test_send_error_is_transport_error(self):
        self.assertTrue(issubclass(TransportSendError, TransportError))

    def test_connection_error_not_subclass_of_send_error(self):
        self.assertFalse(issubclass(TransportConnectionError, TransportSendError))

    def test_send_error_not_subclass_of_connection_error(self):
        self.assertFalse(issubclass(TransportSendError, TransportConnectionError))

    def test_does_not_shadow_builtin_connection_error(self):
        self.assertIsNot(TransportConnectionError, ConnectionError)
        self.assertFalse(issubclass(TransportConnectionError, ConnectionError))

    def test_exception_with_message(self):
        err = TransportConnectionError("No device found")
        self.assertEqual(str(err), "No device found")

    def test_send_error_with_message(self):
        err = TransportSendError("Device disconnected")
        self.assertEqual(str(err), "Device disconnected")

    def test_connection_error_caught_by_base_class(self):
        with self.assertRaises(TransportError):
            raise TransportConnectionError("test")

    def test_send_error_caught_by_base_class(self):
        with self.assertRaises(TransportError):
            raise TransportSendError("test")


# ---------------------------------------------------------------------------
# ABC enforcement
# ---------------------------------------------------------------------------


class TestABCEnforcement(unittest.TestCase):
    """Verify that BaseTransport cannot be instantiated without all methods."""

    def test_cannot_instantiate_base_transport(self):
        with self.assertRaises(TypeError):
            BaseTransport()

    def test_missing_connect_raises_type_error(self):
        class Incomplete(BaseTransport):
            def disconnect(self): pass
            def send(self, message, destination): pass
            def set_message_handler(self, handler): pass
            def remove_message_handler(self): pass
            @property
            def is_connected(self): return False
            @property
            def local_node_id(self): return None

        with self.assertRaises(TypeError):
            Incomplete()

    def test_missing_disconnect_raises_type_error(self):
        class Incomplete(BaseTransport):
            def connect(self, device_path=None): pass
            def send(self, message, destination): pass
            def set_message_handler(self, handler): pass
            def remove_message_handler(self): pass
            @property
            def is_connected(self): return False
            @property
            def local_node_id(self): return None

        with self.assertRaises(TypeError):
            Incomplete()

    def test_missing_send_raises_type_error(self):
        class Incomplete(BaseTransport):
            def connect(self, device_path=None): pass
            def disconnect(self): pass
            def set_message_handler(self, handler): pass
            def remove_message_handler(self): pass
            @property
            def is_connected(self): return False
            @property
            def local_node_id(self): return None

        with self.assertRaises(TypeError):
            Incomplete()

    def test_missing_set_message_handler_raises_type_error(self):
        class Incomplete(BaseTransport):
            def connect(self, device_path=None): pass
            def disconnect(self): pass
            def send(self, message, destination): pass
            def remove_message_handler(self): pass
            @property
            def is_connected(self): return False
            @property
            def local_node_id(self): return None

        with self.assertRaises(TypeError):
            Incomplete()

    def test_missing_remove_message_handler_raises_type_error(self):
        class Incomplete(BaseTransport):
            def connect(self, device_path=None): pass
            def disconnect(self): pass
            def send(self, message, destination): pass
            def set_message_handler(self, handler): pass
            @property
            def is_connected(self): return False
            @property
            def local_node_id(self): return None

        with self.assertRaises(TypeError):
            Incomplete()

    def test_missing_is_connected_raises_type_error(self):
        class Incomplete(BaseTransport):
            def connect(self, device_path=None): pass
            def disconnect(self): pass
            def send(self, message, destination): pass
            def set_message_handler(self, handler): pass
            def remove_message_handler(self): pass
            @property
            def local_node_id(self): return None

        with self.assertRaises(TypeError):
            Incomplete()

    def test_missing_local_node_id_raises_type_error(self):
        class Incomplete(BaseTransport):
            def connect(self, device_path=None): pass
            def disconnect(self): pass
            def send(self, message, destination): pass
            def set_message_handler(self, handler): pass
            def remove_message_handler(self): pass
            @property
            def is_connected(self): return False

        with self.assertRaises(TypeError):
            Incomplete()

    def test_complete_implementation_instantiates(self):
        transport = StubTransport()
        self.assertIsInstance(transport, BaseTransport)


# ---------------------------------------------------------------------------
# Context manager tests (BaseTransport default implementation)
# ---------------------------------------------------------------------------


class TestContextManager(unittest.TestCase):
    """Verify __enter__ and __exit__ default implementations on BaseTransport."""

    def test_context_manager_enter_returns_self(self):
        transport = StubTransport()
        result = transport.__enter__()
        self.assertIs(result, transport)

    def test_context_manager_exit_calls_disconnect(self):
        transport = StubTransport()
        transport.connect()
        transport.__exit__(None, None, None)
        self.assertTrue(transport.disconnect_called)

    def test_context_manager_with_statement(self):
        transport = StubTransport()
        with transport:
            transport.connect()
            self.assertTrue(transport.is_connected)
        self.assertFalse(transport.is_connected)
        self.assertTrue(transport.disconnect_called)

    def test_context_manager_disconnect_on_exception(self):
        transport = StubTransport()
        try:
            with transport:
                transport.connect()
                raise ValueError("test error")
        except ValueError:
            pass
        self.assertTrue(transport.disconnect_called)



# ---------------------------------------------------------------------------
# Import structure
# ---------------------------------------------------------------------------


class TestModuleImports(unittest.TestCase):
    """Verify public API is accessible from expected import paths."""

    def test_import_from_transport_base(self):
        from transport.base import BaseTransport
        from transport.base import TransportError
        from transport.base import TransportConnectionError
        from transport.base import TransportSendError
        from transport.base import MessageHandler
        self.assertIsNotNone(BaseTransport)
        self.assertIsNotNone(MessageHandler)

    def test_import_from_transport_package(self):
        from transport import BaseTransport
        from transport import TransportError
        from transport import TransportConnectionError
        from transport import TransportSendError
        from transport import MessageHandler
        self.assertIsNotNone(BaseTransport)
        self.assertIsNotNone(MessageHandler)


if __name__ == "__main__":
    unittest.main()
