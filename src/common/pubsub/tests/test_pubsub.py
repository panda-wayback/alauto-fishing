import threading

from common.pubsub import EventBus


def test_publish_delivers_same_event():
    bus = EventBus()
    got = []
    bus.subscribe("t", got.append)
    event = object()
    bus.publish("t", event)
    assert got == [event]


def test_duplicate_subscribe_called_once():
    bus = EventBus()
    got = []
    bus.subscribe("t", got.append)
    bus.subscribe("t", got.append)
    bus.publish("t", 1)
    assert got == [1]


def test_unsubscribe_stops_delivery_and_unknown_is_silent():
    bus = EventBus()
    got = []
    bus.subscribe("t", got.append)
    bus.unsubscribe("t", got.append)
    bus.unsubscribe("t", got.append)
    bus.unsubscribe("other", got.append)
    bus.publish("t", 1)
    assert got == []


def test_failing_subscriber_does_not_block_others():
    bus = EventBus()
    got = []

    def boom(_):
        raise RuntimeError("boom")

    bus.subscribe("t", boom)
    bus.subscribe("t", got.append)
    bus.publish("t", 1)
    assert got == [1]


def test_topics_are_isolated():
    bus = EventBus()
    a, b = [], []
    bus.subscribe("a", a.append)
    bus.subscribe("b", b.append)
    bus.publish("a", 1)
    assert a == [1] and b == []


def test_publish_without_subscribers_is_noop():
    EventBus().publish("nobody", 1)


def test_concurrent_publish_counts():
    bus = EventBus()
    lock = threading.Lock()
    count = [0]

    def inc(_):
        with lock:
            count[0] += 1

    bus.subscribe("t", inc)
    threads = [
        threading.Thread(target=lambda: [bus.publish("t", i) for i in range(200)])
        for _ in range(8)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert count[0] == 1600
