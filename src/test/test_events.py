"""Test the events manager and collections."""
import pytest
from unittest.mock import Mock, create_autospec

from event import EventManager


def event_func(arg):
    pass


def test_simple_register() -> None:
    """"Test registering events in the manager."""
    man = EventManager()
    func1 = create_autospec(event_func)
    func2 = create_autospec(event_func)
    ctx1 = object()
    ctx2 = object()

    man.register(ctx1, int, func1)

    func1.assert_not_called()
    func2.assert_not_called()

    man(ctx1, 5)

    func1.assert_called_once_with(5)
    func2.assert_not_called()
    func1.reset_mock()

    # Different context, not fired.
    man(ctx2, 12)

    func1.assert_not_called()
    func2.assert_not_called()

    man.register(ctx2, int, func2)

    func1.assert_not_called()
    func2.assert_not_called()

    man(ctx2, 34)
    func1.assert_not_called()
    func2.assert_called_once_with(34)
    func2.reset_mock()


def test_unregister() -> None:
    """"Test unregistering events in the manager."""
    man = EventManager()
    func1 = create_autospec(event_func)
    func2 = create_autospec(event_func)
    ctx = object()

    man.register(ctx, bool, func1)
    man.register(ctx, bool, func2)
    man(ctx, True)

    func1.assert_called_once_with(True)
    func2.assert_called_once_with(True)
    func1.reset_mock()
    func2.reset_mock()

    with pytest.raises(KeyError):
        man.unregister(ctx, int, func1)
    with pytest.raises(KeyError):
        man.unregister(45, bool, func1)
    man.unregister(ctx, bool, func1)

    func1.assert_not_called()
    func2.assert_not_called()

    man(ctx, False)

    func1.assert_not_called()
    func2.assert_called_once_with(False)


def test_register_nonearg() -> None:
    """"Test registering events with no arg in the manager."""
    man = EventManager()
    func1 = Mock()
    func2 = create_autospec(event_func)
    ctx1 = object()
    ctx2 = object()

    man.register(ctx1, None, func1)

    func1.assert_not_called()
    func2.assert_not_called()

    man(ctx1)

    func1.assert_called_once_with(None)
    func2.assert_not_called()
    func1.reset_mock()

    # Different context, not fired.
    man(ctx2)

    func1.assert_not_called()
    func2.assert_not_called()

    man.register(ctx2, None, func2)

    func1.assert_not_called()
    func2.assert_not_called()

    man(ctx2, None)
    func1.assert_not_called()
    func2.assert_called_once_with(None)
    func2.reset_mock()


def test_unregister_nonearg() -> None:
    """"Test unregistering events in the manager."""
    man = EventManager()
    func1 = create_autospec(event_func)
    func2 = create_autospec(event_func)
    ctx = object()

    man.register(ctx, None, func1)
    man.register(ctx, None, func2)
    man(ctx)

    func1.assert_called_once_with(None)
    func2.assert_called_once_with(None)
    func1.reset_mock()
    func2.reset_mock()

    with pytest.raises(KeyError):
        man.unregister(ctx, int, func1)
    with pytest.raises(KeyError):
        man.unregister(45, None, func1)
    man.unregister(ctx, None, func1)

    func1.assert_not_called()
    func2.assert_not_called()

    man(ctx)

    func1.assert_not_called()
    func2.assert_called_once_with(None)
