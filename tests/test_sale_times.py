import unittest
from unittest.mock import Mock

from railwatch_sale_times import SaleTimeService, parse_schedules


def record(name="北京", code="BJP", sale="1000", **extra):
    return {"station_name": name, "station_telecode": code, "sale_time": sale,
            "start_date": "20100101", "stop_date": "20991231", **extra}


class SaleTimeTests(unittest.TestCase):
    def test_official_shape_and_malformed_records(self):
        data = parse_schedules({"status": True, "data": [record(), record(), record(sale="2500"),
            record(start_date="20260230"), record(stop_date="20000101"), None]})
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["sale_time"], "10:00")
        self.assertEqual(data[0]["start_date"], "2010-01-01")
        for payload in ({"data": [record()]}, {"status": True, "data": []}, "<html>error</html>"):
            with self.assertRaises(ValueError):
                parse_schedules(payload)

    def test_exact_station_and_cache_shared_across_stations(self):
        fetch = Mock(return_value=parse_schedules({"status": True, "data": [record(), record("北京南", "VNP", "1245")]}))
        service = SaleTimeService(fetch, lambda: 1000)
        self.assertEqual(service.query("北京")["schedules"][0]["station_code"], "BJP")
        self.assertEqual(service.query("北京南")["schedules"][0]["sale_time"], "12:45")
        self.assertEqual(service.query("京")["status"], "not_found")
        fetch.assert_called_once()

    def test_expired_cache_is_marked_stale_on_failure_and_retry_is_throttled(self):
        clock = Mock(return_value=1000)
        fetch = Mock(return_value=parse_schedules({"status": True, "data": [record()]}))
        service = SaleTimeService(fetch, clock)
        service.query("北京")
        clock.return_value = 4600
        fetch.side_effect = OSError("offline")
        result = service.query("北京")
        self.assertEqual(result["status"], "stale")
        self.assertEqual(result["checked_at"], 1000)
        self.assertEqual(result["expires_at"], 4600)
        self.assertIsNotNone(result["warning"])
        service.query("北京", True)
        self.assertEqual(fetch.call_count, 2)
        clock.return_value = 4660
        service.query("北京")
        self.assertEqual(fetch.call_count, 3)

    def test_force_refresh_recovery_and_invalid_inputs(self):
        clock = Mock(return_value=1000)
        fetch = Mock(side_effect=OSError("offline"))
        service = SaleTimeService(fetch, clock)
        self.assertEqual(service.query("北京")["status"], "unavailable")
        clock.return_value = 1060
        fetch.side_effect = None
        fetch.return_value = parse_schedules({"status": True, "data": [record()]})
        self.assertEqual(service.query("北京", True)["status"], "available")
        clock.return_value = 1120
        service.query("北京", True)
        self.assertEqual(fetch.call_count, 3)
        for station, force in [(None, False), ("", False), ("a" * 41, False), ("北京", "true")]:
            with self.assertRaises(ValueError):
                service.query(station, force)

    def test_runtime_dispatch_keeps_lookup_read_only(self):
        from railwatch_runtime import RailWatchRuntime
        bridge = Mock()
        bridge.station_sale_times.return_value = {"status": "not_found"}
        runtime = RailWatchRuntime(bridge=bridge)
        try:
            result = runtime._dispatch("stationSaleTimes", {"station": "北京", "force": True})
            self.assertEqual(result, {"status": "not_found"})
            bridge.station_sale_times.assert_called_once_with("北京", True)
            bridge.start_monitor.assert_not_called()
            bridge.save_config.assert_not_called()
        finally:
            runtime._executor.shutdown(wait=True)


if __name__ == "__main__":
    unittest.main()
