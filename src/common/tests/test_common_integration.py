import common
from common.pubsub import EventBus


def test_pubsub_submodule_usable_via_common_package():
    import common.pubsub

    assert common.pubsub.EventBus is EventBus
    got = []
    bus = EventBus()
    bus.subscribe("t", got.append)
    bus.publish("t", 1)
    assert got == [1]
