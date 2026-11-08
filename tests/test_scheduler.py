import unittest
from unittest.mock import MagicMock, patch

from hltv_api.collector import CollectionError
from hltv_api.scheduler import collect_cycle, run


class SchedulerTests(unittest.TestCase):
    def test_cycle_reuses_one_client_and_closes_it(self):
        store = MagicMock()
        with patch("hltv_api.scheduler.Collector") as factory:
            client = factory.return_value
            client.collect.side_effect = [[{"id": 1}], [{"id": 2}]]
            collect_cycle(store)
            self.assertEqual([c.args[0] for c in client.collect.call_args_list], ["results", "upcoming"])
            self.assertEqual(store.save.call_count, 2)
            client.close.assert_called_once()

    def test_failed_first_request_skips_second_and_closes_client(self):
        store = MagicMock()
        with patch("hltv_api.scheduler.Collector") as factory:
            factory.return_value.collect.side_effect = CollectionError("blocked")
            with self.assertRaises(CollectionError):
                collect_cycle(store)
            factory.return_value.collect.assert_called_once_with("results")
            factory.return_value.close.assert_called_once()
            store.save.assert_not_called()

    def test_failures_wait_for_next_cycle_and_can_stop(self):
        stopped = MagicMock()
        stopped.is_set.side_effect = [False, True]
        with patch("hltv_api.scheduler.collect_cycle", side_effect=CollectionError("blocked")) as cycle:
            with self.assertLogs("hltv-scheduler", level="ERROR"):
                run(MagicMock(), 1800, stopped)
            cycle.assert_called_once()
            stopped.wait.assert_called_once_with(1800)

    def test_too_frequent_schedule_rejected(self):
        with self.assertRaises(ValueError):
            run(MagicMock(), 60, MagicMock())
